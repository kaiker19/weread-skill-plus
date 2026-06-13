#!/usr/bin/env python3
"""
web/extract_concepts.py — 批量抽取各书概念（本地用，走 data/llm.json），供知识图谱。

每本书一次 LLM：吐 3-6 个短概念 + 各自挂的划线，写入 concepts 表。喂已有概念
词表以消除重复；跨书连接由概念名的 embedding 相似度在图层完成（不依赖同名）。
RPM 友好：每本间隔 + 失败退避；可断点续跑（已抽过的书自动跳过）。

用法：
  python3 web/extract_concepts.py --limit 5     # 先试 5 本
  python3 web/extract_concepts.py --delay 3     # 每本间隔（防 RPM）
  python3 web/extract_concepts.py               # 全部待抽取的书
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "web"))

from knowledge_base import (
    get_books_needing_concepts, get_highlights_for_book,
    get_distinct_concept_tags, replace_book_concepts, get_book,
)
import llm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--delay", type=float, default=2.0)
    a = ap.parse_args()

    if not llm.llm_available():
        print("未配置 data/llm.json，无法抽取。")
        return

    books = get_books_needing_concepts()
    if a.limit:
        books = books[:a.limit]
    if not books:
        print("没有待抽取的书（都抽过了）。")
        return
    print(f"待抽取 {len(books)} 本，每本间隔 {a.delay}s（已抽过的会跳过）")

    ok = fail = 0
    for i, b in enumerate(books, 1):
        title = b.get("title", b["book_id"])
        cons = None
        try:
            hl = get_highlights_for_book(b["book_id"])
            existing = get_distinct_concept_tags()  # 每本刷新，词表逐步积累
            for attempt in range(3):
                try:
                    cons = llm.extract_concepts(title, hl, existing)
                    break
                except Exception as e:
                    wait = (attempt + 1) * 10
                    print(f"  [{title[:16]}] 第{attempt+1}次失败（{e}），{wait}s 后重试")
                    time.sleep(wait)
        except Exception as e:
            print(f"[{i}/{len(books)}] ✗ {title[:22]}（{e}）")

        if cons is not None:
            replace_book_concepts(b["book_id"], cons)
            ok += 1
            print(f"[{i}/{len(books)}] ✓ {title[:22]} → {[c['name'] for c in cons]}")
        else:
            fail += 1
            print(f"[{i}/{len(books)}] ✗ {title[:22]}")
        time.sleep(a.delay)

    print(f"完成：成功 {ok}，失败 {fail}。")


if __name__ == "__main__":
    main()
