#!/usr/bin/env python3
"""web/standalone/launcher.py — 纯本地版统一入口（开发期隔离，整体未完成前不进 git）

两种跑法，同一份逻辑：
  - 用户：被 PyInstaller 打包成二进制，双击即运行本脚本。
  - agent：直接 `python3 web/standalone/launcher.py` 拉起同一套面板。

职责：初始化 db → 选空闲端口 → 在 server.app 上挂新路由 → 关 reload 启动 → 自动开浏览器。
"""
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Windows 控制台默认 cp1252，打印中文/箭头会 UnicodeEncodeError 直接崩。统一改 UTF-8。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_HERE = Path(__file__).resolve().parent          # web/standalone
_WEB = _HERE.parent                              # web
_ROOT = _WEB.parent                              # 项目根
_LIB = _ROOT / "lib"

for p in (str(_HERE), str(_WEB), str(_LIB)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _is_frozen():
    """是否被 PyInstaller 打包后运行。"""
    return getattr(sys, "frozen", False)


def _ensure_user_data_dir():
    """打包运行时把所有数据（db / api_key / llm.json / embedding.json）落到用户目录
    （二进制内部只读）。统一通过 WEREAD_DATA_DIR，knowledge_base.data_dir() 据此解析。
    开发 / agent 直接跑时不动默认路径（项目根 data/）。Path.home() 跨 Mac/Win 通用。"""
    if _is_frozen() and not os.environ.get("WEREAD_DATA_DIR"):
        d = Path.home() / ".weread-skill-plus"
        d.mkdir(parents=True, exist_ok=True)
        os.environ["WEREAD_DATA_DIR"] = str(d)
        # 语义模型缓存落持久目录（可写），首次从打进包里的模型拷过去——
        # 不依赖运行时从 HuggingFace 下载（国内常被墙）。
        mdir = d / "models"
        mdir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("FASTEMBED_CACHE_DIR", str(mdir))
        _seed_bundled_model(mdir)


def _seed_bundled_model(models_dir):
    """若用户目录还没有模型，从二进制里内置的副本拷过去（离线/国内可用）。
    Windows(onedir) 的 datas 落在 exe 同级的 _internal/，故多搜几处。"""
    import shutil
    name = "models--Qdrant--bge-small-zh-v1.5"
    if (models_dir / name).exists():
        return
    exe_dir = Path(sys.executable).resolve().parent
    for base in (getattr(sys, "_MEIPASS", None), str(_HERE), str(exe_dir),
                 str(exe_dir / "_internal"), str(_HERE / "_internal")):
        if not base:
            continue
        src = Path(base) / "fastembed_models" / name
        if src.exists():
            try:
                shutil.copytree(src, models_dir / name)
            except Exception:
                pass
            return


def _free_port(start=8765, tries=20):
    """从 start 起找一个未被占用的端口。"""
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


def _our_instance(port=8765):
    """探测 8765 上是否已有一份我们自己的实例在跑（单实例判定）。
    用单机版独有的 /api/settings/apikey 路由当指纹：200 即认定是我们的实例。
    避免重复双击时又起一份后台 uvicorn 造成残留。"""
    import urllib.request
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/settings/apikey", timeout=1.0) as r:
            return r.status == 200
    except Exception:
        return False


def main():
    _ensure_user_data_dir()

    # 单实例：已有自己的实例在跑就直接开浏览器指过去，不再起第二份服务
    if _our_instance(8765):
        url = "http://127.0.0.1:8765"
        print(f"WeRead Dashboard 已在运行 → {url}")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        return

    import uvicorn
    import server                      # 定义 app，并按 dist 是否存在注册 SPA 路由
    from knowledge_base import init_db
    from setup_api import attach

    init_db()
    attach(server.app)                 # 追加 key / 全量同步路由，并把 SPA 兜底移到末尾

    port = _free_port()
    url = f"http://127.0.0.1:{port}"

    def _open():
        time.sleep(1.0)
        if os.environ.get("WEREAD_NO_BROWSER"):   # 测试用：不自动开浏览器
            return
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=_open, daemon=True).start()

    print(f"WeRead Dashboard (local) → {url}")
    uvicorn.run(server.app, host="127.0.0.1", port=port, reload=False, log_level="info")


if __name__ == "__main__":
    main()
