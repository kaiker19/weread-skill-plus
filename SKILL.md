---
name: wechat-reading-custom
description: 微信读书扩展技能 — 每日阅读回顾（跨书呼应）+ 读后总结 + 笔记导出 + 语义知识库
version: 2.0.0
---

# 微信读书扩展技能

基于微信读书官方 weread-skills 接口，实现三项核心能力，并维护一个本地 SQLite 语义知识库供增量检索。

**依赖接口：**
- `/shelf/sync` — 书架（含完读状态）
- `/book/bookmarklist` — 个人划线
- `/review/list/mine` — 个人批注/想法
- `/book/bestbookmarks` — 大众热门划线
- `/book/similar` — 相似书推荐
- `/user/notebooks` — 有笔记的书（笔记导出用）

---

## 能力一：每日阅读回顾

**功能**：当天新增划线 + 批注，附跨书呼应（jieba 分词 → 历史 LIKE 检索）

**脚本**：`daily_review/daily_review.py`

**触发**：cron `weread-daily-review` 每日 23:00 Asia/Shanghai

**独立测试**：
```bash
python3 ~/.openclaw/workspace/skills/wechat-reading-custom/daily_review/daily_review.py
```

**输出**：无新内容时静默；有内容时输出 `[AGENT_DAILY_DATA]` JSON，agent LLM 使用 `prompts/daily_summary.md` 合成。

**JSON 结构**：
```json
{
  "date": "2026-05-31",
  "books_active": [{"title": "...", "author": "..."}],
  "new_highlights": [{"book_title": "...", "content": "...", "chapter_title": "..."}],
  "new_reviews":    [{"book_title": "...", "content": "..."}],
  "cross_book_echoes": [{"book_title": "...", "content": "...", "matched_kw": "...", "days_ago": 42}],
  "prompt_ref": "prompts/daily_summary.md"
}
```

---

## 能力二：读后总结

**功能**：检测新完读书籍（`finishTime` 出现），生成"这本书给了我什么"

**脚本**：`book_summary/book_summary.py`

**触发**：每日与 daily_review 同时运行；`get_newly_finished_books()` 检测未总结的完读书

**独立测试**：
```bash
python3 ~/.openclaw/workspace/skills/wechat-reading-custom/book_summary/book_summary.py
```

**输出**：无新完读书时静默；有则输出 `[AGENT_BOOK_SUMMARY_DATA]` JSON，agent LLM 使用 `prompts/book_summary.md` 合成。

**JSON 结构**：
```json
{
  "book": {"title": "...", "author": "...", "category": "...", "finish_date": "..."},
  "my_highlights": [{"content": "...", "chapter_title": "..."}],
  "my_reviews":    [{"content": "..."}],
  "popular_highlights":   [{"content": "...", "total_count": 3200}],
  "popular_not_in_mine":  [{"content": "...", "total_count": 2100}],
  "similar_books": [{"title": "...", "author": "..."}],
  "prompt_ref": "prompts/book_summary.md"
}
```

---

## 能力三：笔记导出

**功能**：导出个人划线，支持关键词筛选

**脚本**：`notes_export/notes_export.py`

**使用**：
```bash
python3 ~/.openclaw/workspace/skills/wechat-reading-custom/notes_export/notes_export.py
python3 ~/.openclaw/workspace/skills/wechat-reading-custom/notes_export/notes_export.py "关键词"
```

**输出文件**：`~/.openclaw/workspace/data/weread_notes_export.json`

---

## Agent 执行模型

脚本本身**不调用 LLM**。完整链路：

```
cron 触发
  → Python 脚本（拉数据 + 入库 + 检索）
  → stdout 输出 [AGENT_*_DATA] JSON
  → Agent 读取 JSON
  → Agent LLM 加载对应 prompts/*.md 作为合成指令
  → 输出总结推送给用户
```

`prompt_ref` 字段告诉 Agent 使用哪个 prompt 文件合成。Agent 的 LLM 能力即为 openclaw 自身，无需额外 API Key。

---

## 底座：本地语义知识库

**位置**：`data/knowledge.db`（SQLite，不提交 git）

**表结构**：`books` / `highlights` / `reviews` / `concepts` / `summaries` / `sync_state`

**同步模块**：`lib/sync.py`，增量拉取，每本书间隔 0.3s 限速

```bash
python3 ~/.openclaw/workspace/skills/wechat-reading-custom/lib/sync.py
python3 ~/.openclaw/workspace/skills/wechat-reading-custom/lib/sync.py --force
```

**环境变量**：
- `WEREAD_API_KEY` — API Key（优先级：env > .env > openclaw.json）
- `WEREAD_KB_PATH` — 自定义 DB 路径（默认 `data/knowledge.db`）

---

## 依赖

- Python 3.9+
- `curl` 命令行工具
- `jieba`（跨书呼应分词，已预装）
- `WEREAD_API_KEY` 已在 openclaw 中配置

---

## 首次安装

1. 前往 [https://weread.qq.com/r/weread-skills](https://weread.qq.com/r/weread-skills) 获取 `WEREAD_API_KEY` 并完成 openclaw 配置
2. 全量同步阅读数据到本地知识库：

```bash
python3 ~/.openclaw/workspace/skills/wechat-reading-custom/lib/sync.py --force
```