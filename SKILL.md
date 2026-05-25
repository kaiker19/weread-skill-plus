---
name: wechat-reading-custom
description: 微信读书扩展技能 — 每日阅读回顾 + 书籍概览 + 读完统计 + 笔记导出 + 主题回顾 + 阅读可视化
version: 1.1.0
---

# 微信读书扩展技能

基于微信读书官方 weread-skills 接口（本 skill 目录下 `~/.agents/skills/weread-skills/`），实现多个扩展能力。

**依赖接口：**
- `/shelf/sync` — 书架
- `/book/getprogress` — 进度
- `/book/bookmarklist` — 划线内容
- `/book/bestbookmarks` — 热门划线
- `/book/chapterinfo` — 章节结构
- `/book/info` — 书籍信息
- `/user/notebooks` — 有笔记的书（分页遍历）
- `/readdata/detail` — 阅读统计（weekly/monthly/annually/overall）
- `/store/search` — 书城搜索

---

## 能力一：每日阅读回顾

**功能**：UTC+8 当天读了什么书、进度变化、新增划线内容

**脚本**：`daily_review/daily_review.py`

**触发**：cron `weread-daily-review` 每日 23:00 Asia/Shanghai → agent 总结 → 推 QQ

**独立测试**：
```bash
python3 ~/.openclaw/workspace/skills/wechat-reading-custom/daily_review/daily_review.py
```

**输出**：
- 今日在读书籍列表
- 每本今日新增划线内容
- 进度增量（今日 vs 昨日）

---

## 能力二：书籍概览 book_overview

**功能**：书名 → 书籍信息 + 章节结构 + 各章热门划线（agent 基于输出总结）

**脚本**：`qa/weread_qa.py`

**使用**：
```bash
# 直接运行
python3 ~/.openclaw/workspace/skills/wechat-reading-custom/qa/weread_qa.py "书名" [bookId]

# 通过 agent 调用（推荐）
# agent 读取脚本输出的 [AGENT_QA_JSON] 做总结
```

**注意**：`/store/search` 对某些书返回 0 条结果，bookId 优先从书架获取

---

## 能力三：读完统计

**功能**：今年 vs 历史读完本数统计、书单

**脚本**：`completion_stats/completion_stats.py`

**使用**：
```bash
python3 ~/.openclaw/workspace/skills/wechat-reading-custom/completion_stats/completion_stats.py
```

**接口依赖**：`/shelf/sync`（筛 finishReading==1） + `/readdata/detail`

---

## 能力四：笔记导出

**功能**：将个人划线笔记导出，支持关键词筛选；数据保存到 JSON 文件

**脚本**：`notes_export/notes_export.py`

**使用**：
```bash
# 导出全部笔记
python3 ~/.openclaw/workspace/skills/wechat-reading-custom/notes_export/notes_export.py

# 关键词筛选（如：自由、消费、哲学）
python3 ~/.openclaw/workspace/skills/wechat-reading-custom/notes_export/notes_export.py "关键词"
```

**接口依赖**：`/user/notebooks`（分页遍历） + `/book/bookmarklist`（逐本拉划线）

**注意**：有笔记的书共 43 本，共 9822 条划线，每次运行约需 50 次 API 调用，间隔 0.3s，总耗时约 15-20 秒

**输出文件**：`~/.openclaw/workspace/data/weread_notes_export.json`

---

## 能力五：主题回顾（增强版）

**功能**：跨书按关键词聚合所有划线；不传关键词时自动聚类所有划线，提炼主题方向

**脚本**：`theme_review/theme_review.py`

**使用**：
```bash
# 自动聚类模式（无关键词）— 从所有划线中提炼主题方向
python3 ~/.openclaw/workspace/skills/wechat-reading-custom/theme_review/theme_review.py

# 关键词搜索模式
python3 ~/.openclaw/workspace/skills/wechat-reading-custom/theme_review/theme_review.py "自由"
```

**自动聚类流程**：
1. 调用 `/user/notebooks` 获取所有有笔记的书（分页遍历）
2. 对每本书调用 `/book/bookmarklist` 获取所有划线
3. jieba 分词 + TF-IDF 向量化 + KMeans 聚类（sklearn）
4. 输出主题方向列表，每主题含关键词 + 代表性划线样本
5. 输出 JSON 结构供 agent 二次总结

**接口依赖**：`/user/notebooks`（分页遍历） + `/book/bookmarklist`（逐本查划线）

**输出**：
- 主要主题方向列表（每方向含 top 关键词 + 3-5 条代表性划线）
- `[AGENT_THEME_JSON]` 块：JSON 格式供 agent 总结

**依赖**：Python `jieba`、`sklearn`（已预装）

---

## 能力六：阅读统计可视化（增强版）

**功能**：周/月/年/历史阅读时长、偏好分类、读书排行，生成 HTML 图表；含季度趋势对比（Q1 vs Q2 百分比变化）

**脚本**：`reading_stats_viz/reading_stats_viz.py`

**使用**：
```bash
python3 ~/.openclaw/workspace/skills/wechat-reading-custom/reading_stats_viz/reading_stats_viz.py
```

**输出**：`~/.openclaw/workspace/data/weread_reading_stats.html`（浏览器打开查看）

**季度对比**：在「今年各季度阅读时长」卡片中显示 Q1 vs Q2 变化百分比（绿色↑/红色↓）

**接口依赖**：`/readdata/detail`（mode: weekly/monthly/annually/overall）

---

## 文件结构

```
wechat-reading-custom/
├── SKILL.md
├── daily_review/
│   └── daily_review.py      # 每日阅读回顾
├── qa/
│   └── weread_qa.py         # 书籍概览 book_overview
├── completion_stats/
│   └── completion_stats.py  # 读完统计
├── notes_export/
│   └── notes_export.py      # 笔记导出
├── theme_review/
│   └── theme_review.py      # 主题回顾（增强：自动聚类）
└── reading_stats_viz/
    └── reading_stats_viz.py  # 阅读可视化（增强：Q1 vs Q2 对比）
```

---

## 依赖

- Python 3.10+
- `curl` 命令行工具
- `jieba`、`sklearn`（主题聚类用，已预装）
- `~/.openclaw/openclaw.json` 中已配置 `skills.entries.weread-skills.env.WEREAD_API_KEY`
- 时区：统一使用 `Asia/Shanghai` (UTC+8)

---

## 更新日志

- 2026-05-24 v1.1.0：
  - **theme_review**：新增无关键词自动聚类模式，jieba + TF-IDF + KMeans 聚类提炼主题方向
  - **reading_stats_viz**：新增 Q1 vs Q2 季度对比百分比显示
- 2026-05-24 v1.0.0：初始版本，支持每日回顾 + 书籍概览 + 读完统计 + 笔记导出 + 主题回顾 + 阅读可视化