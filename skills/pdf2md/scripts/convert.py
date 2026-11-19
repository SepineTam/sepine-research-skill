#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# Copyright (C) 2026 - Present Song Tan, Inc. All Rights Reserved
#
# @Author : Song Tan
# @Email  : sepinetam@gmail.com
# @File   : pdf2md/scripts/convert.py

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from abc import ABC, abstractmethod
from pathlib import Path

__authors__ = [
    {
        "name": "Song Tan", 
        "email": "sepinetam@gmail.com",
    }
]
__version__ = "v0.1.0"
__website__ = "https://github.com/sepinetam/sepine-research-skill"


DEFAULT_TIMEOUT = 300.0
MAX_FLASH_BYTES = 10_000_000


class ConvertBase(ABC):
    OUTPUT_BASE: Path = Path.home() / ".sepine-skill" / "pdf2md" / "output"

    def __init__(self, output_base: Path = OUTPUT_BASE):
        self.output_base = output_base

    @abstractmethod
    def convert(
        self, 
        source: str | Path, 
        output_path: Path | None = None
    ) -> Path:
        ...

    def hash(self, ctx: bytes) -> str:
        return hashlib.sha256(ctx).hexdigest()[:16]

    def _generate_output_path(self, ctx: bytes) -> Path:
        output_path = self.output_base / self.hash(ctx)
        output_path.mkdir(parents=True, exist_ok=True)
        return output_path

    @staticmethod
    def _request(
        url: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 60.0,
    ) -> bytes:
        request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"{method} {url} failed: HTTP {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{method} {url} failed: {exc.reason}") from exc

    @classmethod
    def _request_json(
        cls,
        url: str,
        *,
        method: str = "GET",
        payload: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request_headers = dict(headers or {})
        if data is not None:
            request_headers.setdefault("Content-Type", "application/json")
        raw = cls._request(url, method=method, data=data, headers=request_headers)
        return json.loads(raw.decode("utf-8"))

    @staticmethod
    def _multipart(
        fields: list[tuple[str, str]],
        filename: str,
        content: bytes,
        content_type: str,
    ) -> tuple[bytes, str]:
        boundary = uuid.uuid4().hex
        safe_name = filename.replace('"', "_")
        parts: list[bytes] = []

        for name, value in fields:
            parts.append(
                (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode()
            )
        parts.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="{safe_name}"\r\nContent-Type: {content_type}\r\n\r\n'
            ).encode()
        )
        parts.append(content)
        parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        return b"".join(parts), f"multipart/form-data; boundary={boundary}"

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class MinerU(ConvertBase):
    FLASH_BASE = "https://mineru.net/api/v1/agent"
    API_BASE = "https://mineru.net/api/v4"

    def __init__(
        self,
        output_base: Path = ConvertBase.OUTPUT_BASE,
        mode: str | None = None,
    ):
        super().__init__(output_base)
        default_mode = "api" if self.MINERU_API_TOKEN else "flash"
        self.mode = (mode or os.getenv("MINERU_MODE") or default_mode).lower()

    @property
    def MINERU_API_TOKEN(self) -> str | None:
        return os.getenv("MINERU_API_TOKEN") or os.getenv("MINERU_TOKEN")

    def convert(
        self,
        source: str | Path,
        output_path: Path | None = None,
    ) -> Path:
        source = Path(source).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"PDF not found: {source}")

        content = source.read_bytes()
        output_dir = Path(output_path) if output_path else self._generate_output_path(content)
        output_dir.mkdir(parents=True, exist_ok=True)

        if self.mode == "flash":
            self._convert_flash(source, content, output_dir)
        elif self.mode == "api":
            if not self.MINERU_API_TOKEN:
                raise RuntimeError("MINERU_API_TOKEN is required for MinerU API mode")
            self._convert_api(source, content, output_dir)
        else:
            raise ValueError(f"Unknown MinerU mode: {self.mode!r} (use 'flash' or 'api')")

        return output_dir

    def _convert_flash(self, source: Path, content: bytes, output_dir: Path) -> None:
        if len(content) > MAX_FLASH_BYTES:
            raise ValueError("MinerU flash mode accepts files up to 10 MB only")

        base = os.getenv("MINERU_API_BASE", self.FLASH_BASE).rstrip("/")
        created = self._request_json(
            f"{base}/parse/file",
            method="POST",
            payload={
                "file_name": source.name,
                "language": os.getenv("MINERU_LANGUAGE", "ch"),
            },
        )
        if created.get("code", 0) != 0:
            raise RuntimeError(f"MinerU error {created.get('code')}: {created.get('msg')}")

        data = created.get("data") or {}
        task_id = data.get("task_id")
        file_url = data.get("file_url")
        if not task_id or not file_url:
            raise RuntimeError(f"MinerU returned no upload task: {created}")

        self._request(file_url, method="PUT", data=content, headers={"Content-Type": ""})

        result = self._wait(base, task_id)
        markdown_url = result.get("markdown_url")
        if not markdown_url:
            raise RuntimeError(f"MinerU finished without a markdown URL: {result}")

        markdown = self._request(markdown_url, timeout=120.0).decode("utf-8", errors="replace")
        (output_dir / "document.md").write_text(markdown, encoding="utf-8")
        self._write_json(
            output_dir / "metadata.json",
            {
                "backend": "mineru",
                "mode": "flash",
                "source": str(source),
                "task_id": task_id,
                "state": result.get("state"),
                "progress": result.get("extract_progress"),
            },
        )

    def _convert_api(self, source: Path, content: bytes, output_dir: Path) -> None:
        token = self.MINERU_API_TOKEN
        base = os.getenv("MINERU_V4_BASE", self.API_BASE).rstrip("/")
        headers = {"Authorization": f"Bearer {token}"}

        created = self._request_json(
            f"{base}/file-urls/batch",
            method="POST",
            payload={
                "enable_formula": True,
                "language": os.getenv("MINERU_LANGUAGE", "ch"),
                "files": [{"name": source.name, "data_id": self.hash(content)}],
                "model_version": os.getenv("MINERU_MODEL_VERSION", "vlm"),
            },
            headers=headers,
        )
        if created.get("code", 0) != 0:
            raise RuntimeError(f"MinerU error {created.get('code')}: {created.get('msg')}")

        data = created.get("data") or {}
        batch_id = data.get("batch_id")
        file_urls = data.get("file_urls") or []
        if not batch_id or not file_urls:
            raise RuntimeError(f"MinerU returned no upload batch: {created}")

        for file_url in file_urls:
            self._request(file_url, method="PUT", data=content, headers={"Content-Type": ""})

        result = self._wait_batch(base, batch_id, headers)
        zip_url = result.get("full_zip_url")
        if not zip_url:
            raise RuntimeError(f"MinerU finished without a result archive: {result}")

        archive = self._request(zip_url, timeout=300.0)
        self._extract_zip(archive, output_dir)
        self._write_json(
            output_dir / "metadata.json",
            {
                "backend": "mineru",
                "mode": "api",
                "source": str(source),
                "batch_id": batch_id,
                "state": result.get("state"),
            },
        )

    @classmethod
    def _wait(cls, base: str, task_id: str) -> dict:
        timeout = float(os.getenv("PDF2MD_TIMEOUT", DEFAULT_TIMEOUT))
        deadline = time.monotonic() + timeout
        interval = 2.0

        while True:
            body = cls._request_json(f"{base}/parse/{task_id}")
            if body.get("code", 0) != 0:
                raise RuntimeError(f"MinerU error {body.get('code')}: {body.get('msg')}")

            data = body.get("data") or {}
            state = data.get("state")
            if state == "done":
                return data
            if state == "failed":
                raise RuntimeError(f"MinerU task failed: {data.get('err_msg') or data}")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"MinerU task {task_id} timed out after {timeout:.0f}s")

            time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
            interval = min(interval * 2, 30.0)

    @classmethod
    def _wait_batch(cls, base: str, batch_id: str, headers: dict[str, str]) -> dict:
        timeout = float(os.getenv("PDF2MD_TIMEOUT", DEFAULT_TIMEOUT))
        deadline = time.monotonic() + timeout
        interval = 3.0

        while True:
            body = cls._request_json(
                f"{base}/extract-results/batch/{batch_id}", headers=headers
            )
            if body.get("code", 0) != 0:
                raise RuntimeError(f"MinerU error {body.get('code')}: {body.get('msg')}")

            results = (body.get("data") or {}).get("extract_result") or []
            if results:
                state = results[0].get("state")
                if state == "done":
                    return results[0]
                if state == "failed":
                    raise RuntimeError(
                        f"MinerU task failed: {results[0].get('err_msg') or results[0]}"
                    )

            if time.monotonic() >= deadline:
                raise TimeoutError(f"MinerU batch {batch_id} timed out after {timeout:.0f}s")

            time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
            interval = min(interval * 2, 30.0)

    @staticmethod
    def _extract_zip(archive: bytes, output_dir: Path) -> None:
        root = output_dir.resolve()
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            for member in zf.infolist():
                target = (output_dir / member.filename).resolve()
                if target != root and not str(target).startswith(str(root) + os.sep):
                    continue
                zf.extract(member, output_dir)

        markdown_files = sorted(output_dir.rglob("*.md"))
        if markdown_files and not (output_dir / "document.md").exists():
            (output_dir / "document.md").write_bytes(markdown_files[0].read_bytes())


