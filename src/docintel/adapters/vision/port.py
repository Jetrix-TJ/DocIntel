"""The vision-extraction port. Stage 5b talks to this, never to a vendor SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from docintel.core.models import PageText


@dataclass(frozen=True)
class VisionResult:
    fields: dict[str, str] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    irregularities: list[str] = field(default_factory=list)


class VisionExtractor(Protocol):
    def extract(
        self, pages: tuple[PageText, ...], field_names: list[str]
    ) -> VisionResult: ...
