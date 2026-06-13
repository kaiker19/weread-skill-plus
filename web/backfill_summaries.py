#!/usr/bin/env python3
"""
web/backfill_summaries.py — 批量生成历史已读书的读后总结（本地用，走 data/llm.json）。

把以前读过、还没总结的书一次性补上速览。RPM 友好：每本之间 sleep；失败退避
重试；可断点续跑（已有真实总结的书自动跳过）。生成后 web 详情页即优先显示总结。

用法：
  python3 web/backfill_summaries.py --limit 3      # 先试 3 本
  python3 web/backfill_summaries.py --delay 5      # 每本间隔 5s（按你的 RPM 调）
  python3 web/backfill_summaries.py                # 全部待总结的书
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "web"))
sys.path.insert(0, str(ROOT / "book_summary"))

from knowledge_base import get_books_needing_summary, save_summary
from book_summary import build_payload
import llm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--delay", type=float, default=3.0, help="每本之间间隔秒数（防 RPM）")
    a = ap.parse_args()

    if not llm.llm_available():
        print("未配置 data/llm.json，无法批量生成。")
        return

    books = get_books_needing_summary()
    if a.limit:
        books = books[:a.limit]
    if not books:
        print("没有待生成的书（都有总结了）。")
        return
    print(f"待生成 {len(books)} 本，每本间隔 {a.delay}s（Ctrl-C 可随时中断，已生成的会保留）")

    ok = fail = 0
    for i, b in enumerate(books, 1):
        title = b.get("title", b["book_id"])
        text = None
        try:
            payload = build_payload(b)
            for attempt in range(3):
                try:
                    text = llm.summarize_book(payload)
                    break
                except Exception as e:
                    wait = (attempt + 1) * 10  # 退避：10s / 20s / 30s，缓解 RPM/限流
                    print(f"  [{title[:18]}] 第{attempt+1}次失败（{e}），{wait}s 后重试")
                    time.sleep(wait)
        except Exception as e:
            print(f"[{i}/{len(books)}] ✗ {title[:24]}（payload 失败：{e}）")

        if text:
            save_summary("book_completion", text, book_id=b["book_id"])
            ok += 1
            print(f"[{i}/{len(books)}] ✓ {title[:24]}")
        else:
            fail += 1
            print(f"[{i}/{len(books)}] ✗ {title[:24]}")
        time.sleep(a.delay)

    print(f"完成：成功 {ok}，失败 {fail}。打开 web 书籍详情即可看总结。")


if __name__ == "__main__":
    main()
