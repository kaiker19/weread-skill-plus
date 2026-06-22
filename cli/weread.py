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
import json
import argparse
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))


MIN_SIM = 0.55  # 召回相关度下限：宁缺毋滥（伪相关多 <0.55，真相关多 ≥0.6）


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

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
