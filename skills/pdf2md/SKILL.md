---
name: pdf2md
description: 把 PDF 转成 markdown 方便 AI 阅读。支持 MinerU、SoMark、PaddleOCR、PyMuPDF、Marker 等后端，可处理论文、报告和扫描件。适用于：(1) 需要将 PDF 转换成 Markdown；(2) 需要读取 PDF 内容之前；(3) 需要总结、翻译或分析 PDF；(4) 扫描件需要 OCR 提取文字；(5) 需要提取 PDF 中的表格、公式或图片。

---

# PDF to Markdown
因为 PDF 这种二进制格式的文件对于 AI 来说并不是一个非常友好的文件格式，所以让 AI 读 PDF 的最好的方式是先将其转换成纯文本格式，如 markdown。

对于转换有多种解决方案，该 skill 支持 MinerU、SoMark、PaddleOCR、PyMuPDF 和 Marker，通过 `--backend` 选择。

## 快速开始

脚本位于 [`scripts/convert.py`](./scripts/convert.py)。

```bash
uv run <skill-base-dir>/scripts/convert.py paper.pdf
```

默认使用 MinerU 作为转换引擎。MinerU 有两种模式：

- **Flash（免 token）**：无需配置，限制 ≤10 MB、≤20 页，只输出 Markdown。适合大多数单篇论文，推荐默认使用。
- **API（需要 token）**：设置 `MINERU_API_TOKEN` 后自动启用，支持更大的文件和页数，返回完整结果包（Markdown、图片、JSON 等）。

如配置了 `MINERU_API_TOKEN` 则使用 API 模式，如没有配置，则优先用默认的 Flash 模式；遇到超过 10 MB、超过 20 页，或需要图片和结构化结果时，再配置 token 走 API。也可以用 `MINERU_MODE=flash|api` 强制指定。

具体的使用指南详见 [references/usage.md](./references/usage.md)。

## Resources

| 介绍 | 文件路径 | 描述 |
|---|---|---|
| 使用指南 | [usage.md](./references/usage.md) | 各后端的调用方式、环境变量和输出说明 |
| 转换脚本 | [convert.py](./scripts/convert.py) | PDF 转 Markdown 的实现 |
