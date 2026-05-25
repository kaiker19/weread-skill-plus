#!/usr/bin/env python3
"""
微信读书主题回顾
跨书划线聚合，按关键词搜索；不传关键词时自动聚类所有划线，从文本中提炼主题方向
"""

import json, subprocess, os, sys, time
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter

try:
    import jieba
    import sklearn.cluster
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

CHINA_TZ = timezone(timedelta(hours=8))
SKILL_VERSION = "1.0.3"
SLEEP_INTERVAL = 0.3

# 常用停用词（简单的中文停用词表）
STOPWORDS = {
    "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
    "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
    "自己", "这", "他", "来", "还", "那", "这个", "什么", "可以", "这样", "因为",
    "所以", "但", "而", "又", "如", "于", "与", "或", "等", "把", "被", "让", "从",
    "向", "对", "地", "之", "其", "里", "所", "为", "以", "及", "已", "已", "已",
    "吗", "呢", "吧", "啊", "哦", "嗯", "呀", "哈", "嘛", "呵", "咧",
    "的", "地", "得", "着", "过", "了", "会", "能", "能", "要", "想", "可",
    "你", "我", "他", "她", "它", "们", "咱", "咱", "您",
    "个", "些", "种", "本", "点", "下", "些", "种", "回", "次", "遍",
    "中", "大", "小", "多", "少", "前", "后", "里", "外", "内", "间",
    "时", "年", "月", "日", "号", "天", "样", "像", "做", "当", "年",
    "开始", "然后", "就是", "其实", "不是", "可能", "如果", "因为", "所以",
    "什么", "怎么", "多少", "哪里", "为什么", "如何", "是否",
    "。", "，", "！", "？", "、", "；", "：", "\"", "'", "（", "）", "【", "】",
    "《", "》", "—", "…", "～", "-", "·", ".", ",", "!", "?", ";", ":",
    "0","1","2","3","4","5","6","7","8","9","10",
    "第", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
}

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
    with open(os.path.expanduser("~/.openclaw/openclaw.json")) as f:
        return json.load(f)["skills"]["entries"]["weread-skills"]["env"]["WEREAD_API_KEY"]

def get_all_notebooks(key):
    """遍历所有有笔记的书"""
    all_books = []
    last_sort = None
    while True:
        params = {"count": 20}
        if last_sort:
            params["lastSort"] = last_sort
        result = api(key, "/user/notebooks", params)
        if result.get("errcode"):
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
    result = api(key, "/book/bookmarklist", {"bookId": book_id})
    if result.get("errcode"):
        return []
    return result.get("updated", [])

def extract_words(text, top_n=200):
    """用 jieba 提取中文词/短语，返回 Counter"""
    words = []
    for word in jieba.cut(text):
        word = word.strip()
        if len(word) >= 2 and word not in STOPWORDS and not word.isdigit():
            words.append(word)
    return Counter(words)

def cluster_themes(segments, n_clusters=8):
    """
    简单聚类：将相似主题的划线归到一起
    策略：用词频向量 + sklearn KMeans（如果可用），否则用纯词频排序人工归纳
    """
    if not segments:
        return []

    if HAS_SKLEARN:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.cluster import KMeans

        # 用 jieba 分词后的文本
        texts = [" ".join(jieba.cut(s["markText"])) for s in segments]

        try:
            vectorizer = TfidfVectorizer(max_features=500, min_df=2)
            X = vectorizer.fit_transform(texts)
            n_c = min(n_clusters, len(texts) - 1)
            km = KMeans(n_clusters=max(2, n_c), random_state=42, n_init=5)
            labels = km.fit_predict(X)
        except Exception:
            labels = [0] * len(texts)
    else:
        labels = [0] * len(texts)

    # 按 cluster 分组
    clusters = defaultdict(list)
    for i, label in enumerate(labels):
        clusters[label].append(segments[i])

    return clusters

def summarize_cluster(segments):
    """从一组划线中提取共同主题词"""
    all_text = " ".join(s["markText"] for s in segments)
    counter = extract_words(all_text, top_n=30)
    top_words = [w for w, _ in counter.most_common(15)]
    return top_words

def build_theme_report(all_books, key):
    """
    核心功能：聚类所有划线，提炼主题方向
    """
    print("\n📚 获取所有划线数据...")
    all_segments = []  # {bookTitle, bookAuthor, markText, bookId, createTime}

    for i, book_info in enumerate(all_books):
        book = book_info.get("book", {})
        book_id = book.get("bookId")
        title = book.get("title", "?")
        author = book.get("author", "?")

        time.sleep(SLEEP_INTERVAL)
        marks = get_bookmarks(key, book_id)

        for m in marks:
            text = m.get("markText", "")
            if text and len(text.strip()) >= 10:
                all_segments.append({
                    "bookId": book_id,
                    "bookTitle": title,
                    "bookAuthor": author,
                    "markText": text.strip(),
                    "createTime": m.get("createTime", 0),
                })

        if (i + 1) % 10 == 0:
            print(f"  已扫描 {i+1}/{len(all_books)} 本书，{len(all_segments)} 条有效划线")

    print(f"\n  总计：{len(all_books)} 本书，{len(all_segments)} 条有效划线")

    if len(all_segments) < 20:
        print("划线太少，无法聚类，返回简单词频统计")
        return simple_word_report(all_segments)

    print(f"\n🔍 正在聚类（{len(all_segments)} 条划线）...")

    # 聚类
    clusters = cluster_themes(all_segments, n_clusters=8)

    # 整理主题
    themes = []
    for label, segs in sorted(clusters.items(), key=lambda x: -len(x[1])):
        top_words = summarize_cluster(segs)
        theme = {
            "theme_id": len(themes) + 1,
            "top_keywords": top_words[:8],
            "segment_count": len(segs),
            "sample_marks": [
                {
                    "text": s["markText"][:150],
                    "bookTitle": s["bookTitle"],
                    "bookAuthor": s["bookAuthor"],
                }
                for s in segs[:4]
            ]
        }
        themes.append(theme)

    # 按划线数量排序
    themes.sort(key=lambda x: -x["segment_count"])

    return themes

