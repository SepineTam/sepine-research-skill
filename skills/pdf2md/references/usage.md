# `pdf2md` Skill Script Usage Document

## Backends
### MinerU (default)

默认后端。没有 `MINERU_API_TOKEN` 时使用 Flash 模式（免 token，限制 ≤10 MB、≤20 页，只输出 Markdown）；设置了则自动切换到 API 模式（完整结果包）。可以用 `MINERU_MODE=flash|api` 强制指定。

```bash
# 无 token：自动使用 Flash
uv run <skill-base-dir>/scripts/convert.py paper.pdf

# 有 token：自动使用 API 模式
export MINERU_API_TOKEN=xxx
uv run <skill-base-dir>/scripts/convert.py paper.pdf

# 有 token 但强制使用 Flash
MINERU_MODE=flash uv run <skill-base-dir>/scripts/convert.py paper.pdf
# 或者
uv run <skill-base-dir>/scripts/convert.py paper.pdf --env MINERU_MODE=flash
```

可选环境变量：`MINERU_MODE`、`MINERU_API_TOKEN`（或 `MINERU_TOKEN`）、`MINERU_API_BASE`（Flash）、`MINERU_V4_BASE`（API）、`MINERU_MODEL_VERSION`（默认 `vlm`）、`MINERU_LANGUAGE`（默认 `ch`）、`PDF2MD_TIMEOUT`（默认 300 秒）。

输出：`document.md`、`metadata.json`；API 模式额外包含结果包里的全部文件（Markdown、图片、JSON 等）。


### SoMark

需要 API Key；同步解析，输出 Markdown 和 JSON。

```bash
uv run <skill-base-dir>/scripts/convert.py paper.pdf --backend somark \
  --env SOMARK_API_KEY=sk-xxx
```

可选环境变量：`SOMARK_API_BASE_URL`（默认 `https://somark.cn/api/v1`）、`PDF2MD_TIMEOUT`。

输出：`document.md`、`document.json`、`metadata.json`。


### PaddleOCR

百度 PaddleOCR（PP-StructureV3，AI Studio 在线接口），需要个人 API 地址和 access token。

```bash
uv run <skill-base-dir>/scripts/convert.py paper.pdf --backend paddleocr \
  --env PADDLEOCR_API_URL=https://xxxx.aistudio-app.com/layout-parsing \
        PADDLEOCR_ACCESS_TOKEN=xxxx
```

可选环境变量：`PDF2MD_TIMEOUT`。

输出：`document.md`、`document.json`、`metadata.json`。


### PyMuPDF

本地解析，无网络请求；需要 `pymupdf4llm` 依赖。

```bash
uv run --with pymupdf4llm python3 <skill-base-dir>/scripts/convert.py paper.pdf --backend pymupdf
```

输出：`document.md`、`metadata.json`。


### Marker

本地解析，使用 Marker（`marker-pdf`）；首次运行会下载模型。

```bash
uv run --with marker-pdf python3 <skill-base-dir>/scripts/convert.py paper.pdf --backend marker
```

输出：`document.md`、图片文件、`metadata.json`。
