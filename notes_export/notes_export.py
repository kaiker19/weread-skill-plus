#!/usr/bin/env python3
"""
微信读书笔记导出
导出用户所有划线笔记，支持按关键词筛选
"""

import json, subprocess, os, sys, time
from datetime import datetime, timezone, timedelta

CHINA_TZ = timezone(timedelta(hours=8))
SKILL_VERSION = "1.0.3"
SLEEP_INTERVAL = 0.3
OUTPUT_FILE = os.path.expanduser("~/.openclaw/workspace/data/weread_notes_export.json")

def api(key, name, payload=None):
    payload = payload or {}
    payload["api_name"] = name
    payload["skill_version"] = SKILL_VERSION
    body = json.dumps(payload)
    r = subprocess.run(
        ["curl", "-s", "-X", "POST", "https://i.weread.qq.com/api/agent/gateway",
         "-H", f"Authorization: Bearer {key}",
         "-H", "Content-Type: application/json", "-d", body],
        capture_output=True, text=True
    )
    try:
        return json.loads(r.stdout)
    except:
        return {"errcode": -1, "errmsg": r.stdout[:200]}

def get_key():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # 1. data/api_key 文件（推荐，最稳定）
    key_file = os.path.join(root, "data", "api_key")
    if os.path.exists(key_file):
        val = open(key_file).read().strip()
        if val:
            return val
    # 2. .env 文件（兼容本地开发习惯）
    env_path = os.path.join(root, ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            if line.strip().startswith("WEREAD_API_KEY="):
                val = line.split("=", 1)[1].strip()
                if val:
                    return val
    raise RuntimeError("WEREAD_API_KEY not found. Please create data/api_key and paste your key inside.")

def fmtTime(ts):
    if not ts:
        return "无"
    return datetime.fromtimestamp(ts, tz=CHINA_TZ).strftime("%Y-%m-%d")

def get_all_notebooks(key):
    """遍历所有有笔记的书（分页）"""
    all_books = []
    last_sort = None

    while True:
        params = {"count": 100}
        if last_sort:
            params["lastSort"] = last_sort

        result = api(key, "/user/notebooks", params)
        if result.get("errcode"):
            print(f"获取笔记本失败: {result}")
            break

        books = result.get("books", [])
        all_books.extend(books)

        if result.get("hasMore") != 1:
            break

        if books:
            last_sort = books[-1].get("sort")
        time.sleep(SLEEP_INTERVAL)

    return all_books

def get_bookmarks(key, book_id):
    """获取单本书所有划线"""
    result = api(key, "/book/bookmarklist", {"bookId": book_id})
    if result.get("errcode"):
        return []
    return result.get("updated", [])

def main():
    key = get_key()
    now = datetime.now(CHINA_TZ)

    print(f"📝 微信读书笔记导出 | {now.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    # 获取所有有笔记的书
    print("\n📚 获取有笔记的书...")
    all_books = get_all_notebooks(key)
    total_note_count = sum(
        b.get("reviewCount", 0) + b.get("noteCount", 0) + b.get("bookmarkCount", 0)
        for b in all_books
    )
    print(f"  有笔记的书: {len(all_books)} 本")
    print(f"  笔记总数: {total_note_count} 条")

    # 可选：关键词过滤
    keyword = None
    if len(sys.argv) > 1:
        keyword = sys.argv[1].lower()
        print(f"\n🔍 关键词过滤: {keyword}")

    # 遍历每本书获取划线
    print("\n📖 正在导出划线...")
    all_notes = []
    book_notes_count = {}

    for i, book_info in enumerate(all_books):
        book = book_info.get("book", {})
        book_id = book.get("bookId")
        title = book.get("title", "?")
        author = book.get("author", "?")

        time.sleep(SLEEP_INTERVAL)
        marks = get_bookmarks(key, book_id)

        if keyword:
            marks = [m for m in marks if keyword in m.get("markText", "").lower()]

        if marks:
            book_notes_count[book_id] = {
                "title": title,
                "author": author,
                "note_count": len(marks),
            }
            for m in marks:
                all_notes.append({
                    "bookId": book_id,
                    "title": title,
                    "author": author,
                    "markText": m.get("markText", ""),
                    "chapterUid": m.get("chapterUid"),
                    "createTime": m.get("createTime", 0),
                })

        if (i + 1) % 10 == 0:
            print(f"  已处理 {i+1}/{len(all_books)} 本，当前导出 {len(all_notes)} 条笔记")

    # 输出 Markdown 格式
    print(f"\n📝 导出完成，共 {len(all_notes)} 条笔记（{len(book_notes_count)} 本书有匹配）")

    if not all_notes:
        print("无匹配笔记")
        return

    # 按书分组展示
    print("\n" + "=" * 50)
    print("📖 笔记内容预览（按书分组）")
    print("=" * 50)

    # 按书本数排序
    sorted_books = sorted(book_notes_count.items(), key=lambda x: x[1]["note_count"], reverse=True)

    for book_id, info in sorted_books:
        print(f"\n【{info['title']}】— {info['author']} ({info['note_count']}条)")
        book_marks = [n for n in all_notes if n["bookId"] == book_id]
        for m in book_marks[:5]:
            text = m["markText"].strip()
            if len(text) > 100:
                text = text[:100] + "..."
            print(f"  > {text}")
        if len(book_marks) > 5:
            print(f"  ... 还有 {len(book_marks) - 5} 条")

    # 保存到文件
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "export_time": now.isoformat(),
            "total_notes": len(all_notes),
            "total_books": len(book_notes_count),
            "notes": all_notes,
            "books": book_notes_count,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n💾 已保存到: {OUTPUT_FILE}")
    print("=" * 50)

    # 输出 JSON 供 agent 处理
    print("\n[AGENT_EXPORT_JSON]")
    print(json.dumps({
        "total_notes": len(all_notes),
        "total_books": len(book_notes_count),
        "top_books": [
            {"title": info["title"], "author": info["author"], "note_count": info["note_count"]}
            for _, info in sorted_books[:10]
        ],
        "export_file": OUTPUT_FILE,
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()