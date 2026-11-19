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
import hashlib
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
import uuid

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
    def _request_json(cls, url: str, *, method: str = "GET", payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else None
        raw = cls._request(url, method=method, data=data, headers=headers)
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
                ).encode("utf-8")
            )
        parts.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="{safe_name}"\r\nContent-Type: {content_type}\r\n\r\n'
            ).encode("utf-8")
        )
        parts.append(content)
        parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        return b"".join(parts), f"multipart/form-data; boundary={boundary}"

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class MinerU(ConvertBase):
    FLASH_BASE = "https://mineru.net/api/v1/agent"

    def convert(
        self,
        source: str | Path,
        output_path: Path | None = None,
    ) -> Path:
        source = Path(source).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"PDF not found: {source}")

        content = source.read_bytes()
        if len(content) > MAX_FLASH_BYTES:
            raise ValueError("MinerU flash mode accepts files up to 10 MB only")

        output_dir = Path(output_path) if output_path else self._generate_output_path(content)
        output_dir.mkdir(parents=True, exist_ok=True)

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

        self._request(file_url, method="PUT", data=content)

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
                "source": str(source),
                "task_id": task_id,
                "state": result.get("state"),
                "progress": result.get("extract_progress"),
            },
        )
        return output_dir

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


def main():
    ...


if __name__ == "__main__":
    main()
