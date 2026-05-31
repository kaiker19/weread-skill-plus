# weread-skill-plus

微信读书扩展 skill — 在官方 [weread-skills](https://github.com/Tencent/WeChatReading) 基础上增加：

- **每日阅读回顾**：当天划线 + 批注，附跨书呼应（jieba + SQLite LIKE）
- **读后总结**：完读即触发，对比大众热门划线，发现自己的"盲点"
- **本地语义知识库**：SQLite 增量同步全部阅读数据，供历史检索

---

## 前置：获取微信读书 API Key

前往 [https://weread.qq.com/r/weread-skills](https://weread.qq.com/r/weread-skills) 获取你的 `WEREAD_API_KEY`，并在 openclaw 中完成配置。

---

## 安装

```bash
npx skills install kaiker19/weread-skill-plus
```

安装后 skill 位于 `~/.openclaw/workspace/skills/wechat-reading-custom/`。

**依赖**：Python 3.9+、`curl`、`jieba`（openclaw 环境已预装）

---

## 快速开始

```bash
# 1. 首次全量同步数据到本地 SQLite
python3 lib/sync.py --force

# 2. 验证数据库
python3 lib/knowledge_base.py

# 3. 手动触发每日回顾（正常由 cron 触发）
python3 daily_review/daily_review.py

# 4. 手动触发读后总结检测
python3 book_summary/book_summary.py
```

---

## 文件结构

```
weread-skill-plus/
├── SKILL.md                 # Agent 能力说明（主要读者：Agent LLM）
├── ROADMAP.md               # 产品规划
├── lib/
│   ├── knowledge_base.py    # SQLite schema + CRUD + keyword search
│   └── sync.py              # 增量数据同步层
├── daily_review/
│   └── daily_review.py      # 每日阅读回顾
├── book_summary/
│   └── book_summary.py      # 读后总结
├── notes_export/
│   └── notes_export.py      # 笔记导出（关键词筛选）
├── prompts/
│   ├── daily_summary.md     # 每日总结 prompt
│   ├── book_summary.md      # 读后总结 prompt
│   └── samples.example.md   # 风格样本模板（复制为 samples.md 后填入个人内容）
├── .agents/skills/
│   └── weread-skills/       # 官方 WeChat Reading skill（随本 repo 打包）
└── data/                    # 本地 SQLite（gitignored，运行后自动生成）
    └── knowledge.db
```

---

## 执行模型

脚本不调用 LLM。链路：脚本输出 JSON → Agent 读取 → Agent LLM 用 `prompts/*.md` 合成 → 推送。

---

## 更新日志

- **v2.0.0** (2026-05-31)：SQLite 知识库 + 每日回顾重构 + 读后总结新增
- **v1.1.0** (2026-05-24)：theme_review 自动聚类 + reading_stats_viz 季度对比
- **v1.0.0** (2026-05-24)：初始版本
