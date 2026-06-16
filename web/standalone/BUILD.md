# 打包说明（纯本地版）

> 开发期隔离文档，整体未完成前不进 git。

把 `launcher.py` + FastAPI + 前端 dist 打成**双击即用的单应用**,用户零安装。

## 文件

- `launcher.py` —— 统一入口（用户双击 / agent `python3` 都跑它）。✅ 已验收
- `setup_api.py` —— 首启向导后端（填 key + 全量同步进度）。✅ 已验收
- `weread-dashboard.spec` —— PyInstaller 规格（onedir）。⚠️ 待一次构建验证
- `build_macos.sh` —— Mac 本地：前端 build → PyInstaller → 冒烟 → `.dmg`。
- `release.yml.draft` —— 三端 CI 草案（定稿后移到 `.github/workflows/`）。

## 本地构建（macOS）

```bash
bash web/standalone/build_macos.sh
# 产物 dist/WeReadDashboard.dmg；脚本内含「启动二进制 + 探活」冒烟
```

## 构建验证结论（macOS，已实测 PyInstaller 6.21 / arm64）

✅ **打通**：`.app` 双击级产物可启动 → SPA 首页返回 HTML、`/assets/*.js,css` 200、
`/api/stats` 与向导端点 `/api/settings/apikey`、`/api/sync/full/status` 均 200;frozen 时
正确使用 `~/.weread-skill-plus/knowledge.db`（全新空库,不碰项目数据）。
**体积**：`.app` 120MB / `.dmg` 63MB（模型未打进,故可控）。

- ~~① dist 路径冻结后错位~~ → **实测非问题**：onedir 下 `server.__file__` 落到 `_internal/`,
  dist 正好在 `_internal/frontend/dist`,自然对齐。无需改 server.py。
- ~~③ onnxruntime/fastembed collect_all 完整性~~ → **实测通过**,且构建很快（~18s）。

## ✅ 数据路径统一（已修 + 已验证）

原问题:`api_key` / `llm.json` / `embedding.json` 各自用 `__file__` 推项目根 `data/`,冻结后会落进
只读 bundle、且向导写与 sync 读未必一致 → 填了 key 读不到。

**修法（已落地）**:在 `knowledge_base.py` 加单一来源 `data_dir()`——
`WEREAD_DATA_DIR` 环境变量优先（launcher 冻结时设为 `~/.weread-skill-plus/`,`Path.home()` 跨 Mac/Win），
否则项目根 `data/`。所有消费方改用它:
- `lib/sync.py`（WeRead api_key）、`lib/embedding.py`（embedding.json）、
  `web/server.py` + `web/llm.py`（llm.json）、`get_db_path()`（db）、`setup_api.py`（向导写 key）。

**验证**:
- 普通态 `data_dir()` = 项目 `data/`,WeRead key / llm.json 照常读到,**行为与旧版一致**（回归通过）。
- 冻结态 `.app` 实测:向导 POST 真实 key → 写入 `~/.weread-skill-plus/api_key` 并过 WeRead 校验 →
  `configured:true`;`sync._load_api_key()` 从同一路径读到 → **写读同源,bug 消除**。
- ⚠️ Windows 用 `Path.home()` 代码上跨平台,但**未在 Windows 实测**,需 CI / 手工补测。

> 涉及的 tracked 文件改动（knowledge_base/sync/embedding/server/llm）向后兼容,
> 但按开发期约定**先不提交**,定稿时随 standalone 一起提交。

## ✅ 语义索引在冻结版建不出来（已修，关键坑）

**症状**：.app 同步后数据齐全但 `embeddings=0`，洞见空。
**根因**：spec 的 `excludes` 里排除了 `PIL` 瘦身——但 **fastembed 0.7.4 在 `__init__` 就 `from PIL import Image`**，
排除导致 fastembed 整个 import 失败，被 `_resolve_source` 的 `except` 吞掉 → 无嵌入源 → 0 向量。
**修法**：
- spec：`excludes` 移除 `PIL`（也别排 matplotlib，保险）。
- 模型缓存持久化：launcher 冻结时设 `FASTEMBED_CACHE_DIR=~/.weread-skill-plus/models`，
  `embedding.py` 据此传 `TextEmbedding(cache_dir=...)`——否则模型下到临时目录，重启被清要重下 ~95MB。
**实测**：冻结版 `fastembed import ok`、`embed_dim=512`、洞见端点恢复。
> 教训：打包瘦身排除依赖前，必须实测**运行期功能**（不只 import/启动）。

## ✅ 概念抽取 / 读后总结在冻结版失败（已修，两个叠加 bug）

**症状**：.app 里点「生成概念图谱」无反应；批量总结也不出。
**根因**（都同时影响 concepts 和 summaries）：
1. `web/llm.py`（extract_concepts/summarize_book）和 `book_summary` 是 `server.py` 里**函数内懒导入**，
   PyInstaller 没自动收 → 冻结版 import 崩，线程 `finally` 把 running 立刻设回 false（看着像没启动）。
   **修**：spec `hiddenimports += ["llm", "book_summary"]`，pathex 加 `ROOT/book_summary`。
2. `_read_prompt` 用 `ROOT/prompts`（ROOT=llm.py 的 parent.parent），冻结后指向 `_internal` 上层、
   而 prompts 实际在 `_internal/prompts` → 读 prompt 抛异常，每本 fail。
   **修**：`base = sys._MEIPASS if frozen else ROOT`。
**实测**：冻结版 concepts `running:true, ok 递增, fail:0`，进度正常上报。
> 教训：函数内懒导入的本地模块要进 hiddenimports；任何 `__file__` 相对路径在冻结后都要走 `_MEIPASS`。

## 其余决策（不阻塞）

- **embedding 模型不打进二进制**：包体可控。首启向导「开启语义索引」时 fastembed 下载
  `bge-small-zh-v1.5`(~95MB);不开则回退 jieba,基础功能不受影响。
- **签名（v1 不做）**：未签名,首次 macOS「右键→打开」/ Windows「仍要运行」+ 放行图文。
- **console=True**：首版留控制台看日志;稳定后可改 `False`（.app 双击无终端窗）。

## 跨平台

- 本机只能产 macOS 产物。Windows/Linux 走 `release.yml`（各 OS runner 各自 PyInstaller）。
- v1 平台优先级:macOS + Windows,Linux 押后。