class SoMark(ConvertBase):
    API_BASE = "https://somark.cn/api/v1"

    def convert(
        self,
        source: str | Path,
        output_path: Path | None = None,
    ) -> Path:
        source = Path(source).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"PDF not found: {source}")

        api_key = os.getenv("SOMARK_API_KEY")
        if not api_key:
            raise RuntimeError("SOMARK_API_KEY environment variable is not set")

        content = source.read_bytes()
        output_dir = Path(output_path) if output_path else self._generate_output_path(content)
        output_dir.mkdir(parents=True, exist_ok=True)

        base = os.getenv("SOMARK_API_BASE_URL", self.API_BASE).rstrip("/")
        content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        body, multipart_type = self._multipart(
            [
                ("output_formats", "markdown"),
                ("output_formats", "json"),
                ("api_key", api_key),
            ],
            source.name,
            content,
            content_type,
        )
        raw = self._request(
            f"{base}/parse/sync",
            method="POST",
            data=body,
            headers={"Content-Type": multipart_type},
            timeout=float(os.getenv("PDF2MD_TIMEOUT", DEFAULT_TIMEOUT)),
        )
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("code", 0) != 0:
            raise RuntimeError(f"SoMark error {payload.get('code')}: {payload.get('message')}")

        data = payload.get("data") or {}
        result = data.get("result") or {}
        outputs = result.get("outputs") or {}

        markdown = outputs.get("markdown")
        if markdown:
            (output_dir / "document.md").write_text(markdown, encoding="utf-8")
        if outputs.get("json") is not None:
            self._write_json(output_dir / "document.json", outputs["json"])

        self._write_json(
            output_dir / "metadata.json",
            {
                "backend": "somark",
                "source": str(source),
                "task_id": data.get("task_id"),
                "file_name": result.get("file_name"),
                "metadata": data.get("metadata"),
                "catalog": result.get("catalog"),
            },
        )
        return output_dir


