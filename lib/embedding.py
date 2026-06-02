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
    p = ROOT / "data" / "embedding.json"
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
        model = TextEmbedding(model_name=name)
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

def embed_records(records, src=None, verbose=False):
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
    return done


def backfill(limit=None, verbose=True):
    """Embed all (or up to `limit`) records lacking a vector for the active model."""
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
    n = embed_records(pending, src=src, verbose=verbose)
    if verbose:
        print(f"[embedding] 完成 {n} 条，用时 {time.time()-t0:.1f}s")
    return n


# ── Semantic echoes ──────────────────────────────────────────────────────────

def _normalize(np, mat):
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


def semantic_echoes(today_records, today_book_ids, before_ts,
                    max_results=6, min_sim=0.0):
    """Embedding-based cross-book echoes.

    Returns None if no embedding source (caller should fall back to jieba),
    or a list (possibly empty) of echo dicts compatible with the jieba path:
      book_title, author, content, matched_kw, days_ago, source_type, similarity
    """
    src = _resolve_source()
    if src is None:
        return None
    np = _np()

    today_texts = [r["content"] for r in today_records if r.get("content")]
    if not today_texts:
        return []

    # Make sure today's items are in the index for future days (cheap).
    embed_records(today_records, src=src)

    qvecs = embed_texts(today_texts, src)
    if not qvecs:
        return []
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
    scored = []
    for r, s in zip(rows, best):
        if s < min_sim:
            continue
        scored.append((float(s), r))

    # one best row per book
    book_best = {}
    for s, r in scored:
        t = r["book_title"]
        if t not in book_best or s > book_best[t][0]:
            book_best[t] = (s, r)

    ordered = sorted(book_best.values(), key=lambda x: -x[0])[:max_results]

    echoes = []
    for s, r in ordered:
        ct = r.get("create_time") or now_ts
        echoes.append({
            "book_title":  r["book_title"],
            "author":      r.get("author", ""),
            "content":     r["content"],
            "matched_kw":  "语义相近",
            "days_ago":    max(0, (now_ts - ct) // 86400),
            "source_type": r["source_type"],
            "similarity":  round(s, 3),
        })
    return echoes


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
