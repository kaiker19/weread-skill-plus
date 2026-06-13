# 本地 Web 面板

一个**可选**的图形界面,把 `lib/` 的知识库与语义检索能力做成可视化产品。它**不经过 Agent**——自带一个轻量 FastAPI 后端([web/server.py](../web/server.py)),直接读同一个 `data/knowledge.db`、调同一份 [lib/embedding.py](../lib/embedding.py)。与 Agent 能力完全解耦:不开面板,daily/weekly/summary 等 Agent 能力照常工作。

## 启动

```bash
cd web && python3 server.py          # 默认 http://localhost:8765
```

依赖 `fastapi` + `uvicorn`(`pip install fastapi uvicorn`)。前端是预构建静态文件(`web/frontend/dist`),由 server 直接托管;改了前端需 `cd web/frontend && npm run build`。

## 四个页面

| 页面 | 路径 | 能力 |
|---|---|---|
| **洞见** | `/` | 首页。跨书连接、待重读、近期主题——基于语义层自动浮现的"思考切片"。 |
| **书架** | `/books` | 全部书籍 + 详情。每本书有**读后总结**(自动生成或手写覆盖)、分章划线、批注。 |
| **探索** | `/explore` | 可搜索的概念知识地图。一个搜索框同时点亮图谱相关概念 + 列出语义相近的划线。 |
| **写作台** | `/write` | 边写边浮现你过去的相关划线/批注(语义检索,零 LLM),点一条即插入为引用。 |

## 检索一致性

面板的所有相似度判断与 Agent、CLI **同源**:同一个本地模型(`bge-small-zh-v1.5`)、同一张 `embeddings` 表、同样的 RRF + MMR 混合检索。没有 web 专属的检索实现。

- **探索**(`/explore`)保持"漫游总有结果",不设相关度下限。
- **写作台 / CLI** 设 0.5 相关度下限,宁缺毋滥——写无相关的内容时不硬塞弱结果。

## 可选 LLM(仅"生成"类功能需要)

面板大部分能力(检索、浮现、图谱、手写总结)**不需要 LLM**。只有**自动生成读后总结**、**抽取概念图谱**这类"生成"动作需要,且用你自己配置的 key:

- 在设置页(`/settings`)填写,或写 `data/llm.json`:
  ```json
  {"endpoint": "...", "api_key": "...", "model": "...", "format": "openai"}
  ```
- `format` 支持 `openai` / `anthropic` / `gemini`。未配置时,这些按钮显示"未配置 LLM · 去设置",其余功能不受影响。

## 主要接口(供插件/外部工具调用)

server 是个本地 HTTP 接口,任何工具都能调:

- `GET /api/explore?q=<词>&limit=<n>` — 概念点亮 + 相近划线(写作台同款)
- `GET /api/graph` — 概念图谱节点与边
- `GET /api/books` `GET /api/books/{id}` — 书架与详情
- `POST /api/books/{id}/summary` — 写入/覆盖手写读后总结
- `POST /api/sync` — 触发增量同步

> **发布说明**:`web/` 默认在 `.gitignore` 中、不随 skill 发布,是本地增强。这份 reference 描述的是本机用法;若要把面板一并分发,需要单独决定。
