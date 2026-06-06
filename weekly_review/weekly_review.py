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
WEEK_DAYS = 7

_STOPWORDS = {
    "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一",
    "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有",
    "看", "好", "自己", "这", "那", "里", "不是", "他", "她", "它",
    "我们", "他们", "这个", "那个", "什么", "如果", "但是", "因为", "所以",
    "可以", "已经", "这样", "这种", "一种", "通过", "一些", "这些", "只是",
    "而且", "并且", "或者", "然后", "其实", "对于", "关于", "包括", "以及",
    "时候", "方式", "问题", "事情", "时间", "一个", "一样",
}

_jieba_warned = False


def _ngram_keywords(texts, top_n=12):
    import re
    counter = Counter()
    for t in texts:
        for run in re.findall(r"[一-鿿]+", t):
            for n in (2, 3):
                for i in range(len(run) - n + 1):
                    w = run[i:i + n]
                    if w not in _STOPWORDS:
                        counter[w] += 1
    return [w for w, _ in counter.most_common(top_n)]


def extract_keywords(texts, top_n=12):
    global _jieba_warned
    try:
        import jieba
        words = []
        for t in texts:
            words.extend(jieba.cut(t))
        meaningful = [w for w in words if len(w) >= 2 and w not in _STOPWORDS]
        return [w for w, _ in Counter(meaningful).most_common(top_n)]
    except ImportError:
        if not _jieba_warned:
            print("[weekly_review] 警告：未安装 jieba，改用 n-gram 兜底", file=sys.stderr)
            _jieba_warned = True
        return _ngram_keywords(texts, top_n)


def find_echoes(week_book_ids, keywords, week_start_ts, max_results=6):
    """同 daily_review.find_echoes：关键词粗排，每本书取得分最高一条。"""
    if not keywords:
        return []

    seen_keys = set()
    candidates = []
    now_ts = int(time.time())

    for kw in keywords:
        results = search_content(
            keyword=kw,
            exclude_book_ids=list(week_book_ids) if week_book_ids else None,
            before_ts=week_start_ts,
            limit=3,
        )
        for c in results:
            dedup_key = (c["book_title"], c["content"][:50])
            if dedup_key in seen_keys:
                for item in candidates:
                    if (item["book_title"], item["content"][:50]) == dedup_key:
                        item["_score"] += 1
                        break
                continue
            seen_keys.add(dedup_key)
            c["days_ago"] = max(0, (now_ts - (c.get("create_time") or now_ts)) // 86400)
            c["_score"] = 2 if c.get("source_type") == "review" else 1
            candidates.append(c)

    book_best = {}
    for c in candidates:
        t = c["book_title"]
        if t not in book_best or c["_score"] > book_best[t]["_score"]:
            book_best[t] = c

    sorted_c = sorted(book_best.values(), key=lambda x: -x["_score"])
    return [{k: v for k, v in c.items() if k != "_score"} for c in sorted_c[:max_results]]


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
        echoes = semantic_echoes(week_records, week_book_ids, week_start_ts)
        if echoes:
            echo_mode = "semantic"
    except Exception as e:
        print(f"[weekly_review] 语义检索异常，回退 jieba：{e}", file=sys.stderr)
        echoes = None

    if not echoes:
        all_text = [h["content"] for h in highlights] + [r["content"] for r in reviews]
        keywords = extract_keywords(all_text)
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
