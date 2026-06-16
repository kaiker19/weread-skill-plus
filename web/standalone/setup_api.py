#!/usr/bin/env python3
"""web/standalone/setup_api.py — 纯本地版新增的 HTTP 路由（开发期隔离，整体未完成前不进 git）

在现有 server.app 之上追加「首次引导」需要的两类接口：
  1. WeRead API Key 的查询 / 填写 / 校验
  2. 全量同步（后台线程 + 进度轮询），照搬 server.py 里 backfill 的范式

设计原则：不修改任何被 git 追踪的文件——只复用 lib/sync.py 的同步函数，
并把 key 写到 lib/sync.py 读取的同一个路径。
"""
import sys
import threading
import time
from pathlib import Path

# 复用 lib/ 下的同步逻辑
_LIB = Path(__file__).resolve().parent.parent.parent / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# key 文件路径与 lib/sync.py._load_api_key 同源：都走 knowledge_base.data_dir()
# （普通态=项目根 data/；打包态=~/.weread-skill-plus/）。这样向导写、sync 读一定一致。
from knowledge_base import data_dir
_API_KEY_FILE = data_dir() / "api_key"


# ── 浏览器心跳看门狗 ──────────────────────────────────────────────────────────
# 收到首个心跳后开始监视；超过 _HB_TIMEOUT 秒没有新心跳（用户关 tab/浏览器）即自杀，
# 防止后台 uvicorn 常驻泄漏。从未收到心跳（agent 直跑、无浏览器）则永不触发。
# 180s 而非 15s：浏览器会节流后台标签页的定时器，用户切屏/去复制 key 时心跳会变慢，
# 太短会误杀正在用的服务。真正关 tab 由 sendBeacon('/api/shutdown') 立即退；看门狗只兜底崩溃/强退。
_HB_TIMEOUT = 180
_hb = {"last": 0.0, "armed": False}


def _watchdog():
    import os
    while True:
        time.sleep(5)
        if time.time() - _hb["last"] > _HB_TIMEOUT:
            os._exit(0)


# ── 全量同步任务状态（进程内单任务，前端轮询）────────────────────────────────
_full_sync = {
    "running": False, "finished": False, "phase": "", "current": "",
    "total": 0, "done": 0, "new_highlights": 0, "new_reviews": 0,
    "embedded": 0, "error": "",
}


def _run_full_sync():
    """后台线程：拉书架 → 逐书同步划线/批注（逐本上报进度）→ 顺带嵌入新条目。
    复刻 sync.sync_all(force=True) 的流程，差别仅在于逐本上报 done/current。"""
    global _full_sync
    try:
        from sync import (init_db, sync_shelf, sync_highlights_for_book,
                          sync_reviews_for_book, set_sync_state)
        init_db()
        _full_sync["phase"] = "shelf"
        books = sync_shelf()
        _full_sync.update(total=len(books), done=0, phase="content")
        nh_total = nr_total = 0
        for b in books:
            if not _full_sync["running"]:
                break
            _full_sync["current"] = b.get("title", "")
            bid = b["book_id"]
            nh_total += sync_highlights_for_book(bid)
            nr_total += sync_reviews_for_book(bid)
            _full_sync.update(done=_full_sync["done"] + 1,
                              new_highlights=nh_total, new_reviews=nr_total)
            time.sleep(0.3)  # 与 sync_all 一致的限速
        set_sync_state("last_sync_ts", str(int(time.time())))
        # 顺带嵌入新条目（可选，失败不影响主流程）。逐批上报进度，避免 UI 看着卡住。
        _full_sync.update(phase="embedding", done=0, total=0, current="")
        try:
            from embedding import backfill
            def _on_embed(done, total):
                _full_sync.update(done=done, total=total)
            _full_sync["embedded"] = backfill(verbose=False, progress=_on_embed)
        except Exception:
            _full_sync["embedded"] = 0
    except Exception as e:
        _full_sync["error"] = str(e)[:300]
    finally:
        _full_sync["running"] = False
        _full_sync["finished"] = True
        _full_sync["current"] = ""
        _full_sync["phase"] = "done"


def _validate_key():
    """用当前 key 文件调一次 /shelf/sync 看是否有效。返回 (ok, errmsg)。"""
    from sync import _api
    data = _api("/shelf/sync")
    if data.get("errcode"):
        return False, str(data.get("errmsg", data.get("errcode")))
    return True, ""


class ApiKeyIn(BaseModel):
    api_key: str


def _move_spa_routes_last(app):
    """把 SPA 兜底 catch-all (/{full_path:path}) 移到路由表末尾，
    避免它抢在新加的 /api/* 之前匹配（dist 存在时 server.py 会注册它）。"""
    routes = app.router.routes
    spa = [r for r in routes if getattr(r, "path", "") == "/{full_path:path}"]
    for r in spa:
        routes.remove(r)
        routes.append(r)


def attach(app):
    """在已有 FastAPI app 上挂载新路由。"""
    router = APIRouter()

    @router.get("/api/settings/apikey")
    def get_apikey():
        configured = _API_KEY_FILE.exists() and bool(_API_KEY_FILE.read_text().strip())
        return {"configured": configured}

    @router.post("/api/settings/apikey")
    def save_apikey(body: ApiKeyIn):
        key = body.api_key.strip()
        if not key:
            raise HTTPException(status_code=400, detail="API Key 为空")
        _API_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        # 先备份旧值，校验失败可回滚，避免把一个无效 key 写坏
        old = _API_KEY_FILE.read_text() if _API_KEY_FILE.exists() else None
        _API_KEY_FILE.write_text(key)
        ok, err = _validate_key()
        if not ok:
            if old is None:
                try:
                    _API_KEY_FILE.unlink()
                except Exception:
                    pass
            else:
                _API_KEY_FILE.write_text(old)
            raise HTTPException(status_code=400, detail=f"Key 校验失败：{err}")
        return {"ok": True, "configured": True}

    @router.post("/api/sync/full/start")
    def full_sync_start():
        if _full_sync["running"]:
            raise HTTPException(status_code=409, detail="全量同步已在进行")
        if not (_API_KEY_FILE.exists() and _API_KEY_FILE.read_text().strip()):
            raise HTTPException(status_code=409, detail="尚未配置 WeRead API Key")
        _full_sync.update(running=True, finished=False, phase="启动中", current="",
                          total=0, done=0, new_highlights=0, new_reviews=0,
                          embedded=0, error="")
        threading.Thread(target=_run_full_sync, daemon=True).start()
        return {"started": True}

    @router.get("/api/sync/full/status")
    def full_sync_status():
        return _full_sync

    @router.post("/api/sync/full/stop")
    def full_sync_stop():
        _full_sync["running"] = False
        return {"stopped": True}

    @router.post("/api/shutdown")
    def shutdown():
        """退出单机应用：停掉后台服务进程（前端「退出应用」按钮调用）。"""
        import os
        threading.Timer(0.4, lambda: os._exit(0)).start()
        return {"ok": True}

    @router.post("/api/heartbeat")
    def heartbeat():
        """浏览器存活心跳：tab 关闭后心跳停止，看门狗超时自动退出。"""
        _hb["last"] = time.time()
        if not _hb["armed"]:
            _hb["armed"] = True
            threading.Thread(target=_watchdog, daemon=True).start()
        return {"ok": True}

    app.include_router(router)
    _move_spa_routes_last(app)
    return app
