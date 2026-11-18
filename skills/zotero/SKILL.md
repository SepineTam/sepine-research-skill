---
name: zotero-search
description: 该 Skill 使 agent 能够在不打开图形界面的情况下检索用户的 Zotero 数据库。适用于以下场景：(1) 用户要求你从 Zotero 中查找条目；(2) 你需要检索 Zotero 中的记录；(3) 判断用户是否拥有某篇论文的全文；(4) 其他与 Zotero 相关的需求
metadata: 
  version: v0.1.0
---

# Zotero 检索

Zotero 是研究者获取学术文献最常用的软件之一，其数据库通常存放在用户本地计算机中。

如果未配置 [AIdea-Zotero-MCP](https://github.com/aidea-labs/aidea-zotero-mcp) 则使用该项目的配套脚本。

## 使用说明（脚本）
### help

查看全部命令或某个命令的用法；加 `--docstring` 输出该命令底层方法的 docstring。

```bash
python3 <skill-base-dir>/scripts/zotero.py help
python3 <skill-base-dir>/scripts/zotero.py help <command>
python3 <skill-base-dir>/scripts/zotero.py help <command> --docstring
```

### search

按关键词检索条目。多个关键词为 AND，匹配标题、短标题、摘要、出版物、作者、tag 和笔记；返回 JSON 数组。

```bash
python3 <skill-base-dir>/scripts/zotero.py search <keywords...> [--year-from N] [--year-to N] [--limit N] [--offset N] [--in-publication NAME] [--no-tag] [--no-notes]
```

参数：

- `<keywords...>`：一个或多个关键词，多个之间是 AND
- `--year-from` / `--year-to`：出版年份范围，含边界
- `--limit` / `--offset`：返回条数（默认 25）与跳过的条数（默认 0）
- `--in-publication`：限定期刊、会议或书名
- `--no-tag`：关键词不匹配 tag
- `--no-notes`：关键词不匹配笔记内容

### cite

按 key 输出单条 BibTeX。

```bash
python3 <skill-base-dir>/scripts/zotero.py cite <key>
```

### get_details

输出条目的完整字段（JSON）。

```bash
python3 <skill-base-dir>/scripts/zotero.py get_details <key>
```

### get_notes

输出条目的笔记正文（HTML 数组）。

```bash
python3 <skill-base-dir>/scripts/zotero.py get_notes <key>
```

### get_attachments

输出条目的附件列表（JSON），包含路径、文件名、类型、链接地址和全文标记。

```bash
python3 <skill-base-dir>/scripts/zotero.py get_attachments <key>
```

### get_fulltext

返回全文的实际位置：本地文件路径或 URL；不返回文本内容。

```bash
python3 <skill-base-dir>/scripts/zotero.py get_fulltext <key>
```
