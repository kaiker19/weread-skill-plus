#!/usr/bin/env python3
"""lib/ima.py —— ima OpenAPI 最小客户端：把读后总结/划线写进 ima 笔记。

与官方 ima-skill 的 ima_api.cjs 同协议：POST https://ima.qq.com/<apiPath>，
鉴权走 Header（clientId + apiKey），均由用户自备（ima.qq.com/agent-interface 获取），
只发往 ima.qq.com、不落盘、不外传。HTTPS 复用 knowledge_base.ssl_context()（certifi）。

凭证来源（按优先级）：环境变量 IMA_CLIENT_ID / IMA_API_KEY，或函数参数。

直接测打通：
    IMA_CLIENT_ID=xxx IMA_API_KEY=yyy python3 lib/ima.py
返回 {"code":0,"data":{"note_id":...}} 即写入成功。
"""
import os
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

IMA_BASE = "https://ima.qq.com"
# ctx 只用于上报，非业务校验；可用环境变量覆盖，避免写死会过期的版本号
_CTX_VERSION = os.environ.get("IMA_SKILL_VERSION", "1.0")


def _creds(client_id=None, api_key=None):
    cid = client_id or os.environ.get("IMA_CLIENT_ID") or os.environ.get("IMA_OPENAPI_CLIENTID")
    key = api_key or os.environ.get("IMA_API_KEY") or os.environ.get("IMA_OPENAPI_APIKEY")
    if not cid or not key:
        raise RuntimeError("缺少 ima 凭证：设置 IMA_CLIENT_ID 与 IMA_API_KEY"
                           "（ima.qq.com/agent-interface 获取），或传入参数。")
    return cid, key


def _api(api_path, body, client_id=None, api_key=None):
    from knowledge_base import ssl_context
    cid, key = _creds(client_id, api_key)
    req = urllib.request.Request(
        f"{IMA_BASE}/{api_path.lstrip('/')}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"ima-openapi-clientid": cid, "ima-openapi-apikey": key,
                 "ima-openapi-ctx": f"skill_version={_CTX_VERSION}",
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"code": e.code, "msg": f"HTTP {e.code}"}
    except Exception as e:
        return {"code": -1, "msg": str(e)[:200]}


def import_note(markdown, folder_name="微信读书", client_id=None, api_key=None):
    """新建一篇 ima 笔记（markdown）。返回原始响应 {code, msg, data:{note_id}}。"""
    return _api("openapi/note/v1/import_doc",
                {"content_format": 1, "content": markdown, "folder_name": folder_name},
                client_id, api_key)


if __name__ == "__main__":
    md = ("# weread-skill-plus 打通测试\n\n"
          "这是一条来自「微信读书个人知识库」的测试笔记，收到即说明 ima 打通成功。")
    try:
        print(json.dumps(import_note(md), ensure_ascii=False, indent=2))
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
