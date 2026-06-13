#!/usr/bin/env python3
"""
lib/llm.py — optional LLM source for summaries / concepts.

供 web 后端「网页主动触发」和 agent 批量脚本共用（lib/ 两端共享）。
脚本本身不内置模型；按 data/llm.json 调用用户自配的 LLM，未配置则返回 None，
调用方降级（web 隐藏按钮 / agent 走 openclaw 自带 LLM）。

配置 data/llm.json（gitignore 下 data/ 已忽略）：
  {"endpoint": "...", "api_key": "...", "model": "...", "format": "openai"}

format（默认 openai）一种即覆盖绝大多数（OpenAI / DeepSeek / Kimi / 智谱 /
通义 / Ollama 都有 OpenAI 兼容端点，只改 endpoint+model）；anthropic / gemini
各一个小 adapter。全程 curl + json，不引 SDK。
"""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_config():
    p = ROOT / "data" / "llm.json"
    if not p.exists():
        return None
    try:
        cfg = json.loads(p.read_text())
    except Exception:
        return None
    if cfg.get("api_key") and cfg.get("endpoint") and cfg.get("model"):
        cfg.setdefault("format", "openai")
        return cfg
    return None


def llm_available() -> bool:
    return _load_config() is not None


def _post(url, headers, body):
    args = ["curl", "-s", "-X", "POST", url, "-H", "Content-Type: application/json"]
    for k, v in headers.items():
        args += ["-H", f"{k}: {v}"]
    args += ["-d", json.dumps(body, ensure_ascii=False)]
    r = subprocess.run(args, capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:
        raise RuntimeError(f"LLM 响应非法: {r.stdout[:200]}")


def chat(system: str, user: str, max_tokens: int = 1500):
    """统一对话入口。无配置返回 None。"""
    cfg = _load_config()
    if cfg is None:
        return None
    fmt = cfg["format"]

    if fmt == "anthropic":
        data = _post(cfg["endpoint"],
                     {"x-api-key": cfg["api_key"], "anthropic-version": "2023-06-01"},
                     {"model": cfg["model"], "max_tokens": max_tokens,
                      "system": system, "messages": [{"role": "user", "content": user}]})
        if "content" not in data:
            raise RuntimeError(f"anthropic 返回异常: {str(data)[:200]}")
        return data["content"][0]["text"]

    if fmt == "gemini":
        url = cfg["endpoint"]
        url += ("&" if "?" in url else "?") + f"key={cfg['api_key']}"
        data = _post(url, {},
                     {"contents": [{"parts": [{"text": system + "\n\n" + user}]}]})
        if "candidates" not in data:
            raise RuntimeError(f"gemini 返回异常: {str(data)[:200]}")
        return data["candidates"][0]["content"]["parts"][0]["text"]

    # openai 兼容（默认）
    data = _post(cfg["endpoint"],
                 {"Authorization": f"Bearer {cfg['api_key']}"},
                 {"model": cfg["model"],
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]})
    if "choices" not in data:
        raise RuntimeError(f"openai 兼容返回异常: {str(data)[:200]}")
    return data["choices"][0]["message"]["content"]


def _read_prompt(name: str) -> str:
    return (ROOT / "prompts" / name).read_text()


def summarize_book(payload: dict):
    """用 prompts/book_summary.md 合成读后总结。payload 同脚本输出的
    [AGENT_BOOK_SUMMARY_DATA] 结构。无 LLM 配置返回 None。"""
    if not llm_available():
        return None
    system = _read_prompt("book_summary.md")
    user = "下面是这本书的数据（JSON），请按上面的指令生成读后总结：\n\n" + \
           json.dumps(payload, ensure_ascii=False)
    return chat(system, user, max_tokens=900)  # 硬顶 ~700 字，配合 prompt 的句数约束


def _parse_json_array(raw):
    import re
    if not raw:
        return None
    s = raw.strip()
    s = re.sub(r'^```(?:json)?\s*', '', s)
    s = re.sub(r'\s*```$', '', s)
    m = re.search(r'\[.*\]', s, re.S)
    if m:
        s = m.group(0)
    try:
        return json.loads(s)
    except Exception:
        return None


def extract_concepts(title, highlights, existing_tags, max_highlights=50):
    """抽取一本书的概念。highlights: [{highlight_id, content}]。existing_tags:
    已有概念名列表（喂给模型优先复用，保证跨书一致）。
    返回 [{"name": 概念, "highlight_ids": [...]}] 或 None（无 LLM）。"""
    if not llm_available():
        return None
    hl = highlights[:max_highlights]
    if not hl:
        return []
    system = _read_prompt("concept_extract.md")
    lines = "\n".join(f"{i+1}. {h['content'][:120]}" for i, h in enumerate(hl))
    tags = "、".join(existing_tags[:80]) if existing_tags else "（暂无，可自由命名）"
    user = f"书名：{title}\n\n已有概念（优先复用）：{tags}\n\n划线：\n{lines}"
    parsed = _parse_json_array(chat(system, user, max_tokens=700))
    if not parsed:
        return []
    out = []
    for c in parsed:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        idxs = c.get("highlights") or []
        hids = [hl[i - 1]["highlight_id"] for i in idxs
                if isinstance(i, int) and 1 <= i <= len(hl)]
        out.append({"name": name, "highlight_ids": hids})
    return out
