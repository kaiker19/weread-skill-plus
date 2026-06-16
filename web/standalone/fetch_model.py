#!/usr/bin/env python3
"""打包/CI 用：把语义模型下载到 web/standalone/_model（fastembed 缓存格式），供 spec 打进二进制。
本地已有则跳过。GitHub Actions（美区 runner）可正常访问 HuggingFace；这样发出的二进制内置模型、
终端用户（含国内）无需再下载。"""
import os
from pathlib import Path

_MODEL_DIR = Path(__file__).resolve().parent / "_model"
_NAME = "models--Qdrant--bge-small-zh-v1.5"


def main():
    # 纯 ASCII 输出：Windows CI 控制台默认 cp1252，打印中文会 UnicodeEncodeError
    if (_MODEL_DIR / _NAME).exists():
        print(f"[fetch_model] already present: {_MODEL_DIR / _NAME}")
        return
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["FASTEMBED_CACHE_DIR"] = str(_MODEL_DIR)
    from fastembed import TextEmbedding
    TextEmbedding(model_name="BAAI/bge-small-zh-v1.5")   # triggers download into _MODEL_DIR
    print(f"[fetch_model] downloaded to {_MODEL_DIR}")


if __name__ == "__main__":
    main()
