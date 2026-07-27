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
                yield from self._walk(path)
            else:
                # A missing or unreadable path is still yielded: the filter stage
                # skips it with a reason. Spec Stage 1 - nothing is discarded at
                # intake, and a path nobody looked at is not even counted.
                yield IntakeItem(_stable_id(path), path)

    @staticmethod
    def _walk(root: str) -> Iterator[IntakeItem]:
        """Walk a directory tree, deepest paths included.

        Recursion is deliberate. A flat listdir leaves a PDF one directory down
        completely invisible - not skipped, not dead-lettered, not counted in
        `intaken` - which is the one failure mode this pipeline refuses. os.walk
        also separates directories from files, so a *directory* named
        `archive.pdf` is walked into rather than mistaken for a document.
        """
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()  # deterministic traversal order
            for name in sorted(filenames):
                if name.lower().endswith(".pdf"):
                    yield IntakeItem(
                        _stable_id(os.path.join(dirpath, name)),
                        os.path.join(dirpath, name),
                    )