def simple_word_report(segments):
    """划线较少时用简单词频"""
    all_text = " ".join(s["markText"] for s in segments)
    counter = extract_words(all_text, top_n=100)
    top = counter.most_common(40)
    return {"type": "word_freq", "top_words": top, "segments": segments[:20]}

# ─── 关键词搜索模式（原有逻辑） ─────────────────────────────────────────────

def search_keyword(all_books, key, keyword):
    print(f"\n🔍 在所有书籍中搜索「{keyword}」...")
    matched = []

    for i, book_info in enumerate(all_books):
        book = book_info.get("book", {})
        book_id = book.get("bookId")
        title = book.get("title", "?")
        author = book.get("author", "?")

        time.sleep(SLEEP_INTERVAL)
        marks = get_bookmarks(key, book_id)

        for m in marks:
            text = m.get("markText", "")
            if keyword.lower() in text.lower():
                matched.append({
                    "bookId": book_id,
                    "title": title,
                    "author": author,
                    "markText": text.strip(),
                    "createTime": m.get("createTime", 0),
                })

        if (i + 1) % 10 == 0:
            print(f"  已扫描 {i+1}/{len(all_books)} 本，当前匹配 {len(matched)} 条")

    return matched

# ─── 主函数 ────────────────────────────────────────────────────────────────

def main():
    key = get_key()
    now = datetime.now(CHINA_TZ)

    print(f"📚 微信读书主题回顾")
    print(f"时间: {now.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    # 获取所有有笔记的书
    print("\n📚 扫描有笔记的书...")
    all_books = get_all_notebooks(key)
    print(f"  共 {len(all_books)} 本书有笔记")

    if len(sys.argv) < 2:
        # ── 自动聚类模式 ──────────────────────────────────────────────────
        print("\n🚀 未提供关键词，进入自动聚类模式...")
        themes = build_theme_report(all_books, key)

        print(f"\n{'='*50}")
        print(f"📖 主题聚类结果（共 {len(themes) if isinstance(themes, list) else 0} 个主题）")
        print(f"{'='*50}")

        if isinstance(themes, dict) and themes.get("type") == "word_freq":
            print("\n📊 高频词 Top40：")
            for word, cnt in themes["top_words"][:20]:
                print(f"  {word} ({cnt})")
        else:
            for t in themes[:10]:
                kw = ", ".join(t["top_keywords"][:5])
                print(f"\n  主题 {t['theme_id']}：{kw}")
                print(f"  划线数：{t['segment_count']}")
                for sample in t["sample_marks"][:2]:
                    txt = sample["text"][:80]
                    print(f"    → [{sample['bookTitle']}] {txt}...")

        # 输出 JSON
        print("\n[AGENT_THEME_JSON]")
        print(json.dumps({
            "mode": "auto_cluster",
            "total_books": len(all_books),
            "themes": themes if isinstance(themes, list) else [],
            "raw_report": themes if isinstance(themes, dict) else None
        }, ensure_ascii=False, indent=2))

    else:
        # ── 关键词搜索模式 ────────────────────────────────────────────────
        keyword = sys.argv[1].strip()
        print(f"\n🔍 关键词搜索模式：「{keyword}」")

        matched = search_keyword(all_books, key, keyword)
        print(f"\n✅ 搜索完成，共 {len(matched)} 条划线匹配")

        if not matched:
            print("没有找到匹配的划线")
            return

        # 按书本分组
        by_book = defaultdict(list)
        for m in matched:
            by_book[m["bookId"]].append(m)

        sorted_books = sorted(by_book.items(), key=lambda x: -len(x[1]))

        print(f"\n{'='*50}")
        print(f"📖 跨书划线聚合（{len(by_book)} 本书有匹配）")
        print(f"{'='*50}")

        for book_id, marks in sorted_books:
            first = marks[0]
            print(f"\n【{first['title']}】— {first['author']} ({len(marks)}条)")
            for m in marks:
                text = m["markText"].strip()
                if len(text) > 100:
                    text = text[:100] + "..."
                print(f"  > {text}")

        # JSON 输出
        print("\n[AGENT_THEME_JSON]")
        print(json.dumps({
            "mode": "keyword_search",
            "keyword": keyword,
            "total_matches": len(matched),
            "total_books": len(by_book),
            "results": [
                {
                    "title": first["title"],
                    "author": first["author"],
                    "book_id": book_id,
                    "count": len(marks),
                    "marks": [
                        {"text": m["markText"].strip()[:200], "createTime": m.get("createTime", 0)}
                        for m in marks
                    ]
                }
                for book_id, marks in sorted_books
            ]
        }, ensure_ascii=False))

if __name__ == "__main__":
    main()