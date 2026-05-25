#!/usr/bin/env python3
"""
微信读书每日阅读回顾
输出今日阅读数据，供 agent 总结并推送
"""

import json, subprocess, os
from datetime import datetime, timezone, timedelta

STATE_FILE = os.path.expanduser("~/.openclaw/workspace/data/reading_daily_state.json")
CHINA_TZ = timezone(timedelta(hours=8))

SKILL_VERSION = "1.0.3"

def apiRequest(apiName, payload=None):
    with open(os.path.expanduser("~/.openclaw/openclaw.json")) as f:
        d = json.load(f)
    api_key = d["skills"]["entries"]["weread-skills"]["env"]["WEREAD_API_KEY"]
    payload = payload or {}
    payload["api_name"] = apiName
    payload["skill_version"] = SKILL_VERSION
    body = json.dumps(payload)
    result = subprocess.run(
        ["curl", "-s", "-X", "POST",
         "https://i.weread.qq.com/api/agent/gateway",
         "-H", f"Authorization: Bearer {api_key}",
         "-H", "Content-Type: application/json",
         "-d", body],
        capture_output=True, text=True
    )
    try:
        return json.loads(result.stdout)
    except:
        return {"errcode": -1, "errmsg": result.stdout[:200]}

def utc8_now():
    return datetime.now(CHINA_TZ)

def utc8_day_range():
    now = utc8_now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp(), now.timestamp()

def fmt_time(ts):
    if not ts:
        return "无记录"
    t = datetime.fromtimestamp(ts, tz=CHINA_TZ)
    return t.strftime("%H:%M")

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False)

def get_today_books():
    start_ts, _ = utc8_day_range()
    shelf = apiRequest("/shelf/sync")
    if shelf.get("errcode"):
        return []
    books = shelf.get("books", [])
    return [(b, b.get("readUpdateTime", 0)) for b in books if b.get("readUpdateTime", 0) >= start_ts]

def get_progress(book_id):
    return apiRequest("/book/getprogress", {"bookId": book_id})

def get_today_marks(book_id):
    start_ts, _ = utc8_day_range()
    result = apiRequest("/book/bookmarklist", {"bookId": book_id})
    if result.get("errcode"):
        return []
    return [m for m in result.get("updated", []) if m.get("createTime", 0) >= start_ts]

def main():
    now = utc8_now()
    date_str = now.strftime("%Y-%m-%d")

    print(f"📚 微信读书今日回顾 | {date_str}")
    print("=" * 40)

    today_books = get_today_books()
    state = load_state()

    if not today_books:
        print("今日暂无阅读记录 📭")
        print("=" * 40)
        save_state({})
        return

    print(f"今日阅读 {len(today_books)} 本\n")

    all_data = []

    for book, read_time in sorted(today_books, key=lambda x: x[1], reverse=True):
        book_id = book.get("bookId")
        title = book.get("title", "?")
        author = book.get("author", "?")
        finish = book.get("finishReading", 0)

        today_marks = get_today_marks(book_id)
        mark_count = len(today_marks)

        current_pct = 0
        prev_pct = state.get(book_id, {}).get("progress", 0)
        progress_info = get_progress(book_id)
        if progress_info.get("errcode") == 0:
            current_pct = progress_info.get("book", {}).get("progress", 0)

        if finish:
            status = "✅ 已读完"
        else:
            delta = current_pct - prev_pct
            if delta > 0:
                status = f"📖 {current_pct}% (+{delta}%)"
            elif current_pct > 0:
                status = f"📖 {current_pct}%"
            else:
                status = "📖 在读"

        mark_texts = [m.get("markText", "").strip() for m in today_marks if m.get("markText", "").strip()]

        print(f"{status} {title}")
        print(f"  作者: {author}")
        if read_time:
            print(f"  阅读时间: {fmt_time(read_time)}")
        if mark_count > 0:
            print(f"  今日新增划线 {mark_count} 条:")
            for i, t in enumerate(mark_texts):
                print(f"    [{i+1}] {t}")
        else:
            print(f"  今日无新增划线")
        print()

        all_data.append({
            "title": title, "author": author, "status": status,
            "read_time": fmt_time(read_time), "mark_count": mark_count,
            "mark_texts": mark_texts, "current_pct": current_pct,
        })

    print("=" * 40)

    # 保存进度状态
    new_state = {}
    for book, _ in today_books:
        book_id = book.get("bookId")
        prog = get_progress(book_id)
        p = prog.get("book", {}).get("progress", 0) if prog.get("errcode") == 0 else 0
        new_state[book_id] = {"progress": p}
    save_state(new_state)

    print("\n[AGENT_SUMMARY_DATA]")
    print(json.dumps(all_data, ensure_ascii=False))

if __name__ == "__main__":
    main()