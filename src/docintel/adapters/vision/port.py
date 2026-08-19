"""The vision-extraction port. Stage 5b talks to this, never to a vendor SDK.

**Why `source_path` is on the call and not just `pages`.** `PageText` is the
*text layer*, and on the two corpus documents that most need vision (Complete
Beverage, Federal Recycling) that layer is OCR output - which is exactly the
thing we do not trust. An adapter handed only `PageText` would be doing a text
call and calling it vision. So the port carries a pointer to the original bytes.

It is keyword-only and optional because a deterministic stand-in
(`FakeVision`) has no use for it, and because a caller that genuinely has no
file must be able to say so rather than invent a path.

**Why `field_hints` is on the call, not only on the adapter's constructor.**
An adapter is constructed once and shared across an entire run (`build_
pipeline`), while the hint text is a property of the DOCUMENT's persona -
different per vendor. A constructor-level default (`GeminiVision(field_hints=
...)`) still exists for a caller that only ever processes one vendor (a demo
script, a one-off), but Stage 5b's shared instance needs a hint set that
varies call to call, which only a per-call parameter can give it.
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
        field_hints: dict[str, str] | None = None,
    ) -> VisionResult: ...
