"""Filesystem intake: the 'pass any accepted document' path.

An IMAP source slots in behind the same port later without the pipeline changing.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator

from docintel.adapters.intake.port import IntakeItem
from docintel.extract.convert import ACCEPTED_SUFFIXES


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

        Recursion is deliberate. A document one directory down left invisible -
        not skipped, not dead-lettered, not counted in `intaken` - is the one
        failure mode this pipeline refuses. os.walk also separates directories
        from files, so a *directory* named `archive.pdf` is walked into rather
        than mistaken for a document.

        Filtered against `convert.ACCEPTED_SUFFIXES`, the same constant Stage 2
        checks - a suffix this walk doesn't yield never reaches Stage 2 at all,
        so the two lists must stay identical, not just similar.
        """
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()  # deterministic traversal order
            for name in sorted(filenames):
                if os.path.splitext(name)[1].lower() in ACCEPTED_SUFFIXES:
                    yield IntakeItem(
                        _stable_id(os.path.join(dirpath, name)),
                        os.path.join(dirpath, name),
                    )
