#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# Copyright (C) 2026 - Present Song Tan, Inc. All Rights Reserved
#
# @Author : Song Tan
# @Email  : sepinetam@gmail.com
# @File   : zotero-search/scripts/zotero.py

"""Zotero 本地数据库与本地 HTTP API 的只读客户端。

Zotero 直接读取 zotero.sqlite，Zotero 无需运行；
ZoteroAPI 访问 Zotero Desktop 的本地 HTTP 服务，需要 Zotero 运行并开启本地 API。
"""

from __future__ import annotations  # 避免 3.9 及以下的爆炸🤯，我的 Mac 默认的 python 就是 3.9

import argparse
import inspect
import os
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
                escaped = (
                    str(value)
                    .replace("&", r"\&")
                    .replace("%", r"\%")
                    .replace("#", r"\#")
                    .replace("_", r"\_")
                )
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


# TODO: 补全本地 API 的 search / cite / get_details / get_notes /
# get_attachments / get_fulltext 方法。
# 原因：Zotero 运行时会对 zotero.sqlite 持有独占锁，外部只读连接会报
# "database is locked"；此时应改走本地 API，DB 客户端只用于 Zotero 关闭时。
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
        self.db_path: Path = Path(db_path).expanduser() if db_path else self._get_zotero_db_path()

        if not self.db_path.is_file():
            raise ValueError("Please check whether your Zotero database path is correct")

        self.conn_mode = conn_mode

    def get_detail(self, item: Item) -> dict:
        """Serialize an item to a plain dictionary.

        Args:
            item: The item to serialize.

        Returns:
            A dict containing every field of the item.
        """
        return item.to_dict()

    def search(
        self,
        keywords: list[str] | str,
        *,
        year_from: int | None = None,
        year_to: int | None = None,
        limit: int = 25,
        offset: int = 0,
        in_publication: str | None = None,  # 来指定某本期刊或书
        with_tag: bool = True,  # tag，等价于常规理解的关键词
        with_notes: bool = True,
    ) -> list[Item]:
        """Search Zotero items by keywords.

        Each keyword must match at least one of: metadata fields (title, short
        title, abstract, publication), a creator name, or—when enabled—tags
        and notes. Multiple keywords are combined with AND.

        Args:
            keywords: A keyword or a list of keywords to search for.
            year_from: Inclusive lower bound for the publication year.
            year_to: Inclusive upper bound for the publication year.
            limit: Maximum number of items to return.
            offset: Number of matched items to skip.
            in_publication: Restrict to a journal, proceedings or book name.
            with_tag: Also match keywords against tags.
            with_notes: Also match keywords against note content.

        Returns:
            Matching items sorted by modification time, newest first.
            Items without a parseable year are skipped when a year bound is set.
        """
        if limit < 0 or offset < 0:
            raise ValueError("limit and offset must be non-negative")

        if isinstance(keywords, str):
            keywords = [keywords]
        terms = [term.strip() for term in keywords if term and term.strip()]

        def like(term: str) -> str:
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            return f"%{escaped}%"

        conditions = [
            "del.itemID IS NULL",
            "it.typeName NOT IN ('attachment', 'note', 'annotation')",
        ]
        params: list[str] = []

        # 限定出版物：期刊/会议用对应字段，图书的题名存在 title 里
        if in_publication:
            conditions.append(
                """EXISTS (
                    SELECT 1
                    FROM itemData d
                    JOIN fieldsCombined f ON f.fieldID = d.fieldID
                    JOIN itemDataValues v ON v.valueID = d.valueID
                    WHERE d.itemID = i.itemID
                      AND (
                          f.fieldName IN ('publicationTitle', 'bookTitle', 'proceedingsTitle')
                          OR (f.fieldName = 'title' AND it.typeName = 'book')
                      )
                      AND v.value LIKE ? ESCAPE '\\'
                )"""
            )
            params.append(like(in_publication))

        # 每个关键词都必须命中：元数据、作者，以及可选的 tag、笔记
        for term in terms:
            pattern = like(term)
            branches = [
                """EXISTS (
                    SELECT 1
                    FROM itemData d
                    JOIN fieldsCombined f ON f.fieldID = d.fieldID
                    JOIN itemDataValues v ON v.valueID = d.valueID
                    WHERE d.itemID = i.itemID
                      AND f.fieldName IN (
                          'title', 'shortTitle', 'abstractNote',
                          'publicationTitle', 'bookTitle', 'proceedingsTitle',
                          'publisher', 'university'
                      )
                      AND v.value LIKE ? ESCAPE '\\'
                )""",
                """EXISTS (
                    SELECT 1
                    FROM itemCreators ic
                    JOIN creators c ON c.creatorID = ic.creatorID
                    WHERE ic.itemID = i.itemID
                      AND (c.firstName || ' ' || c.lastName) LIKE ? ESCAPE '\\'
                )""",
            ]
            term_params = [pattern, pattern]

            if with_tag:
                branches.append(
                    """EXISTS (
                        SELECT 1
                        FROM itemTags it2
                        JOIN tags t ON t.tagID = it2.tagID
                        WHERE it2.itemID = i.itemID AND t.name LIKE ? ESCAPE '\\'
                    )"""
                )
                term_params.append(pattern)

            if with_notes:
                branches.append(
                    """EXISTS (
                        SELECT 1
                        FROM itemNotes n
                        WHERE n.parentItemID = i.itemID
                          AND n.note LIKE ? ESCAPE '\\'
                          AND n.itemID NOT IN (SELECT itemID FROM deletedItems)
                    )"""
                )
                term_params.append(pattern)

            conditions.append("(" + "\n                OR ".join(branches) + ")")
            params.extend(term_params)

        sql = f"""
            SELECT i.key,
                   (
                       SELECT v.value
                       FROM itemData d
                       JOIN fieldsCombined f ON f.fieldID = d.fieldID
                       JOIN itemDataValues v ON v.valueID = d.valueID
                       WHERE d.itemID = i.itemID AND f.fieldName = 'date'
                       LIMIT 1
                   ) AS date
            FROM items i
            JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
            LEFT JOIN deletedItems del ON del.itemID = i.itemID
            WHERE {' AND '.join(conditions)}
            ORDER BY i.dateModified DESC
        """
        rows = self.connect().execute(sql, params).fetchall()

        # date 是自由文本，年份在 Python 侧解析更可靠
        if year_from is not None or year_to is not None:
            def in_year_range(date_text: str | None) -> bool:
                match = re.search(r"\b(\d{4})\b", date_text or "")
                if match is None:
                    return False
                year = int(match.group(1))
                if year_from is not None and year < year_from:
                    return False
                if year_to is not None and year > year_to:
                    return False
                return True

            rows = [row for row in rows if in_year_range(row[1])]

        return [self.get_item(key) for (key, _) in rows[offset:offset + limit]]

    def cite(
        self,
        key: str,
        format: CitationFormat | str = CitationFormat.bibtex
    ) -> str:
        """Render a citation for an item.

        Args:
            key: The Zotero item key.
            format: Output format, either a CitationFormat or its string value.

        Returns:
            A single BibTeX entry.

        Raises:
            KeyError: If no item matches the key.
            ValueError: If the format is not supported.
        """
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
        """Return the note contents of an item.

        Notes are stored as HTML and returned verbatim. Deleted notes and
        notes whose parent item is deleted are skipped.

        Args:
            key: The Zotero item key.

        Returns:
            Note HTML strings in insertion order.
        """
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
        """Return the attachments of an item.

        Imported files have their ``storage:`` prefix expanded to an absolute
        path under ``<data dir>/storage/<attachment key>/``. Linked files keep
        their on-disk path. Linked URLs are returned in ``url`` with ``path``
        set to None. Deleted attachments and attachments of deleted items are
        skipped.

        Args:
            key: The parent item key.

        Returns:
            Attachment objects in insertion order.
        """
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
        """Return the locator of an item's full text.

        Prefers the path of a local PDF attachment; otherwise returns the
        first attachment path or URL. This returns where the text lives, not
        the extracted text itself.

        Args:
            key: The parent item key.

        Returns:
            A filesystem path or URL, or None when no attachment is usable.
        """
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
        if platform.system() == "Darwin":
            return Path.home() / "Zotero" / "zotero.sqlite"
        elif platform.system() == "Windows":
            return Path(os.environ.get("USERPROFILE") or Path.home()) / "Zotero" / "zotero.sqlite"
        else:
            raise SystemError("Unknown or unsupported system")

    def connect(self):
        if getattr(self, "_conn", None) is None:
            self._conn = sqlite3.connect(
                f"file:{self.db_path}?mode={self.conn_mode.value}",
                uri=True
            )
            self._conn.execute("PRAGMA busy_timeout = 5000")
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


