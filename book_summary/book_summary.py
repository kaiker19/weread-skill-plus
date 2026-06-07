#!/usr/bin/env python3
"""
微信读书读后总结 v1
触发：每日 cron 与 daily_review 同时运行，检测新出现的 finishTime
输出：[AGENT_BOOK_SUMMARY_DATA] JSON → agent LLM 使用 prompts/book_summary.md 合成 → 推送
无新完读书籍时静默退出
"""

import json
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

_LIB = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(_LIB))

from sync import sync_all, _load_api_key
from knowledge_base import (
    get_newly_finished_books,
    get_highlights_for_book,
    get_reviews_for_book,
    save_summary,
    get_sync_state,
    set_sync_state,
)

CHINA_TZ = timezone(timedelta(hours=8))
SKILL_VERSION = "1.0.4"


def _api(api_name, payload=None):
    key = _load_api_key()
    body = {**(payload or {}), "api_name": api_name, "skill_version": SKILL_VERSION}
    result = subprocess.run(
        ["curl", "-s", "-X", "POST",
         "https://i.weread.qq.com/api/agent/gateway",
         "-H", f"Authorization: Bearer {key}",
         "-H", "Content-Type: application/json",
         "-d", json.dumps(body)],
        capture_output=True, text=True,
    )
    try:
        return json.loads(result.stdout)
    except Exception:
        return {"errcode": -1, "errmsg": result.stdout[:200]}


def get_best_bookmarks(book_id):
    """Pull top popular highlights for a book (for reader comparison)."""
    data = _api("/book/bestbookmarks", {"bookId": book_id})
    if data.get("errcode"):
        return []
    return [
        {
            "content":     item.get("markText", "").strip(),
            "total_count": item.get("totalCount", 0),
        }
        for item in data.get("items", [])
        if item.get("markText", "").strip()
    ]


def get_similar_books(book_id):
    """Pull similar book recommendations."""
    data = _api("/book/similar", {"bookId": book_id})
    if data.get("errcode"):
        return []
    books = data.get("books", [])
    return [
        {
            "title":  b.get("title", ""),
            "author": b.get("author", ""),
        }
        for b in books[:3]
        if b.get("title")
    ]


def build_payload(book):
    """Build the full summary payload for one finished book."""
    book_id = book["book_id"]

    highlights = get_highlights_for_book(book_id)
    reviews    = get_reviews_for_book(book_id)

    time.sleep(0.3)
    best       = get_best_bookmarks(book_id)
    time.sleep(0.3)
    similar    = get_similar_books(book_id)

    popular_only = [
        b for b in best
        if not any(
            b["content"] in h["content"] or h["content"] in b["content"]
            for h in highlights
        )
    ][:5]

    finish_dt = None
    if book.get("finish_time"):
        finish_dt = datetime.fromtimestamp(
            book["finish_time"], tz=CHINA_TZ
        ).strftime("%Y-%m-%d")

    return {
        "book": {
            "book_id":    book_id,
            "title":      book.get("title", ""),
            "author":     book.get("author", ""),
            "category":   book.get("category", ""),
            "finish_date": finish_dt,
        },
        "my_highlights": [
            {
                "content":       h["content"],
                "chapter_title": h.get("chapter_title", ""),
            }
            for h in highlights
        ],
        "my_reviews": [
            {"content": r["content"]}
            for r in reviews
        ],
        "popular_highlights": best[:10],
        "popular_not_in_mine": popular_only,
        "similar_books": similar,
        "prompt_ref": "prompts/book_summary.md",
    }


# 冷启动保护：默认只处理最近 N 天完读的书，避免首次运行爆量触发
_COLD_START_DAYS = 30


def main():
    backfill = "--backfill" in sys.argv
    run_all = "--all" in sys.argv

    sync_all(verbose=False)

    if backfill:
        # 批量回填：所有"读完/有划线且无总结"的书（历史也覆盖）
        from knowledge_base import get_books_needing_summary
        books = get_books_needing_summary()
    else:
        # 每日增量：检测新完读。冷启动只看近 30 天，避免历史积压一次性爆量。
        is_cold_start = get_sync_state("book_summary_initialized", "0") == "0"
        if run_all:
            since_ts = None
        elif is_cold_start:
            since_ts = int(time.time()) - _COLD_START_DAYS * 86400
        else:
            since_ts = None
        books = get_newly_finished_books(since_ts=since_ts)
        if is_cold_start:
            set_sync_state("book_summary_initialized", "1")

    if not books:
        return

    for book in books:
        title = book.get("title", book["book_id"])
        payload = build_payload(book)

        print(f"微信读书读后总结 | {title}")
        print(f"划线 {len(payload['my_highlights'])} 条 / "
              f"批注 {len(payload['my_reviews'])} 条 / "
              f"大众热门 {len(payload['popular_highlights'])} 条")
        print(f"book_id={book['book_id']}")
        print()
        print("[AGENT_BOOK_SUMMARY_DATA]")
        print(json.dumps(payload, ensure_ascii=False))
        print()
        # 不再写 [pending] 占位；由 agent 合成后调 lib/save_summary.py 回写真内容。


if __name__ == "__main__":
    main()
