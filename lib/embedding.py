#!/usr/bin/env python3
"""
lib/embedding.py — optional semantic layer for weread-skill-plus

Replaces the jieba/LIKE prefilter in cross-book echoes with embedding +
cosine similarity, so synonyms and paraphrase connect ("思维" ↔ "思考").
Fully optional: if no embedding source is available the caller falls back
to the jieba path, so the skill keeps working with zero config.

Embedding source priority (auto-resolved, graceful fallback):
  1. API   — OpenAI-compatible /v1/embeddings, config in data/embedding.json
  2. local — fastembed (ONNX, no torch); Chinese-capable model auto-picked
  3. None  — caller uses jieba/LIKE

Vectors live in the `embeddings` table as float32 BLOB. Retrieval is
brute-force cosine in numpy (the dataset is small — thousands of rows).

CLI:
  python3 lib/embedding.py --status
  python3 lib/embedding.py --backfill [--limit N]
  python3 lib/embedding.py --test "查询文本"
"""

import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from knowledge_base import (
    init_db,
    upsert_embedding,
    count_embeddings,
    count_sources,
    get_primary_model,
    get_sources_missing_embedding,
    load_search_embeddings,
)

ROOT = Path(__file__).parent.parent

# Local model candidates, best Chinese-capable first; we pick the first one
# that the installed fastembed actually supports.
_LOCAL_CANDIDATES = [
    "BAAI/bge-small-zh-v1.5",
    "intfloat/multilingual-e5-small",
    "intfloat/multilingual-e5-large",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
]

_EMBED_BATCH = 64

# Cached active source resolution (kind, model name, handle)
_source_cache = None


# ── numpy guard ──────────────────────────────────────────────────────────────

def _np():
    try:
        import numpy as np
        return np
    except ImportError:
        return None


# ── Source resolution ────────────────────────────────────────────────────────

def _load_api_config():
    """data/embedding.json → {endpoint, api_key, model}. Returns dict or None."""
    from knowledge_base import data_dir
    p = data_dir() / "embedding.json"
    if not p.exists():
        return None
    try:
        cfg = json.loads(p.read_text())
    except Exception:
        return None
    if cfg.get("api_key") and cfg.get("endpoint"):
        cfg.setdefault("model", "text-embedding-3-small")
        return cfg
    return None


def _resolve_source(verbose=False):
    """Return dict {kind, model, handle} or None.

    kind 'api'   → handle = config dict
    kind 'local' → handle = fastembed TextEmbedding instance
    """
    global _source_cache
    if _source_cache is not None:
        return _source_cache

    if _np() is None:
        if verbose:
            print("[embedding] numpy 未安装，语义层不可用（pip install numpy）",
                  file=sys.stderr)
        return None

    # 1. API
    cfg = _load_api_config()
    if cfg:
        _source_cache = {"kind": "api", "model": cfg["model"], "handle": cfg}
        if verbose:
            print(f"[embedding] 源: API ({cfg['endpoint']}, model={cfg['model']})")
        return _source_cache

    # 2. local fastembed
    try:
        from fastembed import TextEmbedding
        supported = {m["model"] for m in TextEmbedding.list_supported_models()}
        name = next((c for c in _LOCAL_CANDIDATES if c in supported), None)
        if name is None:
            name = next((s for s in supported if "multilingual" in s.lower()), None)
        if name is None:
            if verbose:
                print("[embedding] fastembed 无可用多语言模型", file=sys.stderr)
            return None
        # 打包版用持久缓存目录（FASTEMBED_CACHE_DIR），避免临时目录重启被清、反复重下模型
        _cache = os.environ.get("FASTEMBED_CACHE_DIR")
        model = TextEmbedding(model_name=name, cache_dir=_cache) if _cache else TextEmbedding(model_name=name)
        _source_cache = {"kind": "local", "model": name, "handle": model}
        if verbose:
            print(f"[embedding] 源: 本地 fastembed (model={name})")
        return _source_cache
    except ImportError:
        if verbose:
            print("[embedding] 无 API 配置且未安装 fastembed，语义层禁用，"
                  "回退 jieba。", file=sys.stderr)
        return None


def active_model() -> str:
    """Name of the active embedding model, or None if no source."""
    src = _resolve_source()
    return src["model"] if src else None


# ── Embedding ────────────────────────────────────────────────────────────────