class PaddleOCR(ConvertBase):
    API_URL_ENV = "PADDLEOCR_API_URL"
    TOKEN_ENV = "PADDLEOCR_ACCESS_TOKEN"

    def convert(
        self,
        source: str | Path,
        output_path: Path | None = None,
    ) -> Path:
        source = Path(source).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"PDF not found: {source}")

        api_url = os.getenv(self.API_URL_ENV)
        token = os.getenv(self.TOKEN_ENV)
        if not api_url or not token:
            raise RuntimeError(
                f"{self.API_URL_ENV} and {self.TOKEN_ENV} environment variables must be set"
            )

        content = source.read_bytes()
        output_dir = Path(output_path) if output_path else self._generate_output_path(content)
        output_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "file": base64.b64encode(content).decode("ascii"),
            "fileType": 0,  # 0 = PDF, 1 = image
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useChartRecognition": False,
        }
        raw = self._request(
            api_url,
            method="POST",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"token {token}",
                "Content-Type": "application/json",
            },
            timeout=float(os.getenv("PDF2MD_TIMEOUT", DEFAULT_TIMEOUT)),
        )
        response = json.loads(raw.decode("utf-8"))
        if response.get("errorCode", 0) != 0:
            raise RuntimeError(
                f"PaddleOCR error {response.get('errorCode')}: {response.get('errorMsg')}"
            )

        result = response.get("result") or {}
        pages = result.get("layoutParsingResults") or []

        markdown_parts = []
        for page in pages:
            text = (page.get("markdown") or {}).get("text")
            if not text:
                blocks = page.get("parsing_res_list") or []
                blocks = sorted(blocks, key=lambda block: block.get("block_order", 0))
                text = "\n\n".join(
                    block.get("block_content", "")
                    for block in blocks
                    if block.get("block_content")
                )
            if text:
                markdown_parts.append(text)
        markdown = "\n\n".join(markdown_parts)

        (output_dir / "document.md").write_text(markdown, encoding="utf-8")
        self._write_json(output_dir / "document.json", result)
        self._write_json(
            output_dir / "metadata.json",
            {
                "backend": "paddleocr",
                "source": str(source),
                "pages": len(pages),
            },
        )
        return output_dir


