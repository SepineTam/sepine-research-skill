#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# Copyright (C) 2026 - Present Song Tan, Inc. All Rights Reserved
#
# @Author : Song Tan
# @Email  : sepinetam@gmail.com
# @File   : pdf2md/scripts/convert.py

from __future__ import annotations

import hashlib
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


class MinerU(ConvertBase):
    ...


class SoMark(ConvertBase):
    ...


def main():
    ...


if __name__ == "__main__":
    main()
