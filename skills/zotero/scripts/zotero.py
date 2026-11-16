#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# Copyright (C) 2026 - Present Song Tan, Inc. All Rights Reserved
#
# @Author : Song Tan
# @Email  : sepinetam@gmail.com
# @File   : zotero-search/scripts/zotero.py

import os
import sys
import platform
import sqlite3
import re
import json
import urllib.error
import urllib.parse
import urllib.request

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path


class ConnectMode(Enum):
    read_only = "ro"  # 安全角度考虑暂时只支持 read only


class CitationFormat(Enum):
    bibtex = "bibtex"


@dataclass
class Item:
    key: str  # 文章在 Zotero 里的唯一身份识别码，Zotero 里的 8 位字母数字
    title: str
    item_type: str = ""
    shortTitle: str = ""
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    date: str = ""
    year: int = 0
    language: str = ""
    publication: str = ""
    doi: str = ""
    isbn: str = ""
    url: str = ""
    citation_key: str = ""

    has_full_text: bool = False
    has_notes: bool = False
    has_attachment: bool = False

    collections: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def bibtex(self) -> str:
        # itemType → BibTeX 条目类型
        entry_types = {
            "journalArticle": "article",
            "magazineArticle": "article",
            "newspaperArticle": "article",
            "book": "book",
            "bookSection": "incollection",
            "conferencePaper": "inproceedings",
            "thesis": "phdthesis",
            "report": "techreport",
            "manuscript": "unpublished",
        }
        entry_type = entry_types.get(self.item_type, "misc")

        # BibTeX 作者格式：Last, First and Last, First
        authors = []
        for name in self.authors:
            first, _, last = name.rpartition(" ")
            authors.append(f"{last}, {first}" if first else name)

        # citekey：优先用 extra 里的 Citation Key，否则第一作者姓 + 年份
        first_author = self.authors[0].rpartition(" ")[2] if self.authors else ""
        generated_key = re.sub(r"[^0-9a-zA-Z]", "", first_author).lower()
        citekey = self.citation_key or f"{generated_key or 'zotero'}{self.year or ''}"

        fields: list[tuple[str, str]] = []

        def add(name: str, value: str | int | None) -> None:
            if value:
                escaped = str(value).replace("&", r"\&").replace("%", r"\%")
                fields.append((name, escaped))

        if authors:
            add("author", " and ".join(authors))
        add("title", self.title)
        add("year", self.year)

        # publication 在不同条目类型下落到不同 BibTeX 字段
        if self.item_type in {"journalArticle", "magazineArticle", "newspaperArticle"}:
            add("journal", self.publication)
        elif self.item_type in {"conferencePaper", "bookSection"}:
            add("booktitle", self.publication)
        elif self.item_type == "book":
            add("publisher", self.publication)
        elif self.item_type == "thesis":
            add("school", self.publication)
        elif self.item_type == "report":
            add("institution", self.publication)
        else:
            add("howpublished", self.publication)

        add("doi", self.doi)
        add("isbn", self.isbn)
        add("url", self.url)
        add("keywords", ", ".join(self.tags))

        body = "\n".join(f"  {name} = {{{value}}}," for name, value in fields)
        return f"@{entry_type}{{{citekey},\n{body}\n}}"


@dataclass
class Attachment:
    key: str  # 附件自身的 key，对应 storage 下的目录名
    path: Path | None = None  # 解析后的本地文件路径，链接网址类型为 None
    filename: str = ""
    content_type: str = ""
    link_mode: int = 0
    url: str = ""
    has_full_text: bool = False

    @property
    def locator(self) -> str | None:
        """本地文件路径或链接网址，即全文的实际位置。"""
        if self.path is not None:
            return str(self.path)
        return self.url or None


class ZoteroAPI:
    DEFAULT_API_BASE = "http://127.0.0.1:23119"
    API_HEADERS = {"Zotero-API-Version": "3"}

    def __init__(
        self,
        api_base: str = DEFAULT_API_BASE,
        timeout: float = 5.0,
    ):
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        params: dict[str, str | int | None] | None = None,
        data: dict | list | str | None = None,
    ) -> tuple[int, dict[str, str], str]:
        url = self.api_base + path
        if params:
            query = urllib.parse.urlencode(
                {key: value for key, value in params.items() if value is not None}
            )
            url = f"{url}?{query}"

        headers = dict(self.API_HEADERS)
        body: bytes | None = None
        if data is not None:
            if isinstance(data, (dict, list)):
                body = json.dumps(data).encode("utf-8")
                headers.setdefault("Content-Type", "application/json")
            else:
                body = str(data).encode("utf-8")

        request = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return (
                    response.status,
                    {key.lower(): value for key, value in response.headers.items()},
                    response.read().decode("utf-8", errors="replace"),
                )
        except urllib.error.HTTPError as exc:
            return (
                exc.code,
                {key.lower(): value for key, value in exc.headers.items()},
                exc.read().decode("utf-8", errors="replace"),
            )
        except urllib.error.URLError as exc:
            raise ConnectionError(
                f"Zotero local API unreachable at {self.api_base}: {exc.reason}"
            ) from exc
        except OSError as exc:
            raise ConnectionError(
                f"Zotero local API unreachable at {self.api_base}: {exc}"
            ) from exc

    def health(self) -> str:
        try:
            status, headers, _ = self._request("/api/")
        except ConnectionError as exc:
            return str(exc)

        version = headers.get("x-zotero-version", "unknown")
        if not 200 <= status < 300:
            return f"error: HTTP {status} (Zotero {version})"
        return f"ok (Zotero {version})"


