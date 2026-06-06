---
name: wechat-reading-custom
description: 微信读书扩展技能 — 每日阅读回顾（跨书呼应 + 空日历史回声）+ 周回顾 + 读后总结 + 笔记导出 + 语义知识库
version: 2.1.0
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

**输出**：有新内容时输出 `[AGENT_DAILY_DATA]` JSON；无新内容时输出含 `historical_echo` 字段的 JSON（随机取一条历史批注/划线，优先批注）；两者均无时静默。

跨书呼应评分：批注（review）初始分 2，划线（highlight）初始分 1，优先呈现用户自己的思考。

**JSON 结构**：
```json
{
  "date": "2026-05-31",
  "books_active": [{"title": "...", "author": "..."}],
  "new_highlights": [{"book_title": "...", "content": "...", "chapter_title": "..."}],
  "new_reviews":    [{"book_title": "...", "content": "..."}],
  "cross_book_echoes": [{"book_title": "...", "content": "...", "matched_kw": "...", "days_ago": 42}],
  "historical_echo": {"content": "...", "book_title": "...", "days_ago": 119, "source_type": "review"},
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

## 能力四：周回顾

**功能**：汇总过去 7 天的划线 + 批注，提炼跨日阅读主线，附跨周历史回声

**脚本**：`weekly_review/weekly_review.py`

**触发**：cron `weread-weekly-review` 每周六 21:00 Asia/Shanghai

**独立测试**：
```bash
python3 ~/.openclaw/workspace/skills/wechat-reading-custom/weekly_review/weekly_review.py
```

**输出**：本周无新内容时静默；有内容时输出 `[AGENT_WEEKLY_DATA]` JSON，agent LLM 使用 `prompts/weekly_summary.md` 合成。

**JSON 结构**：
```json
{
  "week_range": "2026-05-30 ~ 2026-06-06",
  "stats": {"books": 2, "highlights": 45, "reviews": 3},
  "books": [{"book_id": "...", "book_title": "...", "author": "...", "highlights": [...], "reviews": [...]}],
  "cross_week_echoes": [{"book_title": "...", "content": "...", "days_ago": 120, "similarity": 0.81}],
  "echo_mode": "semantic",
  "prompt_ref": "prompts/weekly_summary.md"
}
```

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

> **耗时提醒**：首次全量同步（3-10 分钟）或较慢的数据拉取前，Agent 先用一句话告知用户"正在同步阅读数据，请稍候"，不要展开解释。增量同步仅数秒，无需提示。

---

## 底座：本地语义知识库

**位置**：`data/knowledge.db`（SQLite，不提交 git）

**表结构**：`books` / `highlights` / `reviews` / `concepts` / `summaries` / `sync_state`

**同步模块**：`lib/sync.py`，增量拉取，每本书间隔 0.3s 限速

```bash
python3 ~/.openclaw/workspace/skills/wechat-reading-custom/lib/sync.py
python3 ~/.openclaw/workspace/skills/wechat-reading-custom/lib/sync.py --force
```

**API Key 读取优先级**：`data/api_key` 文件 > `.env` 文件

**环境变量**：
- `WEREAD_KB_PATH` — 自定义 DB 路径（默认 `data/knowledge.db`）

---

## 依赖

- Python 3.9+
- `curl` 命令行工具
- `jieba`（跨书呼应分词，需 `pip install jieba`）—— 未安装时自动降级为 n-gram 兜底分词，回声仍可用但质量下降，并在 stderr 给出提示

**可选（语义向量索引，见下）**：
- `fastembed` + `numpy`（本地 embedding，`pip install fastembed`）—— 或改用 embedding API，二选一即可

---

## 首次安装

1. 前往 [https://weread.qq.com/r/weread-skills](https://weread.qq.com/r/weread-skills) 获取 `WEREAD_API_KEY`
2. 将 key 写入 skill 目录下的 `data/api_key` 文件（一行，仅 key 值）：

```bash
mkdir -p ~/.openclaw/workspace/skills/wechat-reading-custom/data
echo "your_key_here" > ~/.openclaw/workspace/skills/wechat-reading-custom/data/api_key
```

3. 全量同步阅读数据到本地知识库：

```bash
python3 ~/.openclaw/workspace/skills/wechat-reading-custom/lib/sync.py --force
```

> **注意**：首次全量同步按书架规模约需 3-10 分钟（每本书间隔 0.3s 限速）。完成后每日增量同步仅需数秒。

> **cold start 保护**：`book_summary` 首次运行仅处理最近 30 天内完读的书籍，避免历史积压书单一次性全部触发。

---

## 更新

当用户想更新本技能，或网关回包出现 `upgrade_info` 字段（提示有新版本）时，引导用户执行：

```bash
npx skills update                         # 更新全部已装技能（别名 upgrade）
npx skills update wechat-reading-custom   # 只更新本技能（按 SKILL.md 的 name，非仓库名 weread-skill-plus）
```

更新只替换技能代码，不动 `data/`（知识库与 API Key 都在此，不受影响）。更新后无需重新全量同步。

---

## 可选增强：语义向量索引

把跨书呼应的召回层从 jieba/LIKE（字面匹配）升级为 **embedding + 余弦相似**，让同义/近义也能连上（"思维 ↔ 思考 ↔ 认知"）。**完全可选**：没有嵌入源时 `daily_review` 自动回退 jieba，技能照常工作。

**两种嵌入源（二选一，自动解析、逐级降级）：**

1. **本地**（推荐，零 key、隐私不出本机）：`pip install fastembed`，首次自动下载中文模型（`bge-small-zh-v1.5`，~95MB）。
2. **API**（质量更好，需自备 key）：在 `data/embedding.json` 写 OpenAI 兼容配置：
   ```json
   {"endpoint": "https://api.openai.com/v1/embeddings", "api_key": "sk-...", "model": "text-embedding-3-small"}
   ```
   智谱 / 通义 / Jina / 本地 Ollama 等 OpenAI 兼容端点都可填。全量嵌入约数千条短文本，成本约 1-2 美分。

**首次回填（独立可选步骤，不拖慢基础安装）：**

```bash
python3 lib/embedding.py --backfill   # 为历史划线/批注生成向量
```

> **耗时提醒**：首次回填 = 模型下载（本地 ~95MB）+ 逐条嵌入。参考量级：~1 万条本地约 2 分钟。**可中断续跑**（只处理缺向量的记录）。不跑这步也能用，只是吃 jieba 兜底。Agent 在执行回填前应先一句话告知用户耗时。

**日常无需手动**：`daily_review` 每天会顺带嵌入当天新增的几条，索引自动增长。

**本地自检：**

```bash
python3 lib/embedding.py --status            # 已嵌入 / 待回填
python3 lib/embedding.py --test "强势思维"   # 看语义最近的划线，肉眼验证
```

向量存在 `data/knowledge.db` 的 `embeddings` 表（float32 BLOB），检索用 numpy 暴力余弦——本地这个数据量足够快，无需 sqlite-vec 之类扩展（系统 python 多半也加载不了扩展）。