def _embed_api(texts, cfg):
    body = {"model": cfg["model"], "input": texts}
    result = subprocess.run(
        ["curl", "-s", "-X", "POST", cfg["endpoint"],
         "-H", f"Authorization: Bearer {cfg['api_key']}",
         "-H", "Content-Type: application/json",
         "-d", json.dumps(body)],
        capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    if "data" not in data:
        raise RuntimeError(f"embedding API error: {str(data)[:200]}")
    items = sorted(data["data"], key=lambda x: x.get("index", 0))
    return [it["embedding"] for it in items]


def _embed_local(texts, src):
    model = src["handle"]
    prep = texts
    # e5 models expect a "query:"/"passage:" prefix; symmetric use is fine.
    if "e5" in src["model"].lower():
        prep = [f"query: {t}" for t in texts]
    return [list(map(float, v)) for v in model.embed(prep)]


def embed_texts(texts, src=None):
    """Embed a list of strings → list of float vectors using the active source."""
    if src is None:
        src = _resolve_source()
    if src is None:
        return None
    if src["kind"] == "api":
        return _embed_api(texts, src["handle"])
    return _embed_local(texts, src)


# ── Backfill / incremental ───────────────────────────────────────────────────

def embed_records(records, src=None, verbose=False, progress=None):
    """Embed and store a list of source rows.

    Each record: {source_type, source_id, content, book_id}.
    Returns count stored.
    """
    if src is None:
        src = _resolve_source(verbose=verbose)
    if src is None:
        return 0
    np = _np()
    model = src["model"]
    done = 0
    for i in range(0, len(records), _EMBED_BATCH):
        batch = records[i:i + _EMBED_BATCH]
        vecs = embed_texts([r["content"] for r in batch], src)
        if vecs is None:
            break
        for rec, v in zip(batch, vecs):
            arr = np.asarray(v, dtype=np.float32)
            upsert_embedding(rec["source_type"], rec["source_id"], rec["book_id"],
                             model, int(arr.shape[0]), arr.tobytes())
            done += 1
        if verbose:
            print(f"  embedded {done}/{len(records)}", file=sys.stderr)
        if progress:
            try:
                progress(done, len(records))
            except Exception:
                pass
    return done


def backfill(limit=None, verbose=True, progress=None):
    """Embed all (or up to `limit`) records lacking a vector for the active model.
    progress(done, total) 每批回调一次，供 UI 展示建索引进度。"""
    init_db()
    src = _resolve_source(verbose=verbose)
    if src is None:
        if verbose:
            print("[embedding] 无可用嵌入源，跳过回填。配置 data/embedding.json "
                  "或 `pip install fastembed`。", file=sys.stderr)
        return 0
    pending = get_sources_missing_embedding(src["model"], limit=limit)
    if verbose:
        total = count_sources()
        have = count_embeddings(src["model"])
        print(f"[embedding] 模型 {src['model']} | 已嵌入 {have}/{total} | "
              f"本次待处理 {len(pending)}")
    if not pending:
        return 0
    t0 = time.time()
    n = embed_records(pending, src=src, verbose=verbose, progress=progress)
    if verbose:
        print(f"[embedding] 完成 {n} 条，用时 {time.time()-t0:.1f}s")
    return n


# ── Semantic echoes ──────────────────────────────────────────────────────────

def _normalize(np, mat):
    mat = np.nan_to_num(np.asarray(mat, dtype=np.float32),
                        nan=0.0, posinf=0.0, neginf=0.0)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


def _quiet_fp(fn):
    """抑制 numpy+Accelerate 对矩阵乘发出的伪 RuntimeWarning
    （divide by zero / overflow / invalid encountered in matmul，macOS 已知问题，
    数据已验证全有限、结果正确）。"""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        np = _np()
        if np is None:
            return fn(*args, **kwargs)
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            return fn(*args, **kwargs)
    return wrapper


# 批注（用户自己的思考）在召回里小幅提权，与 jieba 兜底路径的口径一致
_REVIEW_BOOST = 0.03


@_quiet_fp
def semantic_echoes(today_records, today_book_ids, before_ts,
                    max_results=6, min_sim=0.0, store=True):
    """Embedding-based cross-book echoes.

    Returns None if no embedding source (caller should fall back to jieba),
    or a list (possibly empty) of echo dicts compatible with the jieba path:
      book_title, author, content, matched_kw, days_ago, source_type, similarity

    store=True 时把 today_records 的向量写入索引（每日流程用）；weekly 等
    条目已嵌入的场景传 store=False，避免重复跑模型。排序对 review 小幅提权
    （展示的 similarity 仍是真实余弦）。
    """
    src = _resolve_source()
    if src is None:
        return None
    np = _np()

    recs = [r for r in today_records if r.get("content")]
    if not recs:
        return []

    # 只嵌入一次：既用作查询向量，必要时也写入索引
    qvecs = embed_texts([r["content"] for r in recs], src)
    if not qvecs:
        return []
    if store:
        model = src["model"]
        for rec, v in zip(recs, qvecs):
            arr = np.asarray(v, dtype=np.float32)
            upsert_embedding(rec["source_type"], rec["source_id"], rec["book_id"],
                             model, int(arr.shape[0]), arr.tobytes())

    q = _normalize(np, np.asarray(qvecs, dtype=np.float32))

    rows = load_search_embeddings(src["model"],
                                  exclude_book_ids=list(today_book_ids) if today_book_ids else None,
                                  before_ts=before_ts)
    if not rows:
        return []

    cand = np.frombuffer(b"".join(r["vec"] for r in rows), dtype=np.float32)
    dim = q.shape[1]
    cand = cand.reshape(len(rows), dim)
    cand = _normalize(np, cand)

    sims = cand @ q.T              # (n_cand, n_query)
    best = sims.max(axis=1)        # best match to any of today's items

    now_ts = int(time.time())

    # 每本书保留一条：按「提权后分数」排，但展示真实余弦
    book_best = {}
    for r, s in zip(rows, best):
        raw = float(s)
        if raw < min_sim:
            continue
        eff = raw + (_REVIEW_BOOST if r.get("source_type") == "review" else 0.0)
        t = r["book_title"]
        if t not in book_best or eff > book_best[t][0]:
            book_best[t] = (eff, raw, r)

    ordered = sorted(book_best.values(), key=lambda x: -x[0])[:max_results]

    echoes = []
    for eff, raw, r in ordered:
        ct = r.get("create_time") or now_ts
        echoes.append({
            "book_title":  r["book_title"],
            "author":      r.get("author", ""),
            "content":     r["content"],
            "matched_kw":  "语义相近",
            "days_ago":    max(0, (now_ts - ct) // 86400),
            "source_type": r["source_type"],
            "similarity":  round(raw, 3),
        })
    return echoes


@_quiet_fp
def semantic_search(query_text, exclude_book_ids=None, before_ts=None,
                    max_results=10, min_sim=0.0):
    """Read-only semantic search for the web/query path.

    Unlike semantic_echoes (which is part of the daily write flow and stores
    the day's items), this NEVER writes to the DB. Returns None if no embedding
    source, else a list (possibly empty) of dicts including book_id so callers
    can link to the book.
    """
    src = _resolve_source()
    if src is None:
        return None
    np = _np()
    text = (query_text or "").strip()
    if not text:
        return []

    qvecs = embed_texts([text], src)
    if not qvecs:
        return []
    q = _normalize(np, np.asarray(qvecs, dtype=np.float32))

    rows = load_search_embeddings(src["model"],
                                  exclude_book_ids=exclude_book_ids,
                                  before_ts=before_ts)
    if not rows:
        return []

    cand = np.frombuffer(b"".join(r["vec"] for r in rows), dtype=np.float32)
    cand = _normalize(np, cand.reshape(len(rows), q.shape[1]))
    sims = (cand @ q.T).ravel()

    now_ts = int(time.time())
    book_best = {}
    for r, s in zip(rows, sims):
        if s < min_sim:
            continue
        t = r["book_title"]
        if t not in book_best or s > book_best[t][0]:
            book_best[t] = (float(s), r)

    ordered = sorted(book_best.values(), key=lambda x: -x[0])[:max_results]
    out = []
    for s, r in ordered:
        ct = r.get("create_time") or now_ts
        out.append({
            "book_id":     r["book_id"],
            "book_title":  r["book_title"],
            "author":      r.get("author", ""),
            "content":     r["content"],
            "source_type": r["source_type"],
            "days_ago":    max(0, (now_ts - ct) // 86400),
            "similarity":  round(s, 3),
        })
    return out


# ── Insight engines (read-only, pure numpy over stored vectors) ──────────────
# 这些只读已存向量，不需要运行期 embedding 源（web 端即使没装 fastembed 也能用）。

def _load_all_vectors(model):
    """Return (rows, normalized matrix) for all stored vectors of a model."""
    np = _np()
    if np is None or not model:
        return None, None
    rows = load_search_embeddings(model)
    if not rows:
        return None, None
    mat = np.frombuffer(b"".join(r["vec"] for r in rows), dtype=np.float32)
    mat = mat.reshape(len(rows), -1)
    return rows, _normalize(np, mat)


def _recent_indices(rows, recent_days, fallback_n=50):
    """Indices of highlights/reviews from the last `recent_days`; if none,
    the `fallback_n` most recent by create_time."""
    now = int(time.time())
    cutoff = now - recent_days * 86400
    idx = [i for i, r in enumerate(rows) if (r.get("create_time") or 0) >= cutoff]
    if idx:
        return idx
    order = sorted(range(len(rows)), key=lambda i: -(rows[i].get("create_time") or 0))
    return order[:fallback_n]


def _latest_indices(rows, n=24):
    """最近读的 n 条（按 create_time 倒序）。洞见锚定"你刚读的"，而不是
    30 天里相似度最高的——这样今天读什么，洞见就反映什么。"""
    return sorted(range(len(rows)), key=lambda i: -(rows[i].get("create_time") or 0))[:n]


def _meta(r):
    now = int(time.time())
    ct = r.get("create_time") or now
    return {
        "content":    r["content"],
        "book_id":    r["book_id"],
        "book_title": r["book_title"],
        "author":     r.get("author", ""),
        "days_ago":   max(0, (now - ct) // 86400),
    }


@_quiet_fp
def cross_book_connections(limit=3, anchor_n=24, min_sim=0.78):
    """锚定"你最新读的"那批划线：为它们找其他书里语义最近的历史划线，组成对照对。
    返回 [{anchor, echo, similarity}]，echo 与 anchor 必来自不同书。"""
    np = _np()
    model = get_primary_model()
    rows, mat = _load_all_vectors(model)
    if rows is None:
        return []

    recent_idx = _latest_indices(rows, anchor_n)   # 锚定最新读的那批
    book_ids = np.array([r["book_id"] for r in rows], dtype=object)
    rec_mat = mat[recent_idx]                     # (R, dim)
    sims_all = mat @ rec_mat.T                     # (N, R)

    pairs = []
    for col, ai in enumerate(recent_idx):
        sims = sims_all[:, col].copy()
        sims[book_ids == rows[ai]["book_id"]] = -1.0   # 排除同书与自身
        bi = int(sims.argmax())
        s = float(sims[bi])
        if s > 0:
            pairs.append((s, ai, bi))

    # 先按相似度去重，得到一池"较强候选"，再从中随机挑——保质量又有新鲜感（换一批会变）
    pairs.sort(key=lambda x: -x[0])
    pool, seen_echo, seen_pair = [], set(), set()
    for s, ai, bi in pairs:
        a, e = rows[ai], rows[bi]
        if e["source_id"] in seen_echo:
            continue
        bp = tuple(sorted([a["book_id"], e["book_id"]]))
        if bp in seen_pair:
            continue
        seen_echo.add(e["source_id"])
        seen_pair.add(bp)
        pool.append((s, ai, bi))
        if len(pool) >= max(limit * 3, 8):   # 取 top 一池（如 8-9 条）
            break

    # 抬阈值提准：只从足够强的候选里挑（宁少勿滥）；若一条都没过线，保底给最强的 1 条
    strong = [p for p in pool if p[0] >= min_sim]
    if strong:
        chosen = random.sample(strong, min(limit, len(strong)))
    elif pool:
        chosen = [max(pool, key=lambda x: x[0])]   # 不空场：给最准的一条
    else:
        chosen = []
    chosen.sort(key=lambda x: -x[0])
    return [{"anchor": _meta(rows[ai]), "echo": _meta(rows[bi]), "similarity": round(s, 3)}
            for s, ai, bi in chosen]


@_quiet_fp
def daily_reread(min_age_days=90, recent_days=30, top_k=20):
    """浮现一条够旧、且呼应最近阅读的划线/批注。按当天定种子，一天稳定、每天换。"""
    np = _np()
    model = get_primary_model()
    rows, mat = _load_all_vectors(model)
    if rows is None:
        return None

    now = int(time.time())
    old_cutoff = now - min_age_days * 86400
    old_idx = [i for i, r in enumerate(rows) if (r.get("create_time") or 0) < old_cutoff]
    if not old_idx:
        return None

    recent_idx = _latest_indices(rows, recent_days if recent_days < 60 else 24)
    anchor = _normalize(np, mat[recent_idx].mean(axis=0, keepdims=True))[0]  # (dim,)

    old_mat = mat[old_idx]
    sims = old_mat @ anchor                         # (len old,)
    k = min(top_k, len(old_idx))
    topk_local = np.argsort(-sims)[:k]
    seed = int(now // 86400)                         # 按天轮换
    pick_local = int(topk_local[seed % k])
    chosen = old_idx[pick_local]
    r = rows[chosen]

    # "为什么现在"：最近阅读里与之最相近的那本书
    rec_sims = mat[recent_idx] @ mat[chosen]
    why_book = rows[recent_idx[int(rec_sims.argmax())]]["book_title"]

    out = _meta(r)
    out["source_type"] = r["source_type"]
    out["why"] = {"anchor_book_title": why_book}
    return out


@_quiet_fp
def cluster_recent_themes(days=30, max_k=4):
    """近 days 划线按向量聚类，返回 [{label_content, book_title, count, book_count}]。
    纯 numpy k-means(余弦=归一化点积);代表句取离簇心最近的一条。"""
    np = _np()
    model = get_primary_model()
    rows, mat = _load_all_vectors(model)
    if rows is None:
        return []

    now = int(time.time())
    cutoff = now - days * 86400
    idx = [i for i, r in enumerate(rows) if (r.get("create_time") or 0) >= cutoff]
    if len(idx) < 8:
        return []

    sub = mat[idx]                                  # (n, dim) 已归一化
    n = len(idx)
    k = min(max_k, max(2, n // 12))

    rng = np.random.default_rng(int(now // 86400))  # 按天稳定
    # k-means++ 选初始中心
    centers = [sub[rng.integers(n)]]
    for _ in range(k - 1):
        d = 1.0 - (sub @ np.array(centers).T).max(axis=1)   # 到最近中心的距离
        d = np.clip(d, 0, None)
        probs = d / d.sum() if d.sum() > 0 else None
        centers.append(sub[rng.choice(n, p=probs)])
    centers = _normalize(np, np.array(centers))

    assign = None
    for _ in range(10):
        assign = (sub @ centers.T).argmax(axis=1)
        new = []
        for c in range(k):
            pts = sub[assign == c]
            new.append(centers[c] if len(pts) == 0 else pts.mean(axis=0))
        centers = _normalize(np, np.array(new))

    themes = []
    for c in range(k):
        members = [idx[j] for j in range(n) if assign[j] == c]
        if not members:
            continue
        msub = mat[members]
        rep = members[int((msub @ centers[c]).argmax())]
        themes.append({
            "label_content": rows[rep]["content"],
            "book_title":    rows[rep]["book_title"],
            "count":         len(members),
            "book_count":    len({rows[m]["book_id"] for m in members}),
        })
    themes.sort(key=lambda x: -x["count"])
    return themes


@_quiet_fp
def representative_highlights(book_id, n=6):
    """提取式速览：取离本书划线质心最近的 n 条，作为最具代表性的划线（纯向量）。"""
    np = _np()
    model = get_primary_model()
    if np is None or not model:
        return []
    from knowledge_base import load_book_embeddings
    rows = load_book_embeddings(book_id, model, source_type="highlight")
    if not rows:
        return []
    mat = np.frombuffer(b"".join(r["vec"] for r in rows), dtype=np.float32)
    mat = _normalize(np, mat.reshape(len(rows), -1))
    centroid = _normalize(np, mat.mean(axis=0, keepdims=True))[0]
    sims = mat @ centroid
    order = np.argsort(-sims)[:n]
    return [{"content": rows[i]["content"], "similarity": round(float(sims[i]), 3)}
            for i in order]


@_quiet_fp
def hybrid_search(query, limit=20, k_dense=40, k_sparse=40, rrf_k=60, mmr_lambda=0.72):
    """混合检索：语义(dense)+关键词(sparse)用 RRF 融合排名，再 MMR 去冗余。
    catch 精确词(人名/短语)又懂语义，结果相关且不重复。无嵌入源 → 退化关键词。"""
    from knowledge_base import search_content
    np = _np()
    src = _resolve_source()
    model = get_primary_model()
    if src is None or np is None or not model:
        return search_content(keyword=query, limit=limit)

    rows = load_search_embeddings(model)   # 全部划线+批注向量及元数据
    if not rows:
        return search_content(keyword=query, limit=limit)
    qv = embed_texts([query], src)
    if not qv:
        return search_content(keyword=query, limit=limit)

    q = _normalize(np, np.asarray(qv, dtype=np.float32))[0]
    cand = np.frombuffer(b"".join(r["vec"] for r in rows), dtype=np.float32).reshape(len(rows), -1)
    cand = _normalize(np, cand)
    sims = cand @ q

    dense_idx = list(map(int, np.argsort(-sims)[:k_dense]))
    ql = query.strip()
    sparse_idx = [i for i, r in enumerate(rows) if ql and ql in r["content"]][:k_sparse]

    # RRF 融合
    rrf = {}
    for rank, i in enumerate(dense_idx):
        rrf[i] = rrf.get(i, 0.0) + 1.0 / (rrf_k + rank)
    for rank, i in enumerate(sparse_idx):
        rrf[i] = rrf.get(i, 0.0) + 1.0 / (rrf_k + rank)
    fused = sorted(rrf, key=lambda i: -rrf[i])[: max(limit * 3, 40)]

    # MMR 去冗余
    selected, pool = [], list(fused)
    while pool and len(selected) < limit:
        if not selected:
            best = pool[0]
        else:
            sel_mat = cand[selected]
            best = max(pool, key=lambda i: mmr_lambda * float(sims[i])
                       - (1 - mmr_lambda) * float((cand[i] @ sel_mat.T).max()))
        selected.append(best); pool.remove(best)

    now = int(time.time())
    out = []
    for i in selected:
        r = rows[i]; ct = r.get("create_time") or now
        out.append({"content": r["content"], "book_id": r["book_id"],
                    "book_title": r["book_title"], "author": r.get("author", ""),
                    "source_type": r["source_type"], "similarity": round(float(sims[i]), 3),
                    "days_ago": max(0, (now - ct) // 86400), "create_time": r.get("create_time")})
    return out


@_quiet_fp
def explore_search(query, limit=20, concept_floor=0.6):
    """统一探索：一次混合检索得到划线，并把命中划线**归到各自最近的概念**来点亮图谱。
    图谱高亮 = 右栏划线所属概念，两边同源一致；也修了"人名查询点不亮概念"。"""
    from knowledge_base import search_content
    np = _np()
    src = _resolve_source()
    model = get_primary_model()
    fallback = {"highlights": search_content(keyword=query, limit=limit), "concepts": []}
    if src is None or np is None or not model:
        return fallback
    rows = load_search_embeddings(model)
    qv = embed_texts([query], src)
    if not rows or not qv:
        return fallback

    q = _normalize(np, np.asarray(qv, dtype=np.float32))[0]
    cand = _normalize(np, np.frombuffer(b"".join(r["vec"] for r in rows),
                                        dtype=np.float32).reshape(len(rows), -1))
    sims = cand @ q

    # 混合：dense top-K + 关键词子串，RRF 融合
    dense_idx = list(map(int, np.argsort(-sims)[:40]))
    ql = query.strip()
    sparse_idx = [i for i, r in enumerate(rows) if ql and ql in r["content"]][:40]
    rrf = {}
    for rank, i in enumerate(dense_idx):
        rrf[i] = rrf.get(i, 0.0) + 1.0 / (60 + rank)
    for rank, i in enumerate(sparse_idx):
        rrf[i] = rrf.get(i, 0.0) + 1.0 / (60 + rank)
    fused = sorted(rrf, key=lambda i: -rrf[i])[: max(limit * 3, 40)]

    # MMR 去冗余
    selected, pool = [], list(fused)
    while pool and len(selected) < limit:
        if not selected:
            best = pool[0]
        else:
            sm = cand[selected]
            best = max(pool, key=lambda i: 0.72 * float(sims[i])
                       - 0.28 * float((cand[i] @ sm.T).max()))
        selected.append(best); pool.remove(best)

    now = int(time.time())
    highlights = []
    for i in selected:
        r = rows[i]; ct = r.get("create_time") or now
        highlights.append({"content": r["content"], "book_id": r["book_id"],
                           "book_title": r["book_title"], "author": r.get("author", ""),
                           "source_type": r["source_type"], "similarity": round(float(sims[i]), 3),
                           "days_ago": max(0, (now - ct) // 86400), "create_time": r.get("create_time")})

    # 概念高亮 = 命中划线各自最近的概念
    # 关键词命中的划线(确实含查询词)照常归属；纯语义召回的划线要够相关(≥0.5)才参与，
    # 避免"阿尔都塞"召回的弱划线把"债务可持续性"这种无关概念点亮
    concepts, seen = [], set()
    sparse_set = set(sparse_idx)
    vtags, cmat = _concept_vectors()
    if cmat is not None:
        for i in selected[:14]:
            if i not in sparse_set and float(sims[i]) < 0.5:
                continue
            csims = cmat @ cand[i]
            b = int(csims.argmax())
            if float(csims[b]) >= concept_floor and vtags[b] not in seen:
                seen.add(vtags[b]); concepts.append(vtags[b])
    return {"highlights": highlights, "concepts": concepts}


def _concept_vectors(max_nodes=200):
    """(tags, 归一化矩阵)——每个概念的"语境向量"=其支持划线向量均值。"""
    from collections import defaultdict
    from knowledge_base import _conn
    np = _np()
    model = get_primary_model()
    if np is None or not model:
        return [], None
    with _conn() as c:
        rows = c.execute("SELECT tag FROM concepts GROUP BY tag ORDER BY COUNT(*) DESC LIMIT ?",
                         (max_nodes,)).fetchall()
        tags = [r["tag"] for r in rows]
        if not tags:
            return [], None
        ph = ",".join("?" * len(tags))
        vr = c.execute(f"""
            SELECT cc.tag AS tag, e.vec AS vec FROM concepts cc
            JOIN embeddings e ON e.source_type='highlight' AND e.source_id=cc.source_id AND e.model=?
            WHERE cc.source_type='highlight' AND cc.tag IN ({ph})
        """, (model, *tags)).fetchall()
    acc = defaultdict(list)
    for r in vr:
        acc[r["tag"]].append(np.frombuffer(r["vec"], dtype=np.float32))
    vtags = [t for t in tags if t in acc]
    if not vtags:
        return [], None
    mat = _normalize(np, np.stack([np.mean(np.stack(acc[t]), axis=0) for t in vtags]))
    return vtags, mat


@_quiet_fp
def match_concepts(query, top_n=12, min_sim=0.4):
    """语义匹配概念：概念只要**有一条划线**和查询相近就点亮（取该概念各划线
    与查询相似度的最大值，而非均值——均值会稀释信号）。
    这样搜"苏格拉底"能点亮挂着苏格拉底相关划线的"灵魂/真理/形相"等概念。"""
    from collections import defaultdict
    from knowledge_base import _conn
    np = _np()
    src = _resolve_source()
    model = get_primary_model()
    if src is None or np is None or not model:
        return []
    qv = embed_texts([query], src)
    if not qv:
        return []
    q = _normalize(np, np.asarray(qv, dtype=np.float32))[0]
    with _conn() as c:
        vr = c.execute("""
            SELECT cc.tag AS tag, e.vec AS vec FROM concepts cc
            JOIN embeddings e ON e.source_type='highlight' AND e.source_id=cc.source_id AND e.model=?
            WHERE cc.source_type='highlight'
        """, (model,)).fetchall()
    if not vr:
        return []
    best = defaultdict(float)
    for r in vr:
        v = np.frombuffer(r["vec"], dtype=np.float32)
        nv = np.linalg.norm(v) or 1.0
        s = float((v / nv) @ q)
        if s > best[r["tag"]]:
            best[r["tag"]] = s
    ranked = sorted(best.items(), key=lambda x: -x[1])
    return [t for t, s in ranked[:top_n] if s >= min_sim]


@_quiet_fp
def build_concept_graph(max_nodes=200, sim_threshold=0.70, per_node=3):
    """概念知识图谱（语境分布式语义，可跨书、可解释）：
      节点 = 概念，大小 = 关联划线数；
      每个概念用**它支持划线的向量均值**作为"语境向量"（不是裸名字），
      边 = 语境向量相似度高的概念对（每个概念取最相近 top-K 且超阈值）。
    这样"限度(柏拉图)↔门槛(金融)"因语境不同而不连，"估值↔价值"等真正相关的
    跨书概念才连——跨书关联来自真实划线语境，而非短名字。"""
    from collections import defaultdict
    from knowledge_base import _conn
    np = _np()
    model = get_primary_model()
    with _conn() as c:
        rows = c.execute("""
            SELECT tag, COUNT(*) AS n, COUNT(DISTINCT book_id) AS nb
            FROM concepts GROUP BY tag ORDER BY n DESC LIMIT ?
        """, (max_nodes,)).fetchall()
        tags = [r["tag"] for r in rows]
        nodes = [{"id": r["tag"], "val": int(r["n"]), "books": int(r["nb"])} for r in rows]
        if not tags or np is None or not model:
            return {"nodes": nodes, "links": []}
        ph = ",".join("?" * len(tags))
        vrows = c.execute(f"""
            SELECT cc.tag AS tag, e.vec AS vec
            FROM concepts cc
            JOIN embeddings e ON e.source_type='highlight'
                              AND e.source_id = cc.source_id AND e.model = ?
            WHERE cc.source_type='highlight' AND cc.tag IN ({ph})
        """, (model, *tags)).fetchall()

    acc = defaultdict(list)
    for r in vrows:
        acc[r["tag"]].append(np.frombuffer(r["vec"], dtype=np.float32))
    vtags = [t for t in tags if t in acc]
    if len(vtags) < 2:
        return {"nodes": nodes, "links": []}
    mat = np.stack([np.mean(np.stack(acc[t]), axis=0) for t in vtags])
    mat = _normalize(np, mat)
    sims = mat @ mat.T

    seen, links = set(), []
    for i in range(len(vtags)):
        order = np.argsort(-sims[i])
        cnt = 0
        for j in order:
            if j == i:
                continue
            s = float(sims[i, j])
            if s < sim_threshold:
                break
            key = (min(i, j), max(i, j))
            if key not in seen:
                seen.add(key)
                links.append({"source": vtags[i], "target": vtags[j], "value": round(s, 3)})
            cnt += 1
            if cnt >= per_node:
                break

    # 救援：给孤立概念连上它最相近的邻居，避免一堆孤点飘着
    linked = set()
    for l in links:
        linked.add(l["source"]); linked.add(l["target"])
    for i, t in enumerate(vtags):
        if t in linked:
            continue
        order = np.argsort(-sims[i])
        for j in order:
            if j != i:
                links.append({"source": t, "target": vtags[j], "value": round(float(sims[i, j]), 3)})
                break
    return {"nodes": nodes, "links": links}


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cli():
    args = sys.argv[1:]
    init_db()

    if "--status" in args:
        src = _resolve_source(verbose=True)
        if src is None:
            print("无可用嵌入源（未配置 API，未安装 fastembed）。语义层禁用，回退 jieba。")
            return
        total = count_sources()
        have = count_embeddings(src["model"])
        print(f"可嵌入记录: {total}")
        print(f"已嵌入(当前模型): {have}")
        print(f"待回填: {total - have}")
        return

    if "--backfill" in args:
        limit = None
        if "--limit" in args:
            limit = int(args[args.index("--limit") + 1])
        backfill(limit=limit, verbose=True)
        return

    if "--test" in args:
        query = args[args.index("--test") + 1]
        src = _resolve_source(verbose=True)
        if src is None:
            print("无嵌入源，无法测试。")
            return
        np = _np()
        qv = _normalize(np, np.asarray(embed_texts([query], src), dtype=np.float32))
        rows = load_search_embeddings(src["model"])
        if not rows:
            print("索引为空，先运行 --backfill。")
            return
        cand = _normalize(np, np.frombuffer(
            b"".join(r["vec"] for r in rows), dtype=np.float32
        ).reshape(len(rows), qv.shape[1]))
        sims = (cand @ qv.T).ravel()
        top = sorted(zip(sims, rows), key=lambda x: -x[0])[:8]
        print(f"\n与「{query}」语义最近的划线/批注：")
        for s, r in top:
            print(f"  [{s:.3f}] 《{r['book_title'][:18]}》[{r['source_type']}] "
                  f"{r['content'][:50]}")
        return

    print(__doc__)


if __name__ == "__main__":
    _cli()
