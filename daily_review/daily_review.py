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
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

_LIB = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(_LIB))

from sync import sync_all
from knowledge_base import (
    get_highlights_since,
    get_reviews_since,
    search_content,
)

CHINA_TZ = timezone(timedelta(hours=8))

_STOPWORDS = {
    "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一",
    "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有",
    "看", "好", "自己", "这", "那", "里", "不是", "他", "她", "它",
    "我们", "他们", "这个", "那个", "什么", "如果", "但是", "因为", "所以",
    "可以", "已经", "这样", "这种", "一种", "通过", "一些", "这些", "只是",
    "而且", "并且", "或者", "然后", "其实", "对于", "关于", "包括", "以及",
    "时候", "方式", "问题", "事情", "时间", "一个", "一样",
}


def utc8_today_start() -> int:
    now = datetime.now(CHINA_TZ)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp())


def extract_keywords(texts, top_n=8):
    try:
        import jieba
        words = []
        for t in texts:
            words.extend(jieba.cut(t))
        meaningful = [w for w in words if len(w) >= 2 and w not in _STOPWORDS]
        return [w for w, _ in Counter(meaningful).most_common(top_n)]
    except ImportError:
        return []


def find_echoes(today_book_ids, keywords, today_start_ts, max_results=3):
    """jieba keywords → SQL LIKE → cross-book historical matches."""
    if not keywords:
        return []

    seen_keys = set()
    results = []
    now_ts = int(time.time())

    for kw in keywords:
        if len(results) >= max_results:
            break
        candidates = search_content(
            keyword=kw,
            exclude_book_ids=list(today_book_ids) if today_book_ids else None,
            before_ts=today_start_ts,
            limit=2,
        )
        for c in candidates:
            dedup_key = (c["book_title"], c["content"][:50])
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            days_ago = max(0, (now_ts - (c.get("create_time") or now_ts)) // 86400)
            c["days_ago"] = days_ago
            results.append(c)
            if len(results) >= max_results:
                break

    return results


def main():
    today_start = utc8_today_start()
    today_str = datetime.fromtimestamp(today_start, tz=CHINA_TZ).strftime("%Y-%m-%d")

    sync_all(verbose=False)

    new_highlights = get_highlights_since(today_start)
    new_reviews = get_reviews_since(today_start)

    if not new_highlights and not new_reviews:
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
    keywords = extract_keywords(all_text)
    echoes = find_echoes(today_book_ids, keywords, today_start)

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
            }
            for e in echoes
        ],
        "prompt_ref": "prompts/daily_summary.md",
    }

    print(f"微信读书每日回顾 | {today_str}")
    print(f"新增 {len(new_highlights)} 条划线 / {len(new_reviews)} 条批注"
          + (f" / {len(echoes)} 条跨书呼应" if echoes else ""))
    print()
    print("[AGENT_DAILY_DATA]")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()