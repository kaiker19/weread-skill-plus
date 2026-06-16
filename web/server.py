#!/usr/bin/env python3
"""
web/server.py — WeRead Dashboard 本地 Web 后端

Usage:
    cd /path/to/weread-skill-plus
    pip install fastapi uvicorn
    python3 web/server.py
    # → http://localhost:8765
"""

import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from knowledge_base import (
    _conn,
    init_db,
    get_all_books,
    get_book,
    get_highlights_for_book,
    get_reviews_for_book,
    search_content,
)

PORT = 8765
FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"

app = FastAPI(title="WeRead Dashboard", version="1.0.0", docs_url="/api/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8765"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Stats ─────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def get_stats():
    with _conn() as c:
        books_total    = c.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        books_finished = c.execute("SELECT COUNT(*) FROM books WHERE finish_time IS NOT NULL").fetchone()[0]
        books_reading  = c.execute("""
            SELECT COUNT(*) FROM books b
            WHERE b.finish_time IS NULL
              AND EXISTS (SELECT 1 FROM highlights h WHERE h.book_id = b.book_id)
        """).fetchone()[0]
        highlights     = c.execute("SELECT COUNT(*) FROM highlights").fetchone()[0]
        reviews        = c.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        last_sync_row  = c.execute("SELECT value FROM sync_state WHERE key='last_sync_ts'").fetchone()
    last_sync_ts = int(last_sync_row[0]) if last_sync_row else None
    return {
        "books_total":    books_total,
        "books_finished": books_finished,
        "books_reading":  books_reading,
        "highlights":     highlights,
        "reviews":        reviews,
        "last_sync_ts":   last_sync_ts,
    }


# ── Books ─────────────────────────────────────────────────────────────────

def _books_with_counts():
    """Books enriched with real highlight/review counts.

    The books.highlight_count/review_count columns are not maintained by sync
    (always 0), so counts are computed live from the highlights/reviews tables.
    """
    books = get_all_books()
    with _conn() as c:
        hc = dict(c.execute(
            "SELECT book_id, COUNT(*) FROM highlights GROUP BY book_id").fetchall())
        rc = dict(c.execute(
            "SELECT book_id, COUNT(*) FROM reviews GROUP BY book_id").fetchall())
    for b in books:
        b["highlight_count"] = hc.get(b["book_id"], 0)
        b["review_count"]    = rc.get(b["book_id"], 0)
    return books


@app.get("/api/books")
def list_books(
    status: Optional[str] = None,
    sort:   str = "engaged",
    q:      Optional[str] = None,
):
    books = _books_with_counts()
    # 注：/shelf/sync 不返回可用 progress（库里全为 0），故"在读"以"未完读且有划线"判定
    if status == "finished":
        books = [b for b in books if b.get("finish_time")]
    elif status == "reading":
        books = [b for b in books if not b.get("finish_time") and b.get("highlight_count", 0) > 0]
    elif status == "unread":
        books = [b for b in books if not b.get("finish_time") and b.get("highlight_count", 0) == 0]
    if q:
        q_l = q.lower()
        books = [b for b in books
                 if q_l in b.get("title", "").lower() or q_l in b.get("author", "").lower()]
    def engaged_key(b):
        # 读完或有划线的书排前面，其次按最近阅读
        engaged = 1 if (b.get("finish_time") or b.get("highlight_count", 0) > 0) else 0
        return (engaged, b.get("last_read_time") or 0)

    key_fn = {
        "engaged":     engaged_key,
        "last_read":   lambda b: b.get("last_read_time") or 0,
        "finish_time": lambda b: b.get("finish_time") or 0,
        "highlights":  lambda b: b.get("highlight_count", 0),
    }.get(sort, engaged_key)
    books.sort(key=key_fn, reverse=True)
    return books


@app.get("/api/books/{book_id}")
def get_book_detail(book_id: str):
    book = get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    highlights = get_highlights_for_book(book_id)
    reviews    = get_reviews_for_book(book_id)

    # 总结优先：有真实读后总结就带上
    summary = None
    try:
        from knowledge_base import get_latest_summary
        s = get_latest_summary("book_completion", book_id=book_id)
        summary = s["content"] if s else None
    except Exception:
        summary = None

    # 提取式速览（纯向量，无 LLM）：质心代表划线
    representative = []
    try:
        from embedding import representative_highlights
        representative = representative_highlights(book_id, n=6)
    except Exception:
        representative = []

    return {
        "book": book,
        "highlights": highlights,
        "reviews": reviews,
        "summary": summary,
        "digest": {"representative": representative},
    }


from pydantic import BaseModel


class LLMSettings(BaseModel):
    endpoint: str
    api_key: str
    model: str
    format: str = "openai"


from knowledge_base import data_dir
_LLM_CFG = data_dir() / "llm.json"


@app.get("/api/settings/llm")
def get_llm_settings():
    """当前 LLM 配置（不回显 key，只报是否已配 + 非敏感字段）。"""
    import json
    if not _LLM_CFG.exists():
        return {"configured": False, "endpoint": "", "model": "", "format": "openai"}
    try:
        cfg = json.loads(_LLM_CFG.read_text())
    except Exception:
        return {"configured": False, "endpoint": "", "model": "", "format": "openai"}
    return {
        "configured": bool(cfg.get("api_key")),
        "endpoint": cfg.get("endpoint", ""),
        "model": cfg.get("model", ""),
        "format": cfg.get("format", "openai"),
    }


@app.post("/api/settings/llm")
def save_llm_settings(s: LLMSettings):
    """保存到 data/llm.json 并测试一次连通性。"""
    import json
    existing = {}
    if _LLM_CFG.exists():
        try:
            existing = json.loads(_LLM_CFG.read_text())
        except Exception:
            existing = {}
    # api_key 留空 = 不修改，沿用已存的（兑现 UI「已保存，留空则不修改」的承诺，
    # 避免把空 key 写坏配置导致测试失败）
    api_key = s.api_key.strip() or existing.get("api_key", "")
    _LLM_CFG.parent.mkdir(parents=True, exist_ok=True)
    _LLM_CFG.write_text(json.dumps({
        "endpoint": s.endpoint.strip(), "api_key": api_key,
        "model": s.model.strip(), "format": s.format.strip() or "openai",
    }, ensure_ascii=False))
    try:
        from llm import chat
        r = chat("只回复两个字：好的", "测试连通")
        return {"ok": True, "sample": (r or "").strip()[:40]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


import threading

# 后台批量任务（进程内单任务）：网页触发"批量生成总结/抽取概念"，前端轮询进度
_job = {"running": False, "kind": None, "total": 0, "done": 0, "ok": 0, "fail": 0, "current": ""}


def _run_backfill(kind: str, force: bool = False):
    global _job
    sys.path.insert(0, str(Path(__file__).parent.parent / "book_summary"))
    try:
        if kind == "summaries":
            from book_summary import build_payload
            from knowledge_base import get_books_needing_summary, save_summary
            from llm import summarize_book
            books = get_books_needing_summary(include_done=force)
            _job.update(total=len(books), done=0, ok=0, fail=0)
            for b in books:
                if not _job["running"]:
                    break
                _job["current"] = b.get("title", "")
                try:
                    txt = summarize_book(build_payload(b))
                    if txt:
                        save_summary("book_completion", txt, book_id=b["book_id"]); _job["ok"] += 1
                    else:
                        _job["fail"] += 1
                except Exception:
                    _job["fail"] += 1
                _job["done"] += 1
        else:  # concepts
            from knowledge_base import (get_books_needing_concepts, get_highlights_for_book,
                                        get_distinct_concept_tags, replace_book_concepts)
            from llm import extract_concepts
            books = get_books_needing_concepts(include_done=force)
            _job.update(total=len(books), done=0, ok=0, fail=0)
            for b in books:
                if not _job["running"]:
                    break
                _job["current"] = b.get("title", "")
                try:
                    cons = extract_concepts(b["title"], get_highlights_for_book(b["book_id"]),
                                            get_distinct_concept_tags())
                    if cons is not None:
                        replace_book_concepts(b["book_id"], cons); _job["ok"] += 1
                    else:
                        _job["fail"] += 1
                except Exception:
                    _job["fail"] += 1
                _job["done"] += 1
    finally:
        _job["running"] = False
        _job["current"] = ""


@app.post("/api/backfill/start")
def backfill_start(kind: str = "summaries", force: bool = False):
    if _job["running"]:
        raise HTTPException(status_code=409, detail="已有批量任务在运行")
    if kind not in ("summaries", "concepts"):
        raise HTTPException(status_code=400, detail="kind 必须是 summaries 或 concepts")
    from llm import llm_available
    if not llm_available():
        raise HTTPException(status_code=409, detail="未配置 LLM，先去设置配置")
    # force=True 连已生成过的也重跑（换模型重抽/重生成）
    _job.update(running=True, kind=kind, total=0, done=0, ok=0, fail=0, current="启动中…")
    threading.Thread(target=_run_backfill, args=(kind, force), daemon=True).start()
    return {"started": True}


@app.post("/api/backfill/stop")
def backfill_stop():
    _job["running"] = False
    return {"stopped": True}


@app.get("/api/backfill/status")
def backfill_status():
    return _job


@app.get("/api/backfill/pending")
def backfill_pending():
    from knowledge_base import get_books_needing_summary, get_books_needing_concepts
    return {"summaries": len(get_books_needing_summary()),
            "concepts": len(get_books_needing_concepts())}


@app.post("/api/sync")
def trigger_sync():
    """手动同步：本地 web 没有 cron，由用户点按钮触发。拉新划线/批注入库，
    并增量嵌入新条目，洞见随之更新。"""
    from sync import sync_all
    summary = sync_all(verbose=False)
    embedded = 0
    try:
        from embedding import backfill
        embedded = backfill(verbose=False)  # 只嵌入缺向量的新条目
    except Exception:
        embedded = 0
    return {**summary, "embedded": embedded}


@app.get("/api/capabilities")
def capabilities():
    """前端据此决定是否显示"生成总结"按钮等。"""
    llm = False
    embed = False
    try:
        from llm import llm_available
        llm = llm_available()
    except Exception:
        llm = False
    try:
        from embedding import active_model
        embed = active_model() is not None
    except Exception:
        embed = False
    return {"llm": llm, "embedding": embed}


class SummaryIn(BaseModel):
    content: str


@app.post("/api/books/{book_id}/summary")
def save_book_summary(book_id: str, s: SummaryIn):
    """手动填写/编辑读后总结（覆盖自动生成的）。"""
    from knowledge_base import save_summary
    text = s.content.strip()
    if not text:
        raise HTTPException(status_code=400, detail="内容为空")
    save_summary("book_completion", text, book_id=book_id)
    return {"ok": True, "summary": text}


@app.post("/api/books/{book_id}/summarize")
def summarize_book_endpoint(book_id: str, force: bool = False):
    """网页主动触发生成读后总结。已有真实总结且非 force → 直接返回，不重复调 LLM。"""
    from knowledge_base import get_latest_summary, save_summary
    if not force:
        existing = get_latest_summary("book_completion", book_id=book_id)
        if existing:
            return {"summary": existing["content"], "regenerated": False}

    try:
        from llm import llm_available, summarize_book
    except Exception:
        raise HTTPException(status_code=409, detail="LLM 模块不可用")
    if not llm_available():
        raise HTTPException(status_code=409,
                            detail="未配置 LLM，去 openclaw 生成或配置 data/llm.json")

    book = get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # 复用 book_summary 的 payload 构造
    sys.path.insert(0, str(Path(__file__).parent.parent / "book_summary"))
    from book_summary import build_payload
    payload = build_payload(book)

    text = summarize_book(payload)
    if not text:
        raise HTTPException(status_code=500, detail="LLM 未返回内容")
    save_summary("book_completion", text, book_id=book_id)
    return {"summary": text, "regenerated": True}


@app.post("/api/books/{book_id}/concepts")
def extract_book_concepts_endpoint(book_id: str):
    """对单本书抽取/重抽概念（换模型后就地重来）。replace_book_concepts 覆盖语义，总是重写。"""
    try:
        from llm import llm_available, extract_concepts
    except Exception:
        raise HTTPException(status_code=409, detail="LLM 模块不可用")
    if not llm_available():
        raise HTTPException(status_code=409, detail="未配置 LLM，先去设置配置")
    from knowledge_base import (get_highlights_for_book, get_distinct_concept_tags,
                                replace_book_concepts)
    book = get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    cons = extract_concepts(book["title"], get_highlights_for_book(book_id),
                            get_distinct_concept_tags())
    if cons is None:
        raise HTTPException(status_code=500, detail="LLM 未返回内容")
    replace_book_concepts(book_id, cons)
    return {"ok": True, "count": len(cons)}


# ── Timeline & categories ─────────────────────────────────────────────────

@app.get("/api/timeline")
def get_timeline():
    """Monthly highlight+review count (last 24 months, UTC+8)."""
    with _conn() as c:
        rows = c.execute("""
            SELECT strftime('%Y-%m', datetime(create_time, 'unixepoch', '+8 hours')) AS month,
                   COUNT(*) AS count
            FROM (
                SELECT create_time FROM highlights WHERE create_time IS NOT NULL
                UNION ALL
                SELECT create_time FROM reviews   WHERE create_time IS NOT NULL
            )
            WHERE create_time > strftime('%s', 'now', '-24 months')
            GROUP BY month ORDER BY month
        """).fetchall()
    return [{"month": r[0], "count": r[1]} for r in rows]


@app.get("/api/categories")
def get_categories():
    with _conn() as c:
        rows = c.execute("""
            SELECT category, COUNT(*) AS count
            FROM books WHERE category != ''
            GROUP BY category ORDER BY count DESC
        """).fetchall()
    return [{"category": r[0], "count": r[1]} for r in rows]


# ── Search ────────────────────────────────────────────────────────────────

@app.get("/api/search")
def search(q: str = Query(..., min_length=1), limit: int = 30):
    with _conn() as c:
        highlights = c.execute("""
            SELECT h.highlight_id AS id, h.content, h.create_time,
                   b.title AS book_title, b.author, b.book_id,
                   h.chapter_title, 'highlight' AS source_type
            FROM highlights h JOIN books b ON h.book_id = b.book_id
            WHERE h.content LIKE ? ORDER BY h.create_time DESC LIMIT ?
        """, (f"%{q}%", limit)).fetchall()
        reviews = c.execute("""
            SELECT r.review_id AS id, r.content, r.create_time,
                   b.title AS book_title, b.author, b.book_id,
                   '' AS chapter_title, 'review' AS source_type
            FROM reviews r JOIN books b ON r.book_id = b.book_id
            WHERE r.content LIKE ? ORDER BY r.create_time DESC LIMIT ?
        """, (f"%{q}%", limit)).fetchall()
    results = [dict(r) for r in list(highlights) + list(reviews)]
    results.sort(key=lambda x: x.get("create_time") or 0, reverse=True)
    return results[:limit]


# ── Cross-book echoes ─────────────────────────────────────────────────────

@app.get("/api/echoes")
def get_echoes(q: str = Query(..., min_length=1), limit: int = 10):
    """Semantic echoes if available, fall back to jieba/ngram keyword search.

    Read-only: uses semantic_search (no DB writes). Both paths return a
    consistent shape (book_id + days_ago) for the frontend.
    """
    try:
        from embedding import semantic_search
        results = semantic_search(q, max_results=limit)
        if results:
            return results
    except Exception:
        pass
    # keyword fallback — normalize shape to match semantic results
    raw = search_content(keyword=q, limit=limit)
    now = int(time.time())
    for r in raw:
        ct = r.get("create_time") or now
        r["days_ago"] = max(0, (now - ct) // 86400)
    return raw


# ── Insight (洞见首页) ─────────────────────────────────────────────────────

@app.get("/api/insight/connections")
def insight_connections(limit: int = 3):
    """锚定最近阅读的跨书连接(对照对)。无向量时返回 []。
    网页是浏览/发现场景：放宽锚点范围(anchor_n)、略降阈值，让连接更丰富、「换一批」有料可换；
    agent 每日回声仍走 cross_book_connections 的严格默认。"""
    try:
        from embedding import cross_book_connections
        # 0.70：实测"债务↔资本/财富/消费"这类明显相关的跨书呼应落在 0.70~0.72，
        # 0.72 会把它们挡掉、导致"今天读了书呼应却不更新"。0.70 仍足够相关。
        return cross_book_connections(limit=limit, anchor_n=80, min_sim=0.70)
    except Exception:
        return []


@app.get("/api/insight/reread")
def insight_reread():
    """每日重读卡:一条够旧、呼应最近阅读的划线/批注。无则 null。"""
    try:
        from embedding import daily_reread
        return daily_reread()
    except Exception:
        return None


@app.get("/api/insight/themes")
def insight_themes(days: int = 30):
    """最近主题:近 days 划线的向量聚类。无则 []。"""
    try:
        from embedding import cluster_recent_themes
        return cluster_recent_themes(days=days)
    except Exception:
        return []


# ── Knowledge graph ────────────────────────────────────────────────────────

@app.get("/api/graph")
def graph():
    try:
        from embedding import build_concept_graph
        return build_concept_graph()
    except Exception:
        return {"nodes": [], "links": []}


@app.get("/api/graph/concept/{tag}")
def graph_concept(tag: str):
    from knowledge_base import get_concept_highlights
    return get_concept_highlights(tag)


@app.get("/api/explore")
def explore(q: str = Query(..., min_length=1), limit: int = 20):
    """统一探索：一次返回 语义命中的概念(点亮图谱) + 语义相近的划线(原文)。
    limit 让消费方「要几条就检索几条」——写作台只显示 8 条就传 8，避免 MMR
    在更大候选上多样化时把边缘但相关的划线挤出前列。"""
    try:
        from embedding import explore_search
        r = explore_search(q, limit=limit)
        if r.get("highlights"):
            return {"concepts": r.get("concepts", []), "highlights": r["highlights"]}
    except Exception:
        pass
    from knowledge_base import search_content
    return {"concepts": [], "highlights": search_content(keyword=q, limit=limit)}


# ── Recent activity ───────────────────────────────────────────────────────

@app.get("/api/recent_activity")
def recent_activity(days: int = 30):
    since = int(time.time()) - days * 86400
    with _conn() as c:
        rows = c.execute("""
            SELECT h.content, h.create_time, b.title AS book_title,
                   b.book_id, b.author, 'highlight' AS source_type
            FROM highlights h JOIN books b ON h.book_id = b.book_id
            WHERE h.create_time > ?
            UNION ALL
            SELECT r.content, r.create_time, b.title AS book_title,
                   b.book_id, b.author, 'review' AS source_type
            FROM reviews r JOIN books b ON r.book_id = b.book_id
            WHERE r.create_time > ?
            ORDER BY create_time DESC LIMIT 50
        """, (since, since)).fetchall()
    return [dict(r) for r in rows]


# ── SPA / static files ────────────────────────────────────────────────────

if FRONTEND_DIST.exists():
    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/")
    @app.get("/{full_path:path}")
    def serve_spa(full_path: str = ""):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(str(FRONTEND_DIST / "index.html"))
else:
    @app.get("/")
    def root():
        return JSONResponse({"message": "WeRead API is running.", "docs": "/api/docs",
                             "note": "Build the frontend (`cd web/frontend && npm run build`) for the web UI."})


if __name__ == "__main__":
    init_db()
    print(f"WeRead Dashboard → http://localhost:{PORT}")
    if not FRONTEND_DIST.exists():
        print("  (Frontend not built — run: cd web/frontend && npm install && npm run build)")
    uvicorn.run("server:app", host="127.0.0.1", port=PORT, reload=True,
                reload_dirs=[str(Path(__file__).parent)])
