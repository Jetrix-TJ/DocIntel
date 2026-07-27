from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class IntakeItem:
    document_id: str
    source_path: str
    sender_email: str | None = None
    email_id: str | None = None


class IntakeSource(Protocol):
    def items(self) -> Iterator[IntakeItem]: ...