def _attachment_to_dict(attachment: Attachment) -> dict:
    """Convert an attachment to a JSON-serialisable dict."""
    return {
        "key": attachment.key,
        "path": str(attachment.path) if attachment.path is not None else None,
        "filename": attachment.filename,
        "content_type": attachment.content_type,
        "link_mode": attachment.link_mode,
        "url": attachment.url,
        "has_full_text": attachment.has_full_text,
    }


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def cmd_search(args: argparse.Namespace) -> None:
    with Zotero() as zotero:
        items = zotero.search(
            args.keywords,
            year_from=args.year_from,
            year_to=args.year_to,
            limit=args.limit,
            offset=args.offset,
            in_publication=args.in_publication,
            with_tag=args.with_tag,
            with_notes=args.with_notes,
        )
    _print_json([item.to_dict() for item in items])


def cmd_cite(args: argparse.Namespace) -> None:
    with Zotero() as zotero:
        print(zotero.cite(args.key, args.format))


def cmd_get_details(args: argparse.Namespace) -> None:
    with Zotero() as zotero:
        item = zotero.get_item(args.key)
        details = zotero.get_detail(item)
    _print_json(details)


def cmd_get_notes(args: argparse.Namespace) -> None:
    with Zotero() as zotero:
        notes = zotero.get_notes(args.key)
    _print_json(notes)


