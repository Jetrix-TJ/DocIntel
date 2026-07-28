"""The vision-extraction port. Stage 5b talks to this, never to a vendor SDK.

**Why `source_path` is on the call and not just `pages`.** `PageText` is the
*text layer*, and on the two corpus documents that most need vision (Complete
Beverage, Federal Recycling) that layer is OCR output - which is exactly the
thing we do not trust. An adapter handed only `PageText` would be doing a text
call and calling it vision. So the port carries a pointer to the original bytes.

It is keyword-only and optional because a deterministic stand-in
(`FakeVision`) has no use for it, and because a caller that genuinely has no
file must be able to say so rather than invent a path.
"""

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
        self,
        pages: tuple[PageText, ...],
        field_names: list[str],
        *,
        source_path: str | None = None,
    ) -> VisionResult: ...
