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
    get_random_record,
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


_jieba_warned = False


def _ngram_keywords(texts, top_n=8):
    """jieba 不可用时的兜底：对中文连续段取 2-3 字 n-gram 计频。
    质量不如分词，但保证跨书回声不会因缺依赖而整体哑掉；agent 仍会精排。"""
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


def extract_keywords(texts, top_n=8):
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
            print("[daily_review] 警告：未安装 jieba，跨书回声改用 n-gram 兜底分词，"
                  "质量下降。建议 `pip install jieba`。", file=sys.stderr)
            _jieba_warned = True
        return _ngram_keywords(texts, top_n)


def find_echoes(today_book_ids, keywords, today_start_ts, max_results=6):
    """jieba keywords → SQL LIKE → cross-book historical matches.
    遍历全部关键词，每本书最多贡献 1 条（取命中关键词最多的），最终返回 max_results 条。

    这里返回的是「候选池」，不是最终输出。关键词重合计数是粗排，
    保持宽松（默认 6）以保证召回；真正的精选交给 agent —— prompt 会从候选里
    挑 2-3 条写出真实连接、丢弃假呼应。不要在这一层提前砍候选。
    """
    if not keywords:
        return []

    seen_content_keys = set()
    all_candidates = []
    now_ts = int(time.time())

    for kw in keywords:
        candidates = search_content(
            keyword=kw,
            exclude_book_ids=list(today_book_ids) if today_book_ids else None,
            before_ts=today_start_ts,
            limit=3,
        )
        for c in candidates:
            dedup_key = (c["book_title"], c["content"][:50])
            if dedup_key in seen_content_keys:
                for item in all_candidates:
                    if (item["book_title"], item["content"][:50]) == dedup_key:
                        item["_score"] += 1
                        break
                continue
            seen_content_keys.add(dedup_key)
            c["days_ago"] = max(0, (now_ts - (c.get("create_time") or now_ts)) // 86400)
            c["_score"] = 2 if c.get("source_type") == "review" else 1
            all_candidates.append(c)

    # 每本书只保留得分最高的 1 条
    book_best = {}
    for c in all_candidates:
        title = c["book_title"]
        if title not in book_best or c["_score"] > book_best[title]["_score"]:
            book_best[title] = c

    # 按命中关键词数降序，取 top max_results
    sorted_candidates = sorted(book_best.values(), key=lambda x: -x["_score"])
    return [{k: v for k, v in c.items() if k != "_score"}
            for c in sorted_candidates[:max_results]]


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