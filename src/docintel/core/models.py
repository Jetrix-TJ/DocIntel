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

from docintel.core.geometry import DEFAULT_TOLERANCE, group_lines

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
    # Computed once, at construction, by `extract/pdf.py` / `extract/ocr.py`
    # (core.geometry.line_tolerance) — never recomputed by `lines()`, which is
    # called 21 times across the grammar, several inside loops. The default
    # covers the many call sites elsewhere (tests, `executor.py`'s scanline
    # wrapper) that build a `PageText` without caring about line geometry.
    line_tolerance: float = DEFAULT_TOLERANCE

    def __post_init__(self) -> None:
        if self.source not in ("native", "ocr"):
            raise ValueError(f"source must be 'native' or 'ocr', got {self.source!r}")

    def lines(self) -> list[list[Word]]:
        """Group words into visual lines, each sorted left to right."""
        return group_lines(self.words, self.line_tolerance)

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
    # What format `source_path` actually arrived as - "pdf" | "image" | "docx"
    # | "xlsx". Set by Stage 2 from the file's suffix. Exists so later stages
    # (Stage 5b's vision call, in particular) can tell "this is a raster with
    # no PDF wrapper" from "this is already a PDF" without re-deriving it from
    # a path extension - and so a raster image is never routed through a PDF
    # conversion it doesn't need for OCR, annotation detection, or Gemini
    # (which understands JPEG/PNG natively). Defaults to "pdf" so every
    # existing caller that never sets it keeps behaving exactly as before.
    source_format: str = "pdf"
    # The PDF Stage 2 actually read, when it differs from `source_path` - set
    # only when a non-PDF input (an image, a DOCX/XLSX) was converted at
    # intake (`extract.convert`). `source_path` is deliberately left alone:
    # `crosscheck_filename` (grammar/ops/crosscheck.py) reads its BASENAME to
    # compare an amount embedded in the original filename against the printed
    # total, and a converted file's throwaway temp name would silently break
    # that. Any stage that needs to open the document's actual bytes from
    # disk (Stage 5b's vision call) should read `ctx.readable_path or
    # ctx.source_path` rather than `source_path` alone.
    readable_path: str | None = None
    # `tempfile.mkdtemp()` directories created converting a non-PDF input
    # (`extract.convert`) that must outlive Stage 2 itself - Stage 5b's vision
    # call may still need to read `readable_path` from disk. Never read by any
    # stage; the Runner is the sole consumer, removing every entry once this
    # document's whole run (success, dead-letter, or emit-failure alike) is
    # over. Internal bookkeeping only - never surfaces in the emitted record.
    temp_dirs: list[str] = field(default_factory=list)

    # classification (s3)
    # The domain pack that claimed this document, resolved from the bill-to on
    # the page. `None` is a real answer: an invoice addressed to somebody else is
    # processed generically and tagged, never forced into whichever pack is first.
    pack: Any | None = None
    doc_type: str | None = None
    tags: list[str] = field(default_factory=list)
    classification_confidence: float | None = None
    signal_that_fired: str | None = None

    # persona (s4)
    sender_fingerprint: str | None = None
    persona: Any | None = None
    persona_status: PersonaStatus | None = None
    extraction_rule_version: str | None = None

    # processing profile (s4b). What downstream handling this document's
    # persona asks for, beyond extraction itself - resolved once, right after
    # persona lookup, rather than left implicit for a human to remember to run
    # a follow-up command. Absence of a persona (`hard_miss`) or absence of the
    # key on a persona both mean the same thing: no follow-up is owed.
    #   reconciliation: "none" | "auto" - match this invoice against contracts
    #     on file once it's processed.
    #   export: [] | list of registered layout names (e.g. ["excel"]) - render
    #     this record into that format once it's processed.
    processing_profile: dict[str, Any] = field(
        default_factory=lambda: {"reconciliation": "none", "export": []}
    )

    # extraction (s5*)
    extracted: ExtractedFields = field(default_factory=ExtractedFields)
    derived: DerivedFields = field(default_factory=DerivedFields)
    reference_list: list[ReferenceHit] = field(default_factory=list)
    extraction_route: str | None = None

    # structured extraction (s5*). Row groups are keyed by the persona's
    # `row_group` name; `build_record` lifts line_items, charges and
    # sub_account out of here into their own contract keys. Kept separate from
    # ExtractedFields because a repeating table is not a name->value pair, and
    # flattening one into `fields` would make `fields.line_items` a list in a
    # mapping every other consumer reads as scalars.
    row_groups: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # The remittance scan line, verbatim. Scoring-only (F7): it never supplies a
    # field value, it only corroborates one that a selector already read.
    scanline: str | None = None

    # capture + gate (s6, s7)
    confidence: dict[str, float] = field(default_factory=dict)
    modifiers: list[str] = field(default_factory=list)
    # Corroboration counts per field, raised by the section 4.3 cross-check ops.
    # Kept separate from `modifiers` because modifiers are document-wide and
    # multiplicative while a boost is per-field and capped (core.confidence):
    # three agreeing renderings of an OCR'd number can still all be wrong the
    # same way, so corroboration may never lift a field to certainty.
    boosts: dict[str, int] = field(default_factory=dict)
    # Modifiers that belong to ONE field rather than to the document. Section 5
    # calls modifiers "multiplicative" without saying what they multiply, and
    # applying every one to every field is wrong: `currency_inferred_weak` says
    # the CURRENCY was inferred from a weak signal, which is no reason to trust
    # the invoice number less. Applying it document-wide put every field of every
    # pack-default document at 0.90 against a 0.95 total threshold, so no
    # document could ever reach the `high` lane.
    field_modifiers: dict[str, list[str]] = field(default_factory=dict)
    # What the persona declared, against what was actually found (s6). Held as
    # `Any` for the same reason `pack` and `persona` are: `core.models` is the
    # bottom of the dependency graph and `core.coverage` imports it.
    #
    # A separate attribute rather than more keys in `confidence`, because a field
    # that produced nothing has no confidence to report - that conflation is the
    # bug `core.coverage` documents.
    coverage: Any | None = None
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
        """Record a modifier that applies to the whole document."""
        if name not in self.modifiers:
            self.modifiers.append(name)

    def add_field_modifier(self, field_name: str, name: str) -> None:
        """Record a modifier that applies to one field only.

        Still appended to `modifiers` so it reaches the emitted record - the
        record lists every modifier that fired, which is what makes a confidence
        number auditable - but Stage 6 multiplies it into that one field alone.
        """
        scoped = self.field_modifiers.setdefault(field_name, [])
        if name not in scoped:
            scoped.append(name)
        self.add_modifier(name)

    def add_tag(self, name: str) -> None:
        if name not in self.tags:
            self.tags.append(name)

    def log(self, message: str) -> None:
        self.events.append(message)


def new_context(document_id: str, source_path: str, **kwargs: Any) -> JobContext:
    return JobContext(document_id=document_id, source_path=source_path, **kwargs)
