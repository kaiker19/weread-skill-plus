#!/usr/bin/env python3
"""
lib/echoes.py — 跨书回声的 jieba/LIKE 兜底逻辑（daily + weekly 共用）

主路径是语义检索（lib/embedding.semantic_echoes）；这里是无 embedding 源时的
降级路径：jieba 分词提关键词 → SQL LIKE 召回 → 关键词重合粗排，批注优先。
抽到这里避免 daily_review 和 weekly_review 各维护一份导致逻辑漂移。
"""

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from knowledge_base import search_content

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


def _ngram_keywords(texts, top_n=8):
    """jieba 不可用时的兜底：对中文连续段取 2-3 字 n-gram 计频。"""
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
    """jieba 分词提 top_n 关键词；未装 jieba 则降级 n-gram 并告警一次。"""
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
            print("[echoes] 警告：未安装 jieba，跨书回声改用 n-gram 兜底分词，"
                  "质量下降。建议 `pip install jieba`。", file=sys.stderr)
            _jieba_warned = True
        return _ngram_keywords(texts, top_n)


def find_echoes(exclude_book_ids, keywords, before_ts, max_results=6):
    """关键词 → SQL LIKE → 跨书历史命中。每本书取得分最高一条。

    返回的是「候选池」，不是最终输出：关键词重合是粗排，保持宽松以保证召回，
    真正的精选交给 agent。批注初始分 2、划线 1，优先呈现用户自己的思考。
    """
    if not keywords:
        return []

    seen_keys = set()
    candidates = []
    now_ts = int(time.time())

    for kw in keywords:
        results = search_content(
            keyword=kw,
            exclude_book_ids=list(exclude_book_ids) if exclude_book_ids else None,
            before_ts=before_ts,
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
