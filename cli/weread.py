#!/usr/bin/env python3
"""weread CLI —— 把本地划线库的语义召回能力以最薄的方式提供出去。

    weread recall "<想法/概念>"   找回相关划线 + 相关概念，markdown 到 stdout
    weread recall "<...>" --json   输出原始 JSON，供插件/程序消费

可 `| pbcopy`，或被 vim / Alfred / Raycast / Obsidian 等 shell-out 调用。
检索复用 lib/embedding.py，与 web、skill 同一套相似度逻辑，无 LLM 依赖。
"""
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))


MIN_SIM = 0.55  # 相关度下限：低于此视为不相关，宁缺毋滥。
                # 0.55 实测能滤掉"量子纠缠→异化""乱码→链接"这类伪相关，
                # 又基本保留真相关（真相关多在 0.6+，弱真相关 0.55~0.6）。


def _recall(args):
    from embedding import explore_search
    r = explore_search(args.query, limit=args.limit)
    hl = [h for h in r.get("highlights", []) if (h.get("similarity") or 0) >= MIN_SIM]
    r["highlights"] = hl
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return
    if not hl:
        print(f"没有与「{args.query}」相关的划线。")
        return
    out = [f"## 与「{args.query}」相关的思考 · {len(hl)} 条", ""]
    for h in hl:
        kind = "批注" if h.get("source_type") == "review" else "划线"
        pct = round((h.get("similarity") or 0) * 100)
        text = " ".join((h.get("content") or "").split())   # 折叠换行，保持引用块整洁
        if len(text) > 200:                                 # 超长批注/划线截断，全文走 --json
            text = text[:200] + "…"
        out.append(f"> {text}")
        out.append(f"  —《{h.get('book_title')}》· {kind} · {pct}%")
        out.append("")
    if r.get("concepts"):
        out.append("相关概念  " + " · ".join(r["concepts"]))
    print("\n".join(out))


def main():
    p = argparse.ArgumentParser(prog="weread", description="本地划线库的语义召回")
    sub = p.add_subparsers(dest="cmd", required=True)
    rc = sub.add_parser("recall", help="按想法/概念找回相关划线与概念")
    rc.add_argument("query", help="一个想法、概念或一段话")
    rc.add_argument("-n", "--limit", type=int, default=8, help="返回条数（默认 8）")
    rc.add_argument("--json", action="store_true", help="输出原始 JSON（供插件/程序消费）")
    rc.set_defaults(func=_recall)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