class PyMuPDF(ConvertBase):
    def convert(
        self,
        source: str | Path,
        output_path: Path | None = None,
    ) -> Path:
        try:
            import pymupdf4llm
        except ImportError as exc:
            raise RuntimeError(
                "pymupdf4llm is required: uv run --with pymupdf4llm "
                "python3 convert.py ... --backend pymupdf"
            ) from exc

        source = Path(source).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"PDF not found: {source}")

        content = source.read_bytes()
        output_dir = Path(output_path) if output_path else self._generate_output_path(content)
        output_dir.mkdir(parents=True, exist_ok=True)

        markdown = pymupdf4llm.to_markdown(str(source))
        (output_dir / "document.md").write_text(markdown, encoding="utf-8")
        self._write_json(
            output_dir / "metadata.json",
            {
                "backend": "pymupdf",
                "source": str(source),
            },
        )
        return output_dir


class Marker(ConvertBase):
    def convert(
        self,
        source: str | Path,
        output_path: Path | None = None,
    ) -> Path:
        try:
            from marker.converters.pdf import PdfConverter
            from marker.models import create_model_dict
            from marker.output import text_from_rendered
        except ImportError as exc:
            raise RuntimeError(
                "marker-pdf is required: uv run --with marker-pdf "
                "python3 convert.py ... --backend marker"
            ) from exc

        source = Path(source).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"PDF not found: {source}")

        content = source.read_bytes()
        output_dir = Path(output_path) if output_path else self._generate_output_path(content)
        output_dir.mkdir(parents=True, exist_ok=True)

        converter = PdfConverter(artifact_dict=create_model_dict())
        rendered = converter(str(source))
        text, _extension, images = text_from_rendered(rendered)

        (output_dir / "document.md").write_text(text, encoding="utf-8")
        for filename, image in images.items():
            image_path = output_dir / filename
            image_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(image_path)

        self._write_json(
            output_dir / "metadata.json",
            {
                "backend": "marker",
                "source": str(source),
                "images": len(images),
            },
        )
        return output_dir


BACKENDS = {
    "marker": Marker,
    "mineru": MinerU,
    "paddleocr": PaddleOCR,
    "pymupdf": PyMuPDF,
    "somark": SoMark,
}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="convert.py",
        description="Convert a PDF to Markdown using the selected backend.",
    )
    parser.add_argument("file", type=Path, help="Path to the PDF file")
    parser.add_argument(
        "--output_base",
        type=Path,
        default=ConvertBase.OUTPUT_BASE,
        help="Base directory for conversion output",
    )
    parser.add_argument(
        "--backend",
        choices=sorted(BACKENDS),
        default="mineru",
        help="Parsing backend (default: mineru)",
    )
    parser.add_argument(
        "--env",
        nargs="+",
        default=[],
        metavar="KEY=VALUE",
        help="Extra environment variables, e.g. SOMARK_API_KEY=sk-xxx",
    )
    args = parser.parse_args(argv)

    for item in args.env:
        key, sep, value = item.partition("=")
        if not sep or not key:
            parser.error(f"invalid --env value: {item!r}")
        os.environ[key] = value

    converter = BACKENDS[args.backend](output_base=args.output_base)
    print(converter.convert(args.file))


if __name__ == "__main__":
    main()
