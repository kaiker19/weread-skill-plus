# 导出 / 同步到外部知识库（Obsidian / ima）

当用户想把微信读书的划线 / 批注 / 读后总结 **导出到 Obsidian** 或 **存进腾讯 ima** 时，按本文操作。
两者都复用本地知识库（`data/knowledge.db`），零额外依赖。

---

## Obsidian —— 导出 Markdown（无需任何凭证）

每本有划线的书导成一个 `.md`：frontmatter（书名/作者/分类/概念 tags/读完日期）+ 读后总结
+ 按章节分组的划线 + 批注 + 概念 `[[双链]]`（在 Obsidian graph view 里自动连接同概念的书）。

```bash
python3 cli/weread.py export --out <Obsidian vault 目录>
# 例：python3 cli/weread.py export --out ~/Documents/Obsidian/MyVault/微信读书
```

- 默认 `--out weread-export`（当前目录下），建议指向 vault 下一个独立子目录，避免和已有笔记混。
- 纯增量覆盖：同名书会被新内容覆盖，重跑安全。
- 用户说「导出到 Obsidian / 导出 markdown / 同步到我的笔记库」即触发。

---

## ima（腾讯，与微信读书同源）—— 写笔记 / 灌知识库

### 凭证（一次性）

需要 **两个**：`client_id` + `api_key`，到 https://ima.qq.com/agent-interface 获取。放置（任选）：

```bash
# 方式 A：环境变量
export IMA_CLIENT_ID="xxx"; export IMA_API_KEY="yyy"
# 方式 B：配置文件（与官方 ima-skill 同位置，装了 ima-skill 则自动复用）
mkdir -p ~/.config/ima && echo "xxx" > ~/.config/ima/client_id && echo "yyy" > ~/.config/ima/api_key
```

封装在 `lib/ima.py`（urllib + certifi，只发往 ima.qq.com、凭证不落盘）。

### 场景 1：把一篇读后总结写成 ima 笔记

```bash
python3 -c "
import sys; sys.path.insert(0,'lib')
import ima
r = ima.import_note('# 标题\n\n正文 markdown', folder_name='微信读书')
print(r)  # {code:0, data:{note_id}}
"
```

### 场景 2：把整本书灌进 ima 知识库（可被 ima AI 问答）

⚠️ **ima OpenAPI 没有「创建知识库」接口** —— 知识库需用户先在 ima 客户端手工建一个（如「微信读书」），之后才能往里灌。

```bash
python3 -c "
import sys; sys.path.insert(0,'lib')
import ima
# 1) 找到目标知识库 id
kbs = ima.list_knowledge_bases()
kb = next(k for k in kbs if k['name']=='微信读书')
# 2) 整本书 markdown → 笔记 → 纳入知识库（media_type=11）
md = open('/path/to/book.md').read()   # 或用 cli/weread.py 的渲染逻辑现拼
r = ima.add_to_knowledge_base(md, kb['id'], '书名')
print(r)  # {note_id, media_id} 或 {error, stage}
"
```

批量灌入：遍历 `knowledge_base.get_all_books()`，对每本有划线的书拼 markdown（总结+按章节划线+批注+概念）→ `add_to_knowledge_base`，**每本间 `time.sleep(0.7)` 限速防频控**（ima 错误码 `110021` 频控、`20002` 限频）。

- 用户说「存进 ima / 同步到 ima 知识库 / 导入 ima」即触发。
- 灌入后 ima 后台需几分钟向量化才能问答；条目立即可见。

---

## 凭证安全

ima 凭证只作为 HTTP Header 发往 `ima.qq.com`，不写入任何被追踪的文件、不打日志。引导用户自备，类似微信读书 Key。
