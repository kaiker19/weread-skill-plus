# 微信读书扩展技能 · weread-skill-plus

在微信读书官方 [weread-skills](https://weread.qq.com/r/weread-skills) 接口之上，叠加三项**主动洞察能力**，并维护一个本地 SQLite 知识库做增量沉淀。官方 skill 负责"你问我答"，这个扩展负责"不问也说"——每天主动告诉你今天读了什么、想了什么，读完一本书帮你收尾，并把今天的划线和几个月前另一本书里的批注连起来。

> 这是一个 [Claude Code / OpenClaw](https://claude.com/claude-code) Agent Skill。脚本本身不调用 LLM，由 Agent 读取脚本输出的数据，再用内置的 prompt 合成总结。

---

## 三项能力

| 能力 | 做什么 | 触发 |
|------|--------|------|
| **每日阅读回顾** | 当天新增划线 + 批注 → 提炼"今天在读什么、在想什么"，并附 2-3 条真实的跨书呼应 | cron 每日 23:00 |
| **读后总结** | 检测到一本书读完（`finishTime` 出现）→ 基于全书划线/批注，对比大众热门划线找盲点，生成"这本书给了我什么" | 每日检测，事件触发 |
| **笔记导出** | 导出个人划线，支持关键词筛选 | 手动 |

每日回顾的输出按书籍类型分叉：论说/历史/实用类用加粗关键词锚点结构，文学类保持纯散文保留氛围。prompt 内置了一套"反 AI 腔"规则，让总结读起来像一个读了书的人在跟你分享，而不是助手在交报告。

---

## 安装

### 通过 npx（推荐）

```bash
npx skills install kaiker19/weread-skill-plus
```

### 配置 API Key

前往 [weread-skills 页面](https://weread.qq.com/r/weread-skills) 获取 `WEREAD_API_KEY`，写入 skill 目录下的 `data/api_key` 文件（一行，仅 key 值）：

```bash
mkdir -p data
echo "wrk-xxxxxxxx" > data/api_key
```

### 首次全量同步

```bash
python3 lib/sync.py --force
```

> 首次同步按书架规模约需 3-10 分钟（每本书间隔 0.3s 限速）。完成后每日增量同步仅需数秒。

---

## 工作原理

```
cron 触发
  → Python 脚本（拉数据 + 入库 + 检索）
  → stdout 输出 [AGENT_*_DATA] JSON
  → Agent 读取 JSON
  → Agent 用对应 prompts/*.md 合成总结
  → 推送给用户
```

脚本不需要额外的 LLM API Key——合成由 Agent 自身的模型完成。本地知识库是一个 SQLite 文件（`data/knowledge.db`，不提交 git），增量写入划线、批注、完读状态等，供跨书检索使用。

跨书呼应不依赖 embedding：用 jieba 分词提关键词，SQL `LIKE` 预筛历史候选，再由 Agent 从候选中精选真正成立的 2-3 条连接。零额外依赖。

---

## 依赖

- Python 3.9+
- `curl`
- `jieba`（跨书呼应分词）

---

## 文档

- [SKILL.md](SKILL.md) — 给 Agent 读的技能定义（接口、数据结构、执行模型）
- [ROADMAP.md](ROADMAP.md) — 迭代方向、官方接口全景、Web 端规划

---

## 与官方 weread-skills 的关系

官方 skill（[.agents/skills/weread-skills/](.agents/skills/weread-skills/)）提供搜索、书架、笔记、书评、阅读统计等查询能力。本项目复用它的接口网关，专注做官方没有的"主动总结 + 历史关联 + 本地沉淀"。两者互补，不冲突。
