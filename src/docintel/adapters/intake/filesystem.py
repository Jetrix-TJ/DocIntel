"""Filesystem intake: the 'pass any PDF' path.

An IMAP source slots in behind the same port later without the pipeline changing.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator

from docintel.adapters.intake.port import IntakeItem


def _stable_id(path: str) -> str:
    try:
        size = os.path.getsize(path)
    except OSError:
        size = -1
    key = f"{os.path.abspath(path)}|{size}"
    return "fs-" + hashlib.sha256(key.encode()).hexdigest()[:16]


class FilesystemIntake:
    def __init__(self, paths: list[str]) -> None:
        self.paths = paths

    def items(self) -> Iterator[IntakeItem]:
        for path in self.paths:
            if os.path.isdir(path):
                for name in sorted(os.listdir(path)):
                    if name.lower().endswith(".pdf"):
                        full = os.path.join(path, name)
                        yield IntakeItem(_stable_id(full), full)
            else:
                yield IntakeItem(_stable_id(path), path)
