# 微信读书扩展技能 · weread-skill-plus

在微信读书官方 [weread-skills](https://weread.qq.com/r/weread-skills) 接口之上，叠加三项**主动洞察能力**，并维护一个本地 SQLite 知识库做增量沉淀。官方 skill 负责"你问我答"，这个扩展负责"不问也说"——每天主动告诉你今天读了什么、想了什么，读完一本书帮你收尾，并把今天的划线和几个月前另一本书里的批注连起来。

> 这是一个 [Claude Code / OpenClaw](https://claude.com/claude-code) Agent Skill。脚本本身不调用 LLM，由 Agent 读取脚本输出的数据，再用内置的 prompt 合成总结。

---

## 演示

> 2 分钟：一句话召回散落各书的思考 · 跨书呼应 · 概念地图

<!-- 录屏放这里：开个 issue / PR，把 weread-skill-demo.mp4 拖进评论框上传，
     再把生成的 https://github.com/user-attachments/assets/... 链接单独贴一行到本注释下方
     （GitHub 网页会自动渲染成播放器；文件存 CDN、不进仓库）。 -->

---

## 三项能力

| 能力 | 做什么 | 触发 |
|------|--------|------|
| **每日阅读回顾** | 当天新增划线 + 批注 → 提炼"今天在读什么、在想什么"，附跨书呼应；当天无新内容时随机浮现一条历史批注/划线 | cron 每日 23:00 |
| **周回顾** | 汇总过去 7 天的划线/批注，提炼跨日阅读主线，并附跨周历史回声 | cron 每周六 21:00 |
| **读后总结** | 检测到一本书读完（`finishTime` 出现）→ 基于全书划线/批注，对比大众热门划线找盲点，生成"这本书给了我什么" | 每日检测，事件触发 |

输出按书籍类型分叉：论说/历史/实用类用加粗关键词锚点结构，文学类保持纯散文。prompt 内置"反 AI 腔"规则，读起来像一个读了书的人在跟朋友分享，而不是助手在交报告。

---

## 安装

这个项目有**两种用法**，按你的身份二选一：

### 🖱 普通用户 —— 下载本地应用，双击即用（零命令行）

到 [Releases](https://github.com/kaiker19/weread-skill-plus/releases/latest) 下载对应平台：

- **macOS**：`.dmg` → 拖入「应用程序」→ 打开
- **Windows**：`.zip` → 解压 → 双击 `WeReadDashboard.exe`

首次打开有向导带你走完：填 WeRead API Key → 全量同步 → 建语义索引（中文模型已内置，无需联网下载）。之后就是书架 / 探索 / 写作台 / 洞见 / 概念图谱的本地图形界面，数据全留本机。

> macOS 首次打开若提示「无法验证开发者」：系统设置 → 隐私与安全性 → 下方「仍要打开」。

### 🤖 Agent 用户 —— 作为 Claude Code / OpenClaw 技能

```bash
npx skills add kaiker19/weread-skill-plus -y      # -y 跳过交互式 agent 选择（无 TTY / 让 agent 自动装时必须）
```

> 不加 `-y` 会进入交互式列表让你选装到哪个 agent；在真终端里手动装可以这样选，但在 agent 自动执行或无 TTY 环境下会卡住等输入。

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

### 更新

```bash
npx skills update                         # 更新全部已装技能（别名 upgrade）
npx skills update wechat-reading-custom   # 只更新本技能（按技能名，非仓库名）
```

更新不会动 `data/`（你的知识库和 API Key 都在这里，不受影响）。

### 可选：语义向量索引

跨书呼应默认用 jieba + `LIKE` 字面匹配。装上 embedding 后，召回升级为语义相似——"思维 ↔ 思考 ↔ 认知"这种同义也能连上。**可选，不装也能用**（自动回退 jieba）。

```bash
pip install fastembed                        # 本地嵌入，首次自动下载中文模型 ~95MB
python3 lib/embedding.py --backfill          # 为历史划线生成向量（~1 万条本地约 2 分钟，可中断续跑）
python3 lib/embedding.py --test "强势思维"   # 验证语义检索
```

或改用 embedding API（OpenAI 兼容）：在 `data/embedding.json` 填 `{"endpoint","api_key","model"}`，智谱/通义/Jina/Ollama 等都支持。细节见 [SKILL.md](SKILL.md) 的「可选增强：语义向量索引」。

> 首次回填要等模型下载 + 逐条嵌入，是独立步骤，不影响基础安装。向量留在本机（`data/knowledge.db`），不外传。

---

## 依赖

> 下载的本地应用已自带全部依赖，下面只针对 **Agent / CLI 用法**。

- Python 3.9+（HTTP 走内置 `urllib`，不再依赖系统 `curl`）
- `certifi`（HTTPS 根证书）—— macOS 上的**非系统 Python**（Homebrew/python.org/pyenv）连微信读书 API 必需，否则 `CERTIFICATE_VERIFY_FAILED`；`pip install certifi` 即可。系统 `/usr/bin/python3`、Windows、Linux 自带证书，可免
- `jieba`（跨书呼应分词，`pip install jieba`；缺失时自动降级为 n-gram 兜底，质量下降）
- 可选：`fastembed` + `numpy`（语义向量索引，见上方「可选：语义向量索引」；不装则跨书呼应走 jieba）

---

## 文档

- [SKILL.md](SKILL.md) — 给 Agent 读的技能定义（接口、数据结构、执行模型）
- [references/web.md](references/web.md) — 本地 Web 面板（书架 / 探索 / 写作台 / 洞见 / 概念图谱）启动与各页用法
- **CLI**：`python3 cli/weread.py recall "<想法>"`（语义找回划线）、`weread concepts`（概念地图）—— 零 LLM，可被编辑器 / 启动器 shell-out 调用

---

## 与官方 weread-skills 的关系

官方 skill（[.agents/skills/weread-skills/](.agents/skills/weread-skills/)）提供搜索、书架、笔记、书评、阅读统计等查询能力。本项目复用它的接口网关，专注做官方没有的"主动总结 + 历史关联 + 本地沉淀"。两者互补，不冲突。
