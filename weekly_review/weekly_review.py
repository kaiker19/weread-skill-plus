#!/usr/bin/env python3
"""
微信读书周回顾 v1
触发：cron weread-weekly-review 每周六 21:00 Asia/Shanghai
输出：[AGENT_WEEKLY_DATA] JSON → agent LLM 使用 prompts/weekly_summary.md 合成 → 推送
本周无新内容时静默退出
"""

import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

_LIB = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(_LIB))

from sync import sync_all
from knowledge_base import (
    get_highlights_since,
    get_reviews_since,
)
from echoes import extract_keywords, find_echoes

CHINA_TZ = timezone(timedelta(hours=8))
WEEK_DAYS = 7


def group_by_book(highlights, reviews):
    books = {}
    for h in highlights:
        bid = h["book_id"]
        if bid not in books:
            books[bid] = {
                "book_id":    bid,
                "book_title": h.get("book_title", ""),
                "author":     h.get("book_author", ""),
                "highlights": [],
                "reviews":    [],
            }
        books[bid]["highlights"].append(h["content"])
    for r in reviews:
        bid = r["book_id"]
        if bid not in books:
            books[bid] = {
                "book_id":    bid,
                "book_title": r.get("book_title", ""),
                "author":     r.get("book_author", ""),
                "highlights": [],
                "reviews":    [],
            }
        books[bid]["reviews"].append(r["content"])
    return list(books.values())


def main():
    now = datetime.now(tz=CHINA_TZ)
    week_start = now - timedelta(days=WEEK_DAYS)
    week_start_ts = int(week_start.timestamp())
    week_range = f"{week_start.strftime('%Y-%m-%d')} ~ {now.strftime('%Y-%m-%d')}"

    sync_all(verbose=False)

    highlights = get_highlights_since(week_start_ts)
    reviews    = get_reviews_since(week_start_ts)

    if not highlights and not reviews:
        return

    books_data    = group_by_book(highlights, reviews)
    week_book_ids = {b["book_id"] for b in books_data}

    week_records = [
        {"source_type": "highlight", "source_id": h["highlight_id"],
         "content": h["content"], "book_id": h["book_id"]}
        for h in highlights
    ] + [
        {"source_type": "review", "source_id": r["review_id"],
         "content": r["content"], "book_id": r["book_id"]}
        for r in reviews
    ]

    echoes    = None
    echo_mode = "jieba"
    try:
        from embedding import semantic_echoes
        # store=False：本周条目已在每日流程嵌入过，无需重复跑模型
        echoes = semantic_echoes(week_records, week_book_ids, week_start_ts, store=False)
        if echoes:
            echo_mode = "semantic"
    except Exception as e:
        print(f"[weekly_review] 语义检索异常，回退 jieba：{e}", file=sys.stderr)
        echoes = None

    if not echoes:
        all_text = [h["content"] for h in highlights] + [r["content"] for r in reviews]
        keywords = extract_keywords(all_text, top_n=12)
        echoes   = find_echoes(week_book_ids, keywords, week_start_ts)
        echo_mode = "jieba"

    payload = {
        "week_range": week_range,
        "stats": {
            "books":      len(books_data),
            "highlights": len(highlights),
            "reviews":    len(reviews),
        },
        "books": books_data,
        "cross_week_echoes": [
            {
                "book_title":  e["book_title"],
                "author":      e.get("author", ""),
                "content":     e["content"],
                "matched_kw":  e.get("matched_kw", ""),
                "days_ago":    e["days_ago"],
                "source_type": e["source_type"],
                "similarity":  e.get("similarity"),
            }
            for e in echoes
        ],
        "echo_mode":  echo_mode,
        "prompt_ref": "prompts/weekly_summary.md",
    }

    print(f"微信读书周回顾 | {week_range}")
    print(f"{len(books_data)} 本书 / {len(highlights)} 条划线 / {len(reviews)} 条批注"
          + (f" / {len(echoes)} 条跨周回声（{echo_mode}）" if echoes else ""))
    print()
    print("[AGENT_WEEKLY_DATA]")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