def cmd_get_attachments(args: argparse.Namespace) -> None:
    with Zotero() as zotero:
        attachments = zotero.get_attachments(args.key)
    _print_json([_attachment_to_dict(attachment) for attachment in attachments])


def cmd_get_fulltext(args: argparse.Namespace) -> None:
    with Zotero() as zotero:
        locator = zotero.get_fulltext(args.key)
    _print_json(locator)


def handle_help(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Show help for a command.

    Without --docstring this behaves exactly like `<command> --help`. With
    --docstring it prints the docstring of the Zotero method behind the
    command.
    """
    if args.topic is None:
        parser.print_help()
        return

    if args.topic not in DOCSTRING_TARGETS:
        parser.error(f"unknown command: {args.topic}")

    if args.docstring:
        target = DOCSTRING_TARGETS[args.topic]
        print(inspect.getdoc(target) or f"No docstring for {args.topic}")
        return

    parser.parse_args([args.topic, "--help"])


DOCSTRING_TARGETS = {
    "search": Zotero.search,
    "cite": Zotero.cite,
    "get_details": Zotero.get_detail,
    "get_notes": Zotero.get_notes,
    "get_attachments": Zotero.get_attachments,
    "get_fulltext": Zotero.get_fulltext,
    "help": handle_help,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zotero.py",
        description="Query a local Zotero library without the GUI.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    search = subcommands.add_parser("search", help="Search items by keywords")
    search.add_argument("keywords", nargs="+", help="Keywords, combined with AND")
    search.add_argument(
        "--year-from", type=int, dest="year_from",
        help="Inclusive lower bound for the publication year",
    )
    search.add_argument(
        "--year-to", type=int, dest="year_to",
        help="Inclusive upper bound for the publication year",
    )
    search.add_argument("--limit", type=int, default=25)
    search.add_argument("--offset", type=int, default=0)
    search.add_argument(
        "--in-publication", dest="in_publication",
        help="Restrict to a journal, proceedings or book name",
    )
    search.add_argument(
        "--no-tag", action="store_false", dest="with_tag",
        help="Do not match keywords against tags",
    )
    search.add_argument(
        "--no-notes", action="store_false", dest="with_notes",
        help="Do not match keywords against notes",
    )
    search.set_defaults(handler=cmd_search)

    cite = subcommands.add_parser("cite", help="Render a citation for an item")
    cite.add_argument("key")
    cite.add_argument("--format", default="bibtex")
    cite.set_defaults(handler=cmd_cite)

    details = subcommands.add_parser("get_details", help="Show all fields of an item")
    details.add_argument("key")
    details.set_defaults(handler=cmd_get_details)

    notes = subcommands.add_parser("get_notes", help="Show the notes of an item")
    notes.add_argument("key")
    notes.set_defaults(handler=cmd_get_notes)

    attachments = subcommands.add_parser(
        "get_attachments", help="List the attachments of an item"
    )
    attachments.add_argument("key")
    attachments.set_defaults(handler=cmd_get_attachments)

    fulltext = subcommands.add_parser(
        "get_fulltext", help="Locate the full text of an item"
    )
    fulltext.add_argument("key")
    fulltext.set_defaults(handler=cmd_get_fulltext)

    help_command = subcommands.add_parser("help", help="Show help for a command")
    help_command.add_argument(
        "topic", nargs="?", metavar="command", help="Command to describe"
    )
    help_command.add_argument(
        "--docstring",
        action="store_true",
        help="Print the docstring of the Zotero method instead of CLI help",
    )
    help_command.set_defaults(handler=None)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "help":
        handle_help(parser, args)
        return

    args.handler(args)


if __name__ == "__main__":
    main()
