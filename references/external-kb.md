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

### 场景 2：把书灌进 ima 知识库（可被 ima AI 问答）—— 用 `weread ima`

⚠️ **ima OpenAPI 没有「创建知识库」接口** —— 先在 ima 客户端手工建一个（如「微信读书」）。

```bash
python3 cli/weread.py ima --list              # 列出可用知识库
python3 cli/weread.py ima --kb 微信读书        # 把未导入的书增量灌进去
```

- **增量防重复**：本地记已导入的 book_id（`data/ima_synced.json`），重跑只导新书、不产生重复。
  这很关键——ima **没有去重 / 删除接口**，重复 `import_doc` 会留下两份且删不掉，全靠这边跳过已导。
- 内置限速（每本 0.7s，防频控 `110021`/`20002`），逐本落盘、中断可续。
- 凭证同上（环境变量或 `~/.config/ima/`）。
- **局限**：已导入的书有了新划线**无法更新**（ima 限制：`import_doc` 只能新建）；要刷新得在 ima 手动删旧笔记、并从 `ima_synced.json` 移除该 book_id 后重导。
- 灌入后 ima 后台需几分钟向量化才能问答；条目立即可见。

（只写单篇笔记用 `ima.import_note`，见场景 1。底层批量函数是 `lib/ima.add_to_knowledge_base`。）

---

## 凭证安全

ima 凭证只作为 HTTP Header 发往 `ima.qq.com`，不写入任何被追踪的文件、不打日志。引导用户自备，类似微信读书 Key。
