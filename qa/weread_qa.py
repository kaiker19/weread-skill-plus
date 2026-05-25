#!/usr/bin/env python3
"""
微信读书书籍 Q&A
功能：根据书名搜书，获取书籍信息、章节结构、全书热门划线
用法：python3 weread_qa.py "书名" [bookId]
"""

import json, subprocess, time, sys, os

SKILL_VERSION = "1.0.3"
SLEEP_INTERVAL = 0.5

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

def get_api_key():
    with open(os.path.expanduser("~/.openclaw/openclaw.json")) as f:
        return json.load(f)["skills"]["entries"]["weread-skills"]["env"]["WEREAD_API_KEY"]

def search_books(key, keyword):
    result = api(key, "/store/search", {"keyword": keyword, "count": 10})
    if result.get("errcode"):
        return []
    return result.get("books", [])

def get_book_info(key, book_id):
    return api(key, "/book/info", {"bookId": book_id})

def get_chapters(key, book_id):
    return api(key, "/book/chapterinfo", {"bookId": book_id})

def get_chapter_bestbookmarks(key, book_id, chapter_uid):
    return api(key, "/book/bestbookmarks", {"bookId": book_id, "chapterUid": chapter_uid})

def main():
    if len(sys.argv) < 2:
        print("用法: python3 weread_qa.py '书名' [bookId]")
        sys.exit(1)

    keyword = sys.argv[1]
    book_id = sys.argv[2] if len(sys.argv) > 2 else None

    key = get_api_key()

    # 如果没提供 bookId，先搜索
    if not book_id:
        print(f"🔍 搜索: {keyword}")
        books = search_books(key, keyword)
        if not books:
            print("未找到相关书籍")
            sys.exit(1)
        # 取第一个结果
        book_id = books[0].get("bookId")
        print(f"找到: {books[0].get('title')} - {books[0].get('author')}")

    # 获取书籍信息
    print(f"\n{'='*50}")
    print(f"📖 {keyword}")
    print(f"{'='*50}\n")

    info = get_book_info(key, book_id)
    if info.get("errcode"):
        print(f"获取书籍信息失败: {info}")
        sys.exit(1)

    print(f"书名: {info.get('title')}")
    print(f"作者: {info.get('author')}")
    if info.get("translator"):
        print(f"译者: {info.get('translator')}")
    print(f"分类: {info.get('category')}")
    if info.get("publisher"):
        print(f"出版社: {info.get('publisher')}")
    if info.get("newRating"):
        print(f"评分: {info.get('newRating')/10:.1f} ({info.get('newRatingCount',0)}人评价)")

    intro = info.get("intro", "")
    if intro:
        print(f"\n简介:\n{intro[:500]}{'...' if len(intro) > 500 else ''}")

    # 获取章节结构
    chapters_r = get_chapters(key, book_id)
    chapters = chapters_r.get("chapters", [])
    if not chapters:
        print("\n无法获取章节结构")
        sys.exit(1)

    print(f"\n📑 章节结构（共 {len(chapters)} 章）")
    print("-" * 50)

    # 跳过封面、版权等前言章节，筛出有实质内容的章节
    skip_prefixes = ["封面", "版权", "目录", "前言", "序", "代序", "引言", "序言", "出版", "题记", "扉页"]
    content_chapters = [
        ch for ch in chapters
        if not any(ch.get("title", "").startswith(p) for p in skip_prefixes)
    ]

    print(f"跳过 {len(chapters) - len(content_chapters)} 个前言章节，遍历 {len(content_chapters)} 个内容章节...\n")

    # 遍历所有内容章节获取热门划线
    chapter_highlights = {}
    for ch in content_chapters:
        uid = ch.get("chapterUid")
        title = ch.get("title", "")
        time.sleep(SLEEP_INTERVAL)

        bm = get_chapter_bestbookmarks(key, book_id, uid)
        items = bm.get("items", [])

        if items:
            chapter_highlights[title] = items

    # 输出结果
    print(f"\n{'='*50}")
    print(f"🔥 热门划线详情（共 {len(chapter_highlights)} 章有划线）")
    print(f"{'='*50}\n")

    total_marks = 0
    for title, items in chapter_highlights.items():
        total_marks += len(items)
        print(f"【{title}】")
        for i, item in enumerate(items):
            text = item.get("markText", "").strip()
            count = item.get("totalCount", 0)
            print(f"  {i+1}. {text}")
            print(f"     └ {count} 人划线")
        print()

    print(f"{'='*50}")
    print(f"📊 统计: {len(chapter_highlights)} 章有划线，共 {total_marks} 条热门划线")

    # 输出 JSON 结构供 agent 二次处理
    json_output = {
        "title": info.get("title"),
        "author": info.get("author"),
        "category": info.get("category"),
        "publisher": info.get("publisher"),
        "rating": info.get("newRating", 0) / 10 if info.get("newRating") else None,
        "rating_count": info.get("newRatingCount", 0),
        "intro": intro[:1000] if intro else None,
        "chapter_count": len(chapters),
        "chapters_with_marks": len(chapter_highlights),
        "total_marks": total_marks,
        "chapters": [
            {
                "title": title,
                "marks": [
                    {"text": item.get("markText", ""), "count": item.get("totalCount", 0)}
                    for item in items
                ]
            }
            for title, items in chapter_highlights.items()
        ]
    }

    print("\n[AGENT_QA_JSON]")
    print(json.dumps(json_output, ensure_ascii=False))

if __name__ == "__main__":
    main()