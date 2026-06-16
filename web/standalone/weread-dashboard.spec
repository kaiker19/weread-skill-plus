# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格（onedir）—— 纯本地版打包。
开发期隔离，整体未完成前不进 git。

用法（在仓库根目录）：
    cd web/frontend && npm ci && npm run build && cd -
    pyinstaller web/standalone/weread-dashboard.spec --noconfirm

产物：dist/WeReadDashboard/（onedir）。Mac 下再由 build_macos.sh 包成 .app/.dmg。

⚠️ 见 BUILD.md「待验证的坑」：dist 路径在冻结后的解析、onnxruntime 体积、
   首启模型下载。本 spec 是首版骨架，需一次实际构建收敛。
"""
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

# spec 执行时 CWD = 仓库根（pyinstaller 在根目录调用）
ROOT = Path.cwd()
WEB = ROOT / "web"
LIB = ROOT / "lib"
STANDALONE = WEB / "standalone"

# 把源码树作为数据一并带上，保持相对层级，让 server.py 的
# Path(__file__).parent/"frontend"/"dist" 等相对定位在冻结后仍成立。
datas = [
    (str(WEB / "frontend" / "dist"), "frontend/dist"),   # 前端构建产物
    (str(WEB / "server.py"), "."),                        # server 模块
    (str(STANDALONE / "setup_api.py"), "."),
    (str(LIB), "lib"),                                    # 知识库/检索/同步
    (str(ROOT / "prompts"), "prompts"),                  # 总结/概念 prompt（web/llm 用）
]

# 把语义模型打进包：国内 HuggingFace 常被墙，运行时下载不可靠 → 离线内置。
_model = STANDALONE / "_model"
if _model.exists():
    datas.append((str(_model), "fastembed_models"))

# 第三方原生依赖：fastembed + onnxruntime 必须 collect_all（含 .so/.dylib/.dll 与数据）
hiddenimports = []
for pkg in ("fastembed", "onnxruntime", "tokenizers", "huggingface_hub"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        hiddenimports += h
    except Exception:
        pass
hiddenimports += collect_submodules("uvicorn")
# llm / book_summary 是 server.py 里函数内懒导入的 —— 必须显式列出，否则冻结版
# 概念抽取、读后总结生成会因 import 失败而静默崩溃。
hiddenimports += ["server", "setup_api", "knowledge_base", "embedding", "sync",
                  "fastapi", "jieba", "llm", "book_summary"]

a = Analysis(
    [str(STANDALONE / "launcher.py")],
    pathex=[str(STANDALONE), str(WEB), str(LIB), str(ROOT / "book_summary")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    excludes=["tkinter", "pytest"],   # 瘦身。注意：不能排除 PIL —— fastembed 依赖它，排除会导致 import 失败、语义索引建不出来
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name="WeReadDashboard", console=True,   # console=True 便于首版看日志，稳定后可改 False
          disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, name="WeReadDashboard")

# macOS：再包成 .app，用户双击即用、可拖进「应用程序」
import sys as _sys
_icon = STANDALONE / "icon.icns"
if _sys.platform == "darwin":
    app = BUNDLE(coll, name="WeRead Dashboard.app",
                 icon=str(_icon) if _icon.exists() else None,
                 bundle_identifier="com.weread.dashboard",
                 info_plist={"NSHighResolutionCapable": True, "LSBackgroundOnly": False})
