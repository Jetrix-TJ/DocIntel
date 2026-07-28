"""Deterministic vision stand-in. Proves wiring, nothing else.

Kept alongside `CassetteVision` rather than replaced by it, because the two answer
different questions. A cassette proves the pipeline handles what a model *actually
said*; a fake lets a unit test state the one value it is about. Neither substitutes
for the other, and a test that needs "vision returns exactly this" should not have
to author a cassette to say so.

`source_path` is accepted and ignored: a canned answer has no use for the bytes,
but the port passes it, and a stand-in that rejected it would fail differently
from the real thing.
"""

from __future__ import annotations

from docintel.adapters.vision.port import VisionResult
from docintel.core.models import PageText


class FakeVision:
    def __init__(
        self,
        canned: dict[str, str] | None = None,
        irregularities: list[str] | None = None,
    ) -> None:
        self.canned = canned or {}
        self.irregularities = irregularities or []
        self.calls: list[list[str]] = []
        self.sources: list[str | None] = []

    def extract(
        self,
        pages: tuple[PageText, ...],
        field_names: list[str],
        *,
        source_path: str | None = None,
    ) -> VisionResult:
        self.calls.append(list(field_names))
        self.sources.append(source_path)
        fields = {k: v for k, v in self.canned.items() if k in field_names}
        return VisionResult(
            fields=fields,
            confidence={k: 0.50 for k in fields},
            irregularities=list(self.irregularities),
        )
