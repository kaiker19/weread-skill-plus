#!/usr/bin/env python3
"""
lib/save_summary.py — 写回命令：agent 合成总结后落库（修 [pending] 占位坑）。

用法（openclaw 批量流程里，合成完一本书后调）：
  python3 lib/save_summary.py --book-id 3300076267 --content "总结文本"
  python3 lib/save_summary.py --type daily --date 2026-06-07 --content "..."
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from knowledge_base import save_summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book-id", default=None)
    ap.add_argument("--type", default="book_completion",
                    choices=["book_completion", "daily"])
    ap.add_argument("--date", default=None)
    ap.add_argument("--content", required=True)
    a = ap.parse_args()
    save_summary(a.type, a.content, book_id=a.book_id, date=a.date)
    print(f"OK: saved {a.type} for {a.book_id or a.date}")


if __name__ == "__main__":
    main()
