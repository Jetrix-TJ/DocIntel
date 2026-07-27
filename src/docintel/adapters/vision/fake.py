"""Deterministic vision stand-in. Carries the loop until an API key exists."""

from __future__ import annotations

from docintel.adapters.vision.port import VisionResult
from docintel.core.models import PageText


class FakeVision:
    def __init__(self, canned: dict[str, str] | None = None) -> None:
        self.canned = canned or {}
        self.calls: list[list[str]] = []

    def extract(
        self, pages: tuple[PageText, ...], field_names: list[str]
    ) -> VisionResult:
        self.calls.append(list(field_names))
        fields = {k: v for k, v in self.canned.items() if k in field_names}
        return VisionResult(
            fields=fields,
            confidence={k: 0.50 for k in fields},
            irregularities=[],
        )
