#!/usr/bin/env python3
"""weread CLI —— 把本地划线库的语义能力以最薄的方式提供出去（与 web、skill 同一套 lib）。

    weread recall "<想法/概念>"   找回相关划线 + 相关概念，markdown 到 stdout
    weread recall "<...>" --json   原始 JSON，供插件/程序消费
    weread concepts                你的概念地图（概念簇 + 最强关联），markdown
    weread concepts --extract      先用 data/llm.json 配的 LLM 抽概念，再渲染
    weread concepts --json         概念图谱原始 JSON（nodes/links）

可 `| pbcopy`，或被 vim / Alfred / Raycast / Obsidian / agent 等 shell-out 调用。
"""
import sys
import re
import json
import argparse
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))


MIN_SIM = 0.60  # 召回相关度下限：宁缺毋滥。实测 0.55~0.60 多是被字面词带偏的弱相关
                # （"安全边际"召回到"组织创新"那类），抬到 0.60 去尾部噪音，真相关基本 ≥0.6


def _recall(args):
    from embedding import explore_search
    r = explore_search(args.query, limit=args.limit)
    hl = [h for h in r.get("highlights", []) if (h.get("similarity") or 0) >= MIN_SIM]
    r["highlights"] = hl
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2)); return
    if not hl:
        print(f"没有与「{args.query}」相关的划线。"); return
    out = [f"## 与「{args.query}」相关的思考 · {len(hl)} 条", ""]
    for h in hl:
        kind = "批注" if h.get("source_type") == "review" else "划线"
        pct = round((h.get("similarity") or 0) * 100)
        text = " ".join((h.get("content") or "").split())
        if len(text) > 200:
            text = text[:200] + "…"
        out += [f"> {text}", f"  —《{h.get('book_title')}》· {kind} · {pct}%", ""]
    if r.get("concepts"):
        out.append("相关概念  " + " · ".join(r["concepts"]))
    print("\n".join(out))


def _extract_concepts():
    """用 data/llm.json 配的 LLM 给缺概念的书抽概念（与网页版同一套逻辑）。"""
    sys.path.insert(0, str(_ROOT / "web"))
    from llm import extract_concepts, llm_available
    from knowledge_base import (get_books_needing_concepts, get_highlights_for_book,
                                get_distinct_concept_tags, replace_book_concepts)
    if not llm_available():
        print("抽取概念需要 LLM：在 data/llm.json 配置 {endpoint, api_key, model, format}。", file=sys.stderr)
        return
    books = get_books_needing_concepts()
    print(f"[concepts] 待抽 {len(books)} 本…", file=sys.stderr)
    for i, b in enumerate(books, 1):
        try:
            cons = extract_concepts(b["title"], get_highlights_for_book(b["book_id"]),
                                    get_distinct_concept_tags())
            if cons is not None:
                replace_book_concepts(b["book_id"], cons)
            print(f"[concepts] {i}/{len(books)} {b['title'][:18]} → {len(cons or [])} 个", file=sys.stderr)
        except Exception as e:
            print(f"[concepts] {i}/{len(books)} {b['title'][:18]} 失败: {str(e)[:60]}", file=sys.stderr)


def _concepts(args):
    if args.extract:
        _extract_concepts()
    from embedding import build_concept_graph
    g = build_concept_graph()
    nodes, links = g.get("nodes", []), g.get("links", [])
    if args.json:
        print(json.dumps(g, ensure_ascii=False, indent=2)); return
    if not nodes:
        print("还没有概念。先 `weread concepts --extract`（需 data/llm.json 配 LLM），或用网页版生成。")
        return
    val = {n["id"]: n.get("val", 1) for n in nodes}
    # union-find 把语义相近的概念聚成簇
    parent = {n["id"]: n["id"] for n in nodes}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for l in links:
        a, b = l.get("source"), l.get("target")
        if a in parent and b in parent:
            parent[find(a)] = find(b)
    from collections import defaultdict
    clusters = defaultdict(list)
    for n in nodes:
        clusters[find(n["id"])].append(n["id"])
    cl = sorted(clusters.values(), key=lambda c: -sum(val[x] for x in c))
    out = [f"## 你的概念地图 · {len(nodes)} 个概念 · {len(links)} 条关联", "",
           "### 概念簇（语义相近的聚在一起，越靠前越核心）"]
    shown = 0
    for c in cl:
        if len(c) < 2:
            continue
        names = sorted(c, key=lambda x: -val[x])
        shown += 1
        out.append(f"**{shown}.** " + " · ".join(names[:12]))
        if shown >= 12:
            break
    singles = sorted([c[0] for c in cl if len(c) == 1], key=lambda x: -val[x])
    if singles:
        out += ["", "**独立概念**　" + " · ".join(singles[:15])]
    top = sorted(links, key=lambda l: -l.get("value", 0))[:10]
    if top:
        out += ["", "### 最强关联"]
        for l in top:
            out.append(f"- {l['source']} ↔ {l['target']}　{round(l.get('value', 0) * 100)}%")
    print("\n".join(out))