class Zotero:
    def __init__(
        self, 
        db_path: Path | None = None,
        conn_mode: ConnectMode = ConnectMode.read_only
    ):
        self.db_path: Path = db_path or self._get_zotero_db_path()

        if self.db_path is None:
            raise ValueError("Zotero Database Path not Found")
        if not self.db_path.is_file():
            raise ValueError("Please check whether your Zotero database path is correct")

        self.conn_mode = conn_mode

    def get_detail(self, item: Item) -> dict:
        return item.to_dict()

    def search(
        self, 
        keywords: list[str],
        # 后续会有更多的参数可以加
    ) -> list[Item]:
        pass

    def cite(
        self,
        key: str,
        format: CitationFormat | str = CitationFormat.bibtex
    ) -> str:
        if not isinstance(format, CitationFormat):
            try:
                format = CitationFormat(format)
            except ValueError:
                supported = ", ".join(f.value for f in CitationFormat)
                raise ValueError(
                    f"Unsupported citation format: {format!r}; supported: {supported}"
                ) from None

        item = self.get_item(key)

        if format is CitationFormat.bibtex:
            return item.bibtex
        raise ValueError(f"Unsupported citation format: {format!r}")

    def get_item(self, key: str) -> Item:
        conn = self.connect()

        # 按 key 定位条目，排除已删除；多个库同 key 时优先个人库（libraryID=1）
        row = conn.execute(
            """
            SELECT i.itemID, i.key, it.typeName
            FROM items i
            JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
            LEFT JOIN deletedItems del ON del.itemID = i.itemID
            WHERE i.key = ? AND del.itemID IS NULL
            ORDER BY (i.libraryID = 1) DESC
            LIMIT 1
            """,
            (key,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Zotero item not found: {key}")

        item_id, item_key, item_type = row

        fields = {
            name: value
            for name, value in conn.execute(
                """
                SELECT f.fieldName, v.value
                FROM itemData d
                JOIN fieldsCombined f ON f.fieldID = d.fieldID
                JOIN itemDataValues v ON v.valueID = d.valueID
                WHERE d.itemID = ?
                """,
                (item_id,),
            )
        }

        authors = []
        for first, last, mode in conn.execute(
            """
            SELECT c.firstName, c.lastName, c.fieldMode
            FROM itemCreators ic
            JOIN creators c ON c.creatorID = ic.creatorID
            JOIN creatorTypes ct ON ct.creatorTypeID = ic.creatorTypeID
            WHERE ic.itemID = ? AND ct.creatorType = 'author'
            ORDER BY ic.orderIndex
            """,
            (item_id,),
        ):
            name = last if mode == 1 else " ".join(p for p in (first, last) if p)
            if name:
                authors.append(name)

        collections = [
            name
            for (name,) in conn.execute(
                """
                SELECT c.collectionName
                FROM collectionItems ci
                JOIN collections c ON c.collectionID = ci.collectionID
                WHERE ci.itemID = ?
                ORDER BY c.collectionName
                """,
                (item_id,),
            )
        ]

        tags = [
            name
            for (name,) in conn.execute(
                """
                SELECT t.name
                FROM itemTags it
                JOIN tags t ON t.tagID = it.tagID
                WHERE it.itemID = ?
                ORDER BY t.name
                """,
                (item_id,),
            )
        ]

        has_attachment, has_notes, has_full_text = conn.execute(
            """
            SELECT
                EXISTS(SELECT 1 FROM itemAttachments WHERE parentItemID = ?),
                EXISTS(SELECT 1 FROM itemNotes WHERE parentItemID = ?),
                EXISTS(
                    SELECT 1 FROM itemAttachments ia
                    JOIN fulltextItems ft ON ft.itemID = ia.itemID
                    WHERE ia.parentItemID = ?
                )
            """,
            (item_id, item_id, item_id),
        ).fetchone()

        date = fields.get("date", "")
        year_match = re.search(r"\b(\d{4})\b", date)
        citation_match = re.search(
            r"^Citation Key:\s*(.+)$", fields.get("extra", ""), re.MULTILINE
        )
        publication = next(
            (
                fields[name]
                for name in (
                    "publicationTitle",
                    "proceedingsTitle",
                    "bookTitle",
                    "publisher",
                    "university",
                )
                if fields.get(name)
            ),
            "",
        )

        return Item(
            key=item_key,
            title=fields.get("title", ""),
            item_type=item_type,
            shortTitle=fields.get("shortTitle", ""),
            authors=authors,
            abstract=fields.get("abstractNote", ""),
            date=date,
            year=int(year_match.group(1)) if year_match else 0,
            language=fields.get("language", ""),
            publication=publication,
            doi=fields.get("DOI", ""),
            isbn=fields.get("ISBN", ""),
            url=fields.get("url", ""),
            citation_key=citation_match.group(1).strip() if citation_match else "",
            has_full_text=bool(has_full_text),
            has_notes=bool(has_notes),
            has_attachment=bool(has_attachment),
            collections=collections,
            tags=tags,
        )

    def get_notes(self, key: str) -> list[str]:
        # 取该条目的笔记正文（HTML），跳过已删除的笔记和已删除的父条目
        conn = self.connect()
        return [
            note
            for (note,) in conn.execute(
                """
                SELECT n.note
                FROM itemNotes n
                JOIN items i ON i.itemID = n.parentItemID
                LEFT JOIN deletedItems del_note ON del_note.itemID = n.itemID
                LEFT JOIN deletedItems del_item ON del_item.itemID = i.itemID
                WHERE i.key = ? AND del_note.itemID IS NULL AND del_item.itemID IS NULL
                ORDER BY n.itemID
                """,
                (key,),
            )
        ]

    def get_attachments(self, key: str) -> list[Attachment]:
        # 取该条目的附件列表；storage: 前缀展开为数据目录下的真实路径
        conn = self.connect()
        rows = conn.execute(
            """
            SELECT
                i.key,
                ia.linkMode,
                ia.contentType,
                ia.path,
                (
                    SELECT v.value
                    FROM itemData d
                    JOIN fieldsCombined f ON f.fieldID = d.fieldID
                    JOIN itemDataValues v ON v.valueID = d.valueID
                    WHERE d.itemID = ia.itemID AND f.fieldName = 'url'
                    LIMIT 1
                ) AS url,
                EXISTS(
                    SELECT 1 FROM fulltextItems ft WHERE ft.itemID = ia.itemID
                ) AS has_full_text
            FROM itemAttachments ia
            JOIN items i ON i.itemID = ia.itemID
            JOIN items parent ON parent.itemID = ia.parentItemID
            LEFT JOIN deletedItems del ON del.itemID = i.itemID
            LEFT JOIN deletedItems del_parent ON del_parent.itemID = parent.itemID
            WHERE parent.key = ? AND del.itemID IS NULL AND del_parent.itemID IS NULL
            ORDER BY ia.itemID
            """,
            (key,),
        ).fetchall()

        attachments = []
        for attachment_key, link_mode, content_type, raw_path, url, has_full_text in rows:
            raw_path = raw_path or ""
            filename = ""
            path: Path | None = None

            if raw_path.startswith("storage:"):
                # 导入型附件：storage:<文件名>，真实位置在 storage/<附件key>/ 下
                filename = raw_path.removeprefix("storage:")
                path = self.db_path.parent / "storage" / attachment_key / filename
            elif link_mode == 3:
                # 链接网址：path 列存的就是 URL
                url = raw_path or url or ""
            elif raw_path:
                # 链接的文件：原样是磁盘路径
                path = Path(raw_path).expanduser()
                filename = path.name

            attachments.append(
                Attachment(
                    key=attachment_key,
                    path=path,
                    filename=filename,
                    content_type=content_type or "",
                    link_mode=link_mode or 0,
                    url=url or "",
                    has_full_text=bool(has_full_text),
                )
            )
        return attachments

    def get_fulltext(self, key: str) -> str | None:
        # 返回全文的实际位置：优先 PDF 文件路径，其次任意附件的路径或网址
        attachments = self.get_attachments(key)
        for attachment in attachments:
            if attachment.content_type == "application/pdf" and attachment.path is not None:
                return attachment.locator
        for attachment in attachments:
            if attachment.locator is not None:
                return attachment.locator
        return None

    def _get_zotero_db_path(self) -> Path:
        # 先从环境变量里来拿，如不OK就从默认的来拿
        db_path = os.getenv("ZOTERO_DB_PATH")
        if db_path:
            # 检查这个玩意是否是对的
            db_path = Path(db_path).expanduser()
            if db_path.is_file():
                return db_path

        return self._get_default_db_path()

    def _get_default_db_path(self) -> Path:
        if platform.system == "Darwin":
            return Path.home() / "Zotero" / "zotero.sqlite"
        elif platform.system == "Windows":
            return Path(os.environ.get("USERPROFILE") or Path.home()) / "Zotero" / "zotero.sqlite"
        else:
            raise SystemError("Unknown or unsupported system")

    def connect(self):
        if getattr(self, "_conn", None) is None:
            self._conn = sqlite3.connect(
                f"file:{self.db_path}?mode={self.conn_mode}", 
                uri=True
            )
        return self._conn

    def disconnect(self):
        conn = getattr(self, "_conn", None)
        if conn is not None:
            conn.close()
            self._conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.disconnect()

    def __del__(self):
        self.disconnect()


def main():
    ...


if __name__ == "__main__":
    main()
