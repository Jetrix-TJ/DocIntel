"""Value types threaded through the pipeline.

The ExtractedFields / DerivedFields split is load-bearing. On 7 of the 10 corpus
documents a selector pointed straight at amount_payable would produce the right
answer, which makes the F1 bug invisible to casual testing. Separating the types
makes grammar rule V10 impossible to violate rather than merely forbidden.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

PageRole = Literal["primary", "supporting", "unknown"]
TextSource = Literal["native", "ocr"]
Disposition = Literal["processed", "skipped", "dead_letter"]
PersonaStatus = Literal["hit", "soft_miss", "hard_miss"]

# Fields that may only ever be computed by an adjust op, never read off a page.
DERIVED_ONLY: frozenset[str] = frozenset({
    "amount_payable",
    "payable_basis",
    "document_identity",
    "identity_basis",
    "carried_balance",
})

_LINE_TOLERANCE = 3.0  # points; words within this vertical distance share a line


def _reject_derived(name: str) -> None:
    if name in DERIVED_ONLY:
        raise ValueError(
            f"{name!r} is derived_only (grammar V10) and cannot be extracted; "
            "compute it with an adjust op and store it on DerivedFields"
        )


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class PageText:
    """Normalized page text. Identical shape whether it came from pdfplumber or OCR.

    This is the seam that makes OCR cheap (F2): grammar/executor never learns
    which source produced it.
    """

    page_number: int
    words: tuple[Word, ...]
    width: float
    height: float
    source: TextSource

    def __post_init__(self) -> None:
        if self.source not in ("native", "ocr"):
            raise ValueError(f"source must be 'native' or 'ocr', got {self.source!r}")

    def lines(self) -> list[list[Word]]:
        """Group words into visual lines, each sorted left to right."""
        out: list[list[Word]] = []
        for w in sorted(self.words, key=lambda w: (w.y0, w.x0)):
            if out and abs(out[-1][0].y0 - w.y0) <= _LINE_TOLERANCE:
                out[-1].append(w)
            else:
                out.append([w])
        for line in out:
            line.sort(key=lambda w: w.x0)
        return out

    @property
    def text(self) -> str:
        return "\n".join(" ".join(w.text for w in line) for line in self.lines())


@dataclass(frozen=True)
class PageMeta:
    page_number: int
    char_count: int
    image_count: int
    annot_count: int
    role: PageRole = "unknown"


@dataclass(frozen=True)
class ReferenceHit:
    value: str
    source_field: str
    page: int
    pattern_id: str


@dataclass
class ExtractedFields:
    """Values read off the page. Never holds a derived field.

    The backing dicts are private and exposed only as read-only mapping views,
    so `set()` is the single insertion path and no dict method can reach around
    it. Subclassing dict does not work here: CPython's setdefault and __ior__
    are C-level and bypass an overridden __setitem__.
    """

    _values: dict[str, Any] = field(default_factory=dict)
    _match_quality: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (*self._values, *self._match_quality):
            _reject_derived(name)

    @property
    def values(self) -> Mapping[str, Any]:
        return MappingProxyType(self._values)

    @property
    def match_quality(self) -> Mapping[str, float]:
        return MappingProxyType(self._match_quality)

    def set(self, name: str, value: Any, match_quality: float) -> None:
        _reject_derived(name)
        self._values[name] = value
        self._match_quality[name] = match_quality

    def get(self, name: str, default: Any = None) -> Any:
        return self._values.get(name, default)


@dataclass
class DerivedFields:
    """Values computed by adjust ops from extracted values."""

    values: dict[str, Any] = field(default_factory=dict)

    def set(self, name: str, value: Any) -> None:
        self.values[name] = value

    def get(self, name: str, default: Any = None) -> Any:
        return self.values.get(name, default)


@dataclass
class JobContext:
    # identity (s1)
    document_id: str
    source_path: str
    received_at: str = ""
    sender_email: str | None = None
    email_id: str | None = None
    possible_duplicate_of: str | None = None
    suspected_batch: bool = False

    # text (s2)
    pages: tuple[PageText, ...] = ()
    page_meta: tuple[PageMeta, ...] = ()
    text_source: str = "native"

    # classification (s3)
    doc_type: str | None = None
    tags: list[str] = field(default_factory=list)
    classification_confidence: float | None = None
    signal_that_fired: str | None = None

    # persona (s4)
    sender_fingerprint: str | None = None
    persona: Any | None = None
    persona_status: PersonaStatus | None = None
    extraction_rule_version: str | None = None

    # extraction (s5*)
    extracted: ExtractedFields = field(default_factory=ExtractedFields)
    derived: DerivedFields = field(default_factory=DerivedFields)
    reference_list: list[ReferenceHit] = field(default_factory=list)
    extraction_route: str | None = None

    # capture + gate (s6, s7)
    confidence: dict[str, float] = field(default_factory=dict)
    modifiers: list[str] = field(default_factory=list)
    lane: str | None = None
    review_flag: bool = False
    regen_flag: bool = False
    audit_sample: bool = False

    # emit (s8)
    disposition: Disposition = "processed"
    skip_reason: str | None = None
    emitted: bool = False
    events: list[str] = field(default_factory=list)

    def add_modifier(self, name: str) -> None:
        if name not in self.modifiers:
            self.modifiers.append(name)

    def add_tag(self, name: str) -> None:
        if name not in self.tags:
            self.tags.append(name)

    def log(self, message: str) -> None:
        self.events.append(message)


def new_context(document_id: str, source_path: str, **kwargs: Any) -> JobContext:
    return JobContext(document_id=document_id, source_path=source_path, **kwargs)