def _safe_filename(name):
    name = re.sub(r'[/\\:*?"<>|]', " ", name or "").strip()
    return name[:80] or "untitled"


def _book_tags(bid):
    """某本书的概念标签（去重）。"""
    from knowledge_base import _conn
    with _conn() as c:
        return [r[0] for r in c.execute(
            "SELECT DISTINCT tag FROM concepts WHERE book_id=?", (bid,)).fetchall()]


def _book_body(b, hls, revs, summ, tags, wiki_links=True):
    """书正文 markdown：标题 + 元信息 + 读后总结 + 按章节划线 + 批注 + 概念。
    wiki_links：概念是否用 [[双链]]（Obsidian 用，ima 用纯文本）。"""
    body = [f"# {b.get('title') or ''}"]
    meta = " · ".join(x for x in [b.get("author"), b.get("category")] if x)
    body += [f"> {meta}", ""] if meta else [""]
    if summ and summ.get("content"):
        body += ["## 读后总结", "", summ["content"].strip(), ""]
    if hls:
        body.append(f"## 划线（{len(hls)}）")
        cur = object()
        for h in hls:
            ch = h.get("chapter_title") or ""
            if ch != cur:
                cur = ch
                body += ["", f"### {ch}"] if ch else [""]
            body.append(f"- {' '.join((h.get('content') or '').split())}")
        body.append("")
    if revs:
        body.append(f"## 我的批注（{len(revs)}）")
        for r in revs:
            body.append(f"- {' '.join((r.get('content') or '').split())}")
        body.append("")
    if tags:
        cs = " ".join(f"[[{t}]]" for t in tags) if wiki_links else "  ".join(tags)
        body += ["---", "概念  " + cs]
    return "\n".join(body)


def _render_md(b, hls, revs, summ, tags):
    """一本书 → Obsidian markdown：frontmatter + 正文（含概念 [[双链]]）。"""
    title = (b.get("title") or "").replace('"', '\\"')
    fm = ["---", f'title: "{title}"']
    if b.get("author"):   fm.append(f'author: "{(b["author"] or "").replace(chr(34), "")}"')
    if b.get("category"): fm.append(f'category: "{b["category"]}"')
    fm.append(f'book_id: "{b["book_id"]}"')
    fm.append("source: 微信读书")
    if b.get("finish_time"):
        from datetime import datetime, timezone, timedelta
        fm.append("finished: " + datetime.fromtimestamp(
            b["finish_time"], timezone(timedelta(hours=8))).strftime("%Y-%m-%d"))
    fm.append("tags:")
    for t in ["微信读书"] + tags:
        fm.append(f'  - "{t}"')
    fm.append("---")
    return "\n".join(fm) + "\n\n" + _book_body(b, hls, revs, summ, tags, wiki_links=True) + "\n"


def _export(args):
    from knowledge_base import (get_all_books, get_highlights_for_book,
                                get_reviews_for_book, get_latest_summary)
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    used = set()
    for b in get_all_books():
        bid = b["book_id"]
        hls, revs = get_highlights_for_book(bid), get_reviews_for_book(bid)
        if not hls and not revs:
            continue  # 没划线没批注的书不导
        summ = get_latest_summary("book_completion", book_id=bid)
        name = _safe_filename(b.get("title") or bid)
        if name in used:                 # 仅「同名不同书」才加 book_id 区分；
            name = f"{name}_{bid}"        # 同一本书重导用同一文件名 → 直接覆盖，不再翻倍
        used.add(name)
        (out / (name + ".md")).write_text(
            _render_md(b, hls, revs, summ, _book_tags(bid)), encoding="utf-8")
        n += 1
    print(f"导出 {n} 本书 → {out}/（在 Obsidian 里把该目录作为 vault 或拖进 vault 即可）")


def _ima_sync(args):
    """增量把书同步到 ima 知识库：本地记已导入的 book_id（ima 没有去重/删除接口，
    全靠这边跳过已导，避免重复笔记）。逐本落盘，中断可续。"""
    import time
    import ima
    from knowledge_base import (get_all_books, get_highlights_for_book,
                                get_reviews_for_book, get_latest_summary, data_dir)
    try:
        kbs = ima.list_knowledge_bases()
    except RuntimeError as e:
        print(str(e), file=sys.stderr); return
    if args.list or not args.kb:
        if not kbs:
            print("没有可用的 ima 知识库——先在 ima 客户端建一个（OpenAPI 不能建库）。"); return
        print("可用知识库：" + "、".join(k["name"] for k in kbs))
        if not args.kb:
            print("用 `weread ima --kb <名称>` 增量导入。")
        return
    kb = next((k for k in kbs if k["name"] == args.kb), None)
    if not kb:
        print(f"没找到知识库「{args.kb}」。现有：" + "、".join(k["name"] for k in kbs)); return
    kb_id = kb["id"]
    statef = data_dir() / "ima_synced.json"
    state = json.loads(statef.read_text(encoding="utf-8")) if statef.exists() else {}
    done = set(state.get(kb_id, {}))
    ok = skip = fail = 0
    fails = []
    for b in get_all_books():
        bid = b["book_id"]
        hls, revs = get_highlights_for_book(bid), get_reviews_for_book(bid)
        if not hls and not revs:
            continue
        if bid in done:
            skip += 1; continue
        summ = get_latest_summary("book_completion", book_id=bid)
        md = _book_body(b, hls, revs, summ, _book_tags(bid), wiki_links=False)
        r = ima.add_to_knowledge_base(md, kb_id, b["title"])
        if r.get("media_id"):
            ok += 1
            state.setdefault(kb_id, {})[bid] = r.get("note_id")
            statef.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            print(f"  ✓ {b['title'][:26]}")
        else:
            fail += 1; fails.append((b["title"], r.get("error"), r.get("stage")))
            print(f"  ✗ {b['title'][:26]}：{r.get('error')} @{r.get('stage')}")
        time.sleep(0.7)  # 限速防频控
    print(f"\n完成：新导入 {ok}，跳过(已导) {skip}，失败 {fail} → 知识库「{args.kb}」")
    for t, e, s in fails:
        print(f"  失败：{t} — {e} @{s}")


def main():
    p = argparse.ArgumentParser(prog="weread", description="本地划线库的语义能力（召回 / 概念地图）")
    sub = p.add_subparsers(dest="cmd", required=True)

    rc = sub.add_parser("recall", help="按想法/概念找回相关划线与概念")
    rc.add_argument("query", help="一个想法、概念或一段话")
    rc.add_argument("-n", "--limit", type=int, default=8, help="返回条数（默认 8）")
    rc.add_argument("--json", action="store_true", help="输出原始 JSON")
    rc.set_defaults(func=_recall)

    cc = sub.add_parser("concepts", help="你的概念地图（概念簇 + 最强关联）")
    cc.add_argument("--extract", action="store_true", help="先用 data/llm.json 的 LLM 抽概念再渲染")
    cc.add_argument("--json", action="store_true", help="输出概念图谱原始 JSON（nodes/links）")
    cc.set_defaults(func=_concepts)

    ec = sub.add_parser("export", help="导出为 Obsidian markdown（每本书一个 .md）")
    ec.add_argument("--out", default="weread-export",
                    help="导出目录（默认 ./weread-export，可指向 Obsidian vault 子目录）")
    ec.set_defaults(func=_export)

    mc = sub.add_parser("ima", help="增量同步到 ima 知识库（防重复、限速、可续）")
    mc.add_argument("--kb", help="目标知识库名称（不传则列出可用知识库）")
    mc.add_argument("--list", action="store_true", help="列出可用的 ima 知识库")
    mc.set_defaults(func=_ima_sync)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
