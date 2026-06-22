#!/usr/bin/env python3
"""
lib/sync.py — Incremental sync from WeChat Reading API to local SQLite

Pulls:
  /shelf/sync          → books table
  /book/bookmarklist   → highlights table (per active book)
  /review/list/mine    → reviews table (per active book, paginated via synckey)

State:
  sync_state['last_sync_ts']            — timestamp of last successful sync
  sync_state['review_synckey_{book_id}'] — per-book review pagination cursor

Usage:
  python3 lib/sync.py             # incremental (only books active since last sync)
  python3 lib/sync.py --force     # re-pull all books regardless of timestamp
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from knowledge_base import (
    init_db,
    upsert_book,
    insert_highlight,
    insert_review,
    get_sync_state,
    set_sync_state,
)

SKILL_VERSION = "1.0.3"


# ── API helpers ────────────────────────────────────────────────────────────

def _load_api_key():
    from knowledge_base import data_dir
    root = Path(__file__).parent.parent
    # 1. data/api_key 文件（推荐，最稳定）—— 打包后落用户目录，与向导写入同源
    key_file = data_dir() / "api_key"
    if key_file.exists():
        val = key_file.read_text(encoding="utf-8").strip()
        if val:
            return val
    # 2. .env 文件（兼容本地开发习惯）
    env_path = root / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("WEREAD_API_KEY="):
                val = line.split("=", 1)[1].strip()
                if val:
                    return val
    raise RuntimeError(
        "WEREAD_API_KEY not found. "
        "Please create data/api_key and paste your key inside."
    )


def _api(api_name, payload=None):
    # 用 Python 内置 urllib，不依赖系统 curl（Windows 可能没有 curl / 冻结后 PATH 找不到 → 500）
    import urllib.request
    import urllib.error
    from knowledge_base import ssl_context
    key = _load_api_key()
    body = {**(payload or {}), "api_name": api_name, "skill_version": SKILL_VERSION}
    req = urllib.request.Request(
        "https://i.weread.qq.com/api/agent/gateway",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"errcode": e.code, "errmsg": f"HTTP {e.code}"}
    except Exception as e:
        return {"errcode": -1, "errmsg": str(e)[:200]}


# ── Sync functions ─────────────────────────────────────────────────────────

def sync_shelf():
    """Pull /shelf/sync → upsert all books. Returns list of normalized book dicts."""
    data = _api("/shelf/sync")
    if data.get("errcode"):
        print(f"[sync] shelf error: {data.get('errmsg', data)}")
        return []

    books = []
    for b in data.get("books", []):
        book_id = b.get("bookId", "")
        if not book_id:
            continue
        finished = b.get("finishReading", 0)
        book = {
            "book_id":        book_id,
            "title":          b.get("title", ""),
            "author":         b.get("author", ""),
            "category":       b.get("category", ""),
            "cover":          b.get("cover", ""),
            "progress":       b.get("progress", 0),
            "finish_time":    b.get("readUpdateTime") if finished else None,
            "last_read_time": b.get("readUpdateTime"),
            "highlight_count": 0,
            "review_count":   0,
        }
        upsert_book(book)
        books.append(book)

    return books


def sync_highlights_for_book(book_id):
    """Pull /book/bookmarklist for one book, insert new highlights.
    Returns count of newly inserted records."""
    data = _api("/book/bookmarklist", {"bookId": book_id})
    if data.get("errcode"):
        return 0

    chapters = {c["chapterUid"]: c.get("title", "") for c in data.get("chapters", [])}

    new_count = 0
    for m in data.get("updated", []):
        content = m.get("markText", "").strip()
        if not content:
            continue
        h = {
            "highlight_id":  m.get("bookmarkId", ""),
            "book_id":       book_id,
            "content":       content,
            "chapter_uid":   m.get("chapterUid"),
            "chapter_title": chapters.get(m.get("chapterUid"), ""),
            "range_val":     m.get("range", ""),
            "create_time":   m.get("createTime"),
        }
        if h["highlight_id"] and insert_highlight(h):
            new_count += 1
    return new_count


def sync_reviews_for_book(book_id):
    """Pull /review/list/mine for one book (paginated via synckey), insert new reviews.
    Stores per-book synckey in sync_state for incremental pulls.
    Returns count of newly inserted records."""
    synckey_key = f"review_synckey_{book_id}"
    synckey = int(get_sync_state(synckey_key, "0"))

    new_count = 0
    while True:
        data = _api("/review/list/mine", {
            "bookid": book_id,
            "synckey": synckey,
            "count": 20,
        })
        if data.get("errcode"):
            break

        for item in data.get("reviews", []):
            rv = item.get("review", {})
            content = rv.get("content", "").strip()
            if not content:
                continue
            r = {
                "review_id":  rv.get("reviewId", ""),
                "book_id":    book_id,
                "content":    content,
                "abstract":   (rv.get("abstract") or "").strip(),
                "chapter_uid": rv.get("chapterUid"),
                "range_val":  rv.get("range", ""),
                "create_time": rv.get("createTime"),
            }
            if not r["review_id"]:
                continue
            if insert_review(r):
                new_count += 1
            elif r["abstract"]:
                update_review_abstract(r["review_id"], r["abstract"])

        new_synckey = data.get("synckey", synckey)
        has_more = data.get("hasMore", 0)
        set_sync_state(synckey_key, str(new_synckey))

        if not has_more or new_synckey == synckey:
            break
        synckey = new_synckey

    return new_count


# ── Orchestration ──────────────────────────────────────────────────────────

def sync_all(force=False, verbose=True):
    """
    Incremental sync. Pulls only books active since last sync (or all if force=True).

    Returns:
      dict with keys: books_total, books_synced, new_highlights, new_reviews
    """
    init_db()

    last_sync_ts = int(get_sync_state("last_sync_ts", "0"))
    now_ts = int(time.time())

    if verbose:
        print(f"[sync] last sync: {last_sync_ts} | force={force}")

    books = sync_shelf()
    if verbose:
        print(f"[sync] shelf: {len(books)} books")

    if force:
        active = books
    else:
        active = [b for b in books if (b.get("last_read_time") or 0) > last_sync_ts]

    if verbose:
        print(f"[sync] syncing content for {len(active)} active book(s)...")

    new_highlights = 0
    new_reviews = 0

    for book in active:
        book_id = book["book_id"]
        title = book.get("title", book_id)

        nh = sync_highlights_for_book(book_id)
        new_highlights += nh

        nr = sync_reviews_for_book(book_id)
        new_reviews += nr

        if verbose and (nh or nr):
            print(f"  [{title}] +{nh} highlights, +{nr} reviews")

        time.sleep(0.3)

    set_sync_state("last_sync_ts", str(now_ts))

    summary = {
        "books_total":   len(books),
        "books_synced":  len(active),
        "new_highlights": new_highlights,
        "new_reviews":   new_reviews,
    }
    if verbose:
        print(f"[sync] complete: {summary}")
    return summary


if __name__ == "__main__":
    force = "--force" in sys.argv
    sync_all(force=force)
