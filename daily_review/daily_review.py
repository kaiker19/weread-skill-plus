#!/usr/bin/env python3
"""
微信读书每日阅读回顾 v2
触发：cron weread-daily-review 每日 23:00 Asia/Shanghai
输出：[AGENT_DAILY_DATA] JSON → agent LLM 使用 prompts/daily_summary.md 合成 → 推送
无新内容时静默退出
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
    get_random_record,
)
from echoes import extract_keywords, find_echoes

CHINA_TZ = timezone(timedelta(hours=8))


def utc8_today_start() -> int:
    now = datetime.now(CHINA_TZ)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp())


def main():
    today_start = utc8_today_start()
    today_str = datetime.fromtimestamp(today_start, tz=CHINA_TZ).strftime("%Y-%m-%d")

    sync_all(verbose=False)

    new_highlights = get_highlights_since(today_start)
    new_reviews = get_reviews_since(today_start)

    if not new_highlights and not new_reviews:
        rec = get_random_record(today_start)
        if rec:
            now_ts = int(time.time())
            rec["days_ago"] = max(0, (now_ts - (rec.get("create_time") or now_ts)) // 86400)
            payload = {
                "date":              today_str,
                "books_active":      [],
                "new_highlights":    [],
                "new_reviews":       [],
                "cross_book_echoes": [],
                "historical_echo":   rec,
                "prompt_ref":        "prompts/daily_summary.md",
            }
            print(f"微信读书每日回顾 | {today_str}")
            print(f"今日无新内容，历史回声来自 {rec['days_ago']} 天前《{rec['book_title']}》")
            print()
            print("[AGENT_DAILY_DATA]")
            print(json.dumps(payload, ensure_ascii=False))
        return

    books_active = {}
    for h in new_highlights:
        books_active[h["book_id"]] = {
            "title":  h.get("book_title", ""),
            "author": h.get("book_author", ""),
        }
    for r in new_reviews:
        books_active[r["book_id"]] = {
            "title":  r.get("book_title", ""),
            "author": r.get("book_author", ""),
        }

    today_book_ids = set(books_active.keys())

    all_text = [h["content"] for h in new_highlights] + [r["content"] for r in new_reviews]

    # 跨书呼应：优先语义检索（embedding + 余弦），无嵌入源或召回为空时回退 jieba/LIKE
    today_records = [
        {"source_type": "highlight", "source_id": h["highlight_id"],
         "content": h["content"], "book_id": h["book_id"]}
        for h in new_highlights
    ] + [
        {"source_type": "review", "source_id": r["review_id"],
         "content": r["content"], "book_id": r["book_id"]}
        for r in new_reviews
    ]

    echoes = None
    echo_mode = "jieba"
    try:
        from embedding import semantic_echoes
        echoes = semantic_echoes(today_records, today_book_ids, today_start)
        if echoes:
            echo_mode = "semantic"
    except Exception as e:  # 语义层任何异常都不应阻断每日总结
        print(f"[daily_review] 语义检索异常，回退 jieba：{e}", file=sys.stderr)
        echoes = None

    if not echoes:  # None（无嵌入源）或 []（语义无召回）→ 回退 jieba
        keywords = extract_keywords(all_text)
        echoes = find_echoes(today_book_ids, keywords, today_start)
        echo_mode = "jieba"

    payload = {
        "date": today_str,
        "books_active": list(books_active.values()),
        "new_highlights": [
            {
                "book_title":    h.get("book_title", ""),
                "author":        h.get("book_author", ""),
                "content":       h["content"],
                "chapter_title": h.get("chapter_title", ""),
            }
            for h in new_highlights
        ],
        "new_reviews": [
            {
                "book_title": r.get("book_title", ""),
                "author":     r.get("book_author", ""),
                "content":    r["content"],
            }
            for r in new_reviews
        ],
        "cross_book_echoes": [
            {
                "book_title":  e["book_title"],
                "author":      e.get("author", ""),
                "content":     e["content"],
                "matched_kw":  e["matched_kw"],
                "days_ago":    e["days_ago"],
                "source_type": e["source_type"],
                "similarity":  e.get("similarity"),
            }
            for e in echoes
        ],
        "echo_mode": echo_mode,
        "prompt_ref": "prompts/daily_summary.md",
    }

    print(f"微信读书每日回顾 | {today_str}")
    print(f"新增 {len(new_highlights)} 条划线 / {len(new_reviews)} 条批注"
          + (f" / {len(echoes)} 条跨书呼应（{echo_mode}）" if echoes else ""))
    print()
    print("[AGENT_DAILY_DATA]")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()