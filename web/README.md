# WeRead Dashboard — Web 端

本地 Web 可视化界面，读取 `data/knowledge.db`，无需额外配置。

## 快速启动

### 1. 启动后端

```bash
pip install -r web/requirements.txt
python3 web/server.py
# → http://localhost:8765/api/docs  (API 文档)
```

### 2. 前端开发模式

```bash
cd web/frontend
npm install
npm run dev
# → http://localhost:5173
```

前端 dev server 会自动将 `/api/*` 代理到后端 8765 端口。

### 2b. 前端生产模式（打包内嵌到后端）

```bash
cd web/frontend && npm install && npm run build
# 构建产物写入 web/frontend/dist/
# 之后只需启动后端，访问 http://localhost:8765 即是完整界面
python3 web/server.py
```

---

## API 端点

| Endpoint | 说明 |
|----------|------|
| `GET /api/stats` | 总体统计（书架/已读/划线/批注） |
| `GET /api/books` | 书架列表（`?status=finished/reading&sort=last_read/highlights&q=搜索`） |
| `GET /api/books/{id}` | 单书详情 + 全部划线 + 批注 |
| `GET /api/timeline` | 月度阅读活动数据（图表用，UTC+8） |
| `GET /api/categories` | 书籍类别分布 |
| `GET /api/search?q=关键词` | 全文搜索（划线 + 批注） |
| `GET /api/echoes?q=查询文本` | 跨书呼应检索（语义优先，降级 jieba） |
| `GET /api/recent_activity` | 最近 30 天阅读动态 |

---

## 页面结构

| 页面 | 路由 | 说明 |
|------|------|------|
| 概览 | `/` | 统计卡片 + 月度活动柱状图 + 最近动态 |
| 书架 | `/books` | 书籍列表，可搜索/筛选/排序 |
| 书籍详情 | `/books/:id` | 单书全部划线（按章节分组）+ 批注 |
| 知识库 | `/knowledge` | 全文关键词搜索 |
| 跨书呼应 | `/echoes` | 输入文本，召回历史相近划线/批注 |

---

## 依赖

**后端**：`fastapi`, `uvicorn`（已有 Python 3.9+ 和 `data/knowledge.db` 即可运行）

**前端**：`react`, `react-router-dom`, `recharts`, `lucide-react`, `tailwindcss`（`npm install` 自动装）
