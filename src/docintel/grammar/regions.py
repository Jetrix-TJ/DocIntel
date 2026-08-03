"""The closed region vocabulary (`selector-grammar.md` section 2).

A region answers "where on the document may this pattern look". Fourteen fixed
names live in `RESOLVERS`; `page:N` is parameterized and handled by `resolve`.

**Geometry.** `pdf.read_pages` maps pdfplumber's `top`/`bottom` onto
`Word.y0`/`y1`, so y increases *downward* and `y0 == 0` is the top edge. Every
threshold below reads in that frame: `header-block` is `y0 <= height * 0.25`,
the remittance fallback is `y0 >= height * 0.70`. `ocr.py` scales its pixel
output into the same PDF-point space, which is what lets one set of thresholds
serve native-text and OCR'd documents identically.

**Order is meaning.** A resolver returns a *tuple* of `Span`, and the tuple
order is the search order. `totals-block` returns the last page before page 1
because U-PAK's payable is on page 5 of 5 while page 1's `Please Pay` cell is
blank (F9): searching page 1 first finds the empty cell and reports a confident
miss.

**Regions are pure geometry.** Section 7 forbids taking *field values* off a
`supporting` page, but that restriction is not applied here. Reference-pattern
matching must run across every page and it uses these same resolvers, so
`any-page` really does mean every page. Filtering by `PageMeta.role` is the
executor's job, at the point where it knows whether it is capturing a field or
a reference.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Callable
from dataclasses import dataclass

from docintel.core.errors import ValidationError
from docintel.core.geometry import DEFAULT_TOLERANCE, group_lines, median_pitch
from docintel.core.models import PageMeta, PageText, TextSource, Word

HEADER_FRACTION = 0.25      # header-block: top quarter of page 1
TOP_FRACTION = 1.0 / 3.0    # top-left/center/right: top third of page 1
REMITTANCE_FRACTION = 0.70  # remittance fallback: bottom 30%
TOTALS_FALLBACK = 0.60      # totals fallback: bottom 40%

# B4: `TOTALS_BAND`, `NEAR_ANCHOR_RIGHT`, `NEAR_ANCHOR_BELOW`, `CELL_GAP` and
# `LABEL_BLOCK_MAX` are each a LINE COUNT, hard-coded as points against an
# assumed 14pt line pitch — `LABEL_BLOCK_MAX`'s own comment says as much
# outright ("~10 lines" for 140.0, and 140 / 14 == 10 exactly). A document set
# tighter or looser than that pitch either truncates a region that should have
# kept going, or extends further than intended. Each constant below carries a
# paired `..._PITCHES` ratio (`constant / _ASSUMED_PITCH`) that expresses the
# same line count relative to a page's OWN measured pitch (`_pitch`, below),
# resolved through `_scaled` so today's absolute value is kept as a FLOOR — no
# corpus document's region ever narrows, the same discipline as
# `HEADER_BAND_PITCHES` (`grammar/executor.py`) and Task 7's
# `core.geometry.line_tolerance`.
#
# `NEAR_ANCHOR_RIGHT` and `CELL_GAP` are the two exceptions this "LINE COUNT"
# framing doesn't literally fit - both are HORIZONTAL, scaled by this same
# VERTICAL pitch only because no horizontal-pitch measurement exists anywhere
# in this codebase. See the caveat comment at each of their own `..._PITCHES`
# lines below before assuming they behave exactly like the other three.
_ASSUMED_PITCH = 14.0

TOTALS_BAND = 80.0          # points below the totals label to include
TOTALS_BAND_PITCHES = TOTALS_BAND / _ASSUMED_PITCH   # ~5.7 lines
TOTALS_LEAD = 2.0           # a hair above the label line, so the label is inside the band
NEAR_ANCHOR_RIGHT = 300.0   # points right of the anchor
# ...and a little to the LEFT. Section 2 says "within 300pt right of", but a value
# printed BELOW its label is left-aligned with it, and layout jitter routinely puts
# it a point or two further left. Strict equality dropped `Northstar Recycling
# Company, LLC` from under its own `Bill To` label. One cell gap is enough.
NEAR_ANCHOR_LEFT = 12.0
NEAR_ANCHOR_RIGHT_PITCHES = NEAR_ANCHOR_RIGHT / _ASSUMED_PITCH   # ~21.4 lines
# NEAR_ANCHOR_RIGHT is a HORIZONTAL reach, scaled here by VERTICAL line pitch
# anyway - there is no horizontal-pitch measurement anywhere in this codebase,
# so the page's own line pitch is used as a font-scale proxy (a bigger font
# generally has both taller lines and wider characters). `max(floor, ...)`
# means this can only widen the reach, never narrow it, so it is provably
# inert on today's corpus (every page's pitch is below the 14pt assumption).
# But it IS an axis mismatch: a document with an unusual leading-to-character
# width ratio (e.g. double-spaced but normal-size type) would widen this past
# what its actual character width justifies, and could overreach across a
# genuine column boundary. Revisit if a real horizontal-pitch measurement
# (e.g. median inter-word gap, or character width) is ever added.
NEAR_ANCHOR_BELOW = 40.0    # points below the anchor
NEAR_ANCHOR_BELOW_PITCHES = NEAR_ANCHOR_BELOW / _ASSUMED_PITCH   # ~2.9 lines
CELL_GAP = 12.0             # points of horizontal whitespace that ends a cell
CELL_GAP_PITCHES = CELL_GAP / _ASSUMED_PITCH   # ~0.9 lines
# Same axis mismatch as `NEAR_ANCHOR_RIGHT_PITCHES` above, and for the same
# reason: `CELL_GAP` is a HORIZONTAL gap, scaled by VERTICAL line pitch
# because no horizontal-pitch measurement exists here. `max(floor, ...)` means
# this can only widen (never narrow) the gap that still counts as "one cell",
# so it is provably inert on today's corpus - but on a document with an
# unusual leading-to-character-width ratio, widening past what the actual
# character width justifies could merge two cells across a real column
# gutter. Revisit alongside `NEAR_ANCHOR_RIGHT_PITCHES` if that measurement
# is ever added.
# `CELL_GAP` the module constant stays a plain float on purpose: `executor.py`'s
# `_cells()` also reads it, to split a candidate LINE OF TEXT into cells - a
# pattern-matching concern with no `PageText` in scope, out of this task's
# region-vocabulary brief. Only `_same_cell` below (a region resolver) applies
# the pitch-scaled variant, via `_scaled(CELL_GAP, CELL_GAP_PITCHES, ...)`.

# `label-block`: the anchor's own column, from its line down to the next blank
# line. Added after C5b, where addresses were the single largest remaining class
# of failure across both packs.
#
# Neither existing region could reach them. `near-anchor` stops 40pt below the
# label, which covers a street line but not the city line beneath it.
# `header-block` and the page regions span the FULL page width, and every
# telecom bill in the corpus is a two-column layout flattened into one
# interleaved line stream - so a full-width region picks up the other column:
#
#     To log in or register, go to https://www.lumen.com/login/. Balance 0.00
#     131 W MATTHEWS ST. Amount Due $1,230.14
#
# So this region is x-bounded like `near-anchor` (it stays in the column) and
# y-unbounded until the block genuinely ends (it reaches the whole address).
LABEL_BLOCK_LEFT = 12.0     # same left tolerance as near-anchor
LABEL_BLOCK_RIGHT = 300.0   # same column width as near-anchor
LABEL_BLOCK_MAX = 140.0     # hard ceiling, ~10 lines: a block, not a page
LABEL_BLOCK_MAX_PITCHES = LABEL_BLOCK_MAX / _ASSUMED_PITCH   # == 10.0, matching the comment above
# Whitespace that means "a different column", used to replace the fixed
# LABEL_BLOCK_RIGHT with the real column edge.
#
# `LABEL_BLOCK_RIGHT = 300.0` is a guess, and on Centracom it guesses through
# 224pt of empty space into the next column: `vendor_address` came back as
# `Balance, PO BOX 7, Payments, FAIRVIEW UT 84629, Previous, Please, ...`.
#
# 24.0 is twice `CELL_GAP` - this file already calls 12pt "a column's worth" of
# horizontal whitespace when splitting a line into cells - and it sits below the
# narrowest genuine inter-column gutter measured on the corpus (25pt on Veritiv,
# 26pt on U-PAK), while staying far above the few points that separate words
# inside one address line.
LABEL_BLOCK_GUTTER = 24.0
LABEL_BLOCK_GAP_FACTOR = 2.0  # multiples of the block's own line pitch that end it
LABEL_BLOCK_GAP_FLOOR = 24.0  # keeps a tight-leaded block from breaking early
# How many rows that are empty IN THIS COLUMN may sit inside a block.
#
# One, not zero. A single empty row is a GAP rather than the end: on Comcast's
# bill the left column's `Account number` label is taller than the right column's
# content beside it, so the charges ladder reads
#
#     New charges
#     Comcast Business services            217.89
#     <- nothing in the right column on this row
#     Taxes and fees                         3.22
#
# and a zero-tolerance rule stopped after the first charge. Two consecutive empty
# rows is the end. Over-reach is still bounded by the gap rule and the max cap.
LABEL_BLOCK_BLANK_TOLERANCE = 1


@dataclass(frozen=True)
class Anchor:
    """A located anchor match.

    The page number is part of the location, not context the caller can supply
    separately: a `DESCRIPTION` table anchor found on page 3 must resolve its
    `line_items` region against page 3. `Word` alone cannot express that, and
    `Word` is a frozen contract owned by `core.models`.
    """

    word: Word
    page_number: int


@dataclass(frozen=True)
class Span:
    """A resolved region: the words inside it, and where it was.

    `source` travels with the span so the executor can apply the `ocr_source`
    modifier without re-deriving where the text came from. `bbox` is the
    *region's* box, not the page's, so a captured field can record the geometry
    it was read from.
    """

    page_number: int
    source: TextSource
    words: tuple[Word, ...]
    bbox: tuple[float, float, float, float]
    # Inherited from the page this span was cut from (see `_span`), never
    # recomputed from the span's own (windowed) words: a region is a window
    # onto one page, and recomputing from the window would give a different
    # answer for the same ink. Defaults to today's ceiling for the two direct
    # constructions below that don't go through `_span`.
    line_tolerance: float = DEFAULT_TOLERANCE

    def lines(self) -> list[list[Word]]:
        """Group words into visual lines, each sorted left to right."""
        return group_lines(self.words, self.line_tolerance)

    @property
    def text(self) -> str:
        return "\n".join(" ".join(w.text for w in line) for line in self.lines())


Resolver = Callable[
    [tuple[PageText, ...], tuple[PageMeta, ...], Anchor | None],
    "tuple[Span, ...]",
]

# Regions defined relative to a matched anchor. The uniform resolver signature
# means these carry the same three parameters as the rest and raise when the
# anchor is absent - which the validator can check statically (V5's neighbour).
ANCHOR_REQUIRED: frozenset[str] = frozenset({
    "near-anchor", "same-row", "same-cell", "line_items", "last-table-row",
    "label-block",
})

# Regions that do NOT narrow the search. V6 keys off this: a bare-digit regex
# needs a region narrower than `any-page` or it matches phone numbers and
# zip+4 (F11). Section 3.2 names `any-page` as the only such region.
NON_NARROWING: frozenset[str] = frozenset({"any-page"})

_PAGE_RE = re.compile(r"^page:([1-9]\d*)$")

# A detach rule above the remittance stub. An enumeration, deliberately, for
# the same reason `pageroles._TOTALS_RE` is one: a general "looks like a rule"
# detector trades a visible gap for invisible false positives.
_DETACH_RE = re.compile(r"\b(DETACH|RETURN TOP PORTION|RETURN THIS PORTION|TEAR OFF)\b")

# The document's own payable label. Shares its vocabulary with
# `pageroles._TOTALS_RE` by intent, not by import: that module decides which
# page is primary, this one decides where on a page to look, and the two are
# free to diverge as the corpus grows.
_TOTALS_RE = re.compile(
    r"\b(TOTAL AMOUNT DUE|PLEASE PAY|BALANCE DUE|BALANCE PAYABLE|TOTAL DUE|"
    r"NOW DUE|GRAND TOTAL|TOTAL AMT|AMOUNT DUE|TOTAL)\b"
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _span(page: PageText, words: tuple[Word, ...], bbox: tuple[float, float, float, float]) -> Span:
    return Span(
        page_number=page.page_number,
        source=page.source,
        words=words,
        bbox=bbox,
        line_tolerance=page.line_tolerance,
    )


def _whole(page: PageText) -> Span:
    return _span(page, page.words, (0.0, 0.0, page.width, page.height))


def _band(page: PageText, top: float, bottom: float) -> Span:
    """Every word whose top edge falls within [top, bottom], full page width."""
    words = tuple(w for w in page.words if top <= w.y0 <= bottom)
    return _span(page, words, (0.0, top, page.width, bottom))


def _box(page: PageText, x0: float, top: float, x1: float, bottom: float) -> Span:
    words = tuple(w for w in page.words if top <= w.y0 <= bottom and x0 <= w.x0 < x1)
    return _span(page, words, (x0, top, x1, bottom))


def _page_of(pages: tuple[PageText, ...], anchor: Anchor) -> PageText | None:
    for p in pages:
        if p.page_number == anchor.page_number:
            return p
    return None


def _require(anchor: Anchor | None, region: str) -> Anchor:
    if anchor is None:
        raise ValidationError(f"region {region!r} needs an anchor, but none was matched")
    return anchor


_MIN_LINES_FOR_PITCH = 4  # 3 gaps: the fewest for a median to be an actual
# middle value rather than the average of two (2 lines) or the single
# distance between them (a lone gap dominated entirely by whatever those two
# lines happen to be). A `near-anchor` or `totals-block` unit-test fixture
# often has only 2-3 lines total, one of them a deliberately distant probe
# word (a "toofar"/"waybelow" exclusion check, or a scanline stub 460pt below
# the totals label) - exactly the outlier a real multi-line invoice page never
# has just one of. Below this count, `_scaled` falls back to its floor,
# unscaled: today's behaviour on a page too sparse to trust a pitch reading.


def _pitch(page: PageText) -> float | None:
    """This page's own median line-to-line pitch, or `None` if there are too
    few lines to trust one (see `_MIN_LINES_FOR_PITCH`).

    Delegates to `core.geometry.median_pitch` over the page's own already-grouped
    lines (`page.lines()`, using the page's REAL `line_tolerance`, not the
    bootstrap tolerance `line_tolerance()` itself uses internally) - the same
    measurement `grammar.executor`'s `_median_pitch` makes for `HEADER_BAND_PITCHES`,
    so this file does not grow a second implementation of "the median gap
    between two line baselines".
    """
    lines = page.lines()
    if len(lines) < _MIN_LINES_FOR_PITCH:
        return None
    return median_pitch(lines)


def _scaled(floor: float, pitches: float, pitch: float | None) -> float:
    """`floor`, or `pitches` lines at this page's own measured pitch, whichever
    reaches further.

    B4/Task 8's whole fix: each `floor` (`NEAR_ANCHOR_BELOW` and friends) was
    hard-coded against an assumed 14pt pitch, so `pitches = floor / 14.0`
    expresses the same line count relative to whatever pitch THIS page actually
    measures. `floor` stays a FLOOR rather than being replaced outright, so a
    page at or below the 14pt assumption never gets a narrower region than it
    has today - the corpus (median pitch 5.8-12.4pt, per Task 7) is entirely
    below that assumption and so is provably unaffected by this function for
    every one of these five constants. `pitch is None` (fewer than two lines to
    measure) leaves `floor` as the answer: there is nothing to scale by.
    """
    if pitch is None:
        return floor
    return max(floor, pitch * pitches)


def _label_y(page: PageText, pattern: re.Pattern[str]) -> float | None:
    """The top edge of the last line matching `pattern`.

    Last, not first: a totals label appears in a table header before it appears
    over the actual figure, and the figure is what a selector is after.
    """
    found: float | None = None
    for line in page.lines():
        text = " ".join(w.text for w in line).upper()
        if pattern.search(text):
            found = line[0].y0
    return found


# --------------------------------------------------------------------------
# Whole-page regions
# --------------------------------------------------------------------------


def _first_page(
    pages: tuple[PageText, ...], meta: tuple[PageMeta, ...], anchor: Anchor | None
) -> tuple[Span, ...]:
    return (_whole(pages[0]),) if pages else ()


def _last_page(
    pages: tuple[PageText, ...], meta: tuple[PageMeta, ...], anchor: Anchor | None
) -> tuple[Span, ...]:
    return (_whole(pages[-1]),) if pages else ()


def _any_page(
    pages: tuple[PageText, ...], meta: tuple[PageMeta, ...], anchor: Anchor | None
) -> tuple[Span, ...]:
    return tuple(_whole(p) for p in pages)


def _page_n(n: int) -> Resolver:
    def resolver(
        pages: tuple[PageText, ...], meta: tuple[PageMeta, ...], anchor: Anchor | None
    ) -> tuple[Span, ...]:
        for p in pages:
            if p.page_number == n:
                return (_whole(p),)
        return ()  # a shorter document than the fingerprint expected: a miss, not a crash

    return resolver


# --------------------------------------------------------------------------
# Geometric regions - page 1 only
# --------------------------------------------------------------------------


def _header_block(
    pages: tuple[PageText, ...], meta: tuple[PageMeta, ...], anchor: Anchor | None
) -> tuple[Span, ...]:
    if not pages:
        return ()
    p = pages[0]
    return (_band(p, 0.0, p.height * HEADER_FRACTION),)


def _top_third(which: str) -> Resolver:
    def resolver(
        pages: tuple[PageText, ...], meta: tuple[PageMeta, ...], anchor: Anchor | None
    ) -> tuple[Span, ...]:
        if not pages:
            return ()
        p = pages[0]
        third = p.width / 3.0
        x0 = {"left": 0.0, "center": third, "right": third * 2.0}[which]
        x1 = x0 + third if which != "right" else p.width
        return (_box(p, x0, 0.0, x1, p.height * TOP_FRACTION),)

    return resolver


# --------------------------------------------------------------------------
# Structural regions
# --------------------------------------------------------------------------


def _totals_on(page: PageText, anchor: Anchor | None) -> Span:
    """The band around this page's totals label.

    Ladder: the selector's own anchor, then the label enumeration, then the
    bottom 40% of the page. The last rung matters - an unrecognized phrasing
    should widen the search, which confidence can price, rather than return
    nothing, which reads as a certain miss.
    """
    top: float | None = None
    if anchor is not None and anchor.page_number == page.page_number:
        top = anchor.word.y0
    if top is None:
        top = _label_y(page, _TOTALS_RE)
    if top is None:
        return _band(page, page.height * TOTALS_FALLBACK, page.height)
    band = _scaled(TOTALS_BAND, TOTALS_BAND_PITCHES, _pitch(page))
    return _band(page, top - TOTALS_LEAD, min(top + band, page.height))


def _totals_block(
    pages: tuple[PageText, ...], meta: tuple[PageMeta, ...], anchor: Anchor | None
) -> tuple[Span, ...]:
    """Last page first, then page 1 (F9). Deduplicated for one-page documents."""
    if not pages:
        return ()
    order = [pages[-1]] if len(pages) == 1 else [pages[-1], pages[0]]
    return tuple(_totals_on(p, anchor) for p in order)


def _remittance_block(
    pages: tuple[PageText, ...], meta: tuple[PageMeta, ...], anchor: Anchor | None
) -> tuple[Span, ...]:
    """Below the detach rule, page 1 first and then the last page.

    **Page 1 first, and that ordering is the whole correction.** An earlier draft
    searched only the last page, on the reasoning that a stub sits at the foot of a
    document. The corpus says otherwise: you detach the top of the FIRST page and
    mail it, so Centracom's scan line is on page 1 of 10 and Comcast's on page 1 of
    6. Searching the last page found the final page of per-line service detail and
    reported a confident miss on all five documents that print a scan line.

    Same shape as `totals-block`, which searches the last page first for the
    mirror-image reason (F9). Both regions have a preferred page and a fallback;
    neither can assume.
    """
    if not pages:
        return ()
    order = [pages[0]] if len(pages) == 1 else [pages[0], pages[-1]]
    out: list[Span] = []
    for page in order:
        cut = _label_y(page, _DETACH_RE)
        top = (
            cut + page.line_tolerance
            if cut is not None
            else page.height * REMITTANCE_FRACTION
        )
        out.append(_band(page, top, page.height))
    return tuple(out)


def _table_body(pages: tuple[PageText, ...], anchor: Anchor) -> Span | None:
    """Everything below the table header row, on the anchor's own page.

    The header row itself is excluded: `line_items` is the table *body*, and a
    row group matches its columns by header text separately (F19). A fuller
    table model - column boundaries, row spans - arrives with the row-group
    executor; this is the geometric part it will refine.
    """
    page = _page_of(pages, anchor)
    if page is None:
        return None
    return _band(page, anchor.word.y0 + page.line_tolerance + 1.0, page.height)


def _line_items(
    pages: tuple[PageText, ...], meta: tuple[PageMeta, ...], anchor: Anchor | None
) -> tuple[Span, ...]:
    body = _table_body(pages, _require(anchor, "line_items"))
    return (body,) if body is not None else ()


def _last_table_row(
    pages: tuple[PageText, ...], meta: tuple[PageMeta, ...], anchor: Anchor | None
) -> tuple[Span, ...]:
    body = _table_body(pages, _require(anchor, "last-table-row"))
    if body is None:
        return ()
    lines = body.lines()
    if not lines:
        return ()
    last = lines[-1]
    return (
        Span(
            page_number=body.page_number,
            source=body.source,
            words=tuple(last),
            bbox=(body.bbox[0], last[0].y0, body.bbox[2], last[0].y1),
            line_tolerance=body.line_tolerance,
        ),
    )


# --------------------------------------------------------------------------
# Anchor-relative regions
# --------------------------------------------------------------------------


def _near_anchor(
    pages: tuple[PageText, ...], meta: tuple[PageMeta, ...], anchor: Anchor | None
) -> tuple[Span, ...]:
    a = _require(anchor, "near-anchor")
    page = _page_of(pages, a)
    if page is None:
        return ()
    pitch = _pitch(page)
    top = a.word.y0 - page.line_tolerance
    x0 = a.word.x0 - NEAR_ANCHOR_LEFT
    x1 = a.word.x0 + _scaled(NEAR_ANCHOR_RIGHT, NEAR_ANCHOR_RIGHT_PITCHES, pitch)
    bottom = a.word.y0 + _scaled(NEAR_ANCHOR_BELOW, NEAR_ANCHOR_BELOW_PITCHES, pitch)
    return (_box(page, x0, top, x1, bottom),)


def _same_row(
    pages: tuple[PageText, ...], meta: tuple[PageMeta, ...], anchor: Anchor | None
) -> tuple[Span, ...]:
    a = _require(anchor, "same-row")
    page = _page_of(pages, a)
    if page is None:
        return ()
    return (_band(page, a.word.y0 - page.line_tolerance, a.word.y0 + page.line_tolerance),)


def _label_block(
    pages: tuple[PageText, ...], meta: tuple[PageMeta, ...], anchor: Anchor | None
) -> tuple[Span, ...]:
    """The anchor's column, from its line down to the next blank line.

    "Blank" means blank *in this column* - a line with words only in the other
    column ends the block, which is what makes the region column-aware rather
    than merely narrow. Three further stops keep it a block rather than a page: a
    vertical gap much larger than the block's own line pitch, the
    `LABEL_BLOCK_MAX` ceiling, and the foot of the page.

    The anchor's own line is included. The executor excludes the anchor's words
    from its candidates, so a `text_block` capture yields the address beneath the
    label rather than the label itself.
    """
    a = _require(anchor, "label-block")
    page = _page_of(pages, a)
    if page is None:
        return ()

    x0 = a.word.x0 - LABEL_BLOCK_LEFT
    x1 = a.word.x0 + LABEL_BLOCK_RIGHT
    top = a.word.y0 - page.line_tolerance
    max_reach = _scaled(LABEL_BLOCK_MAX, LABEL_BLOCK_MAX_PITCHES, _pitch(page))

    bands: list[list[Word]] = []
    prev_y: float | None = None
    pitch: float | None = None
    gaps: list[float] = []
    blanks = 0

    for line in page.lines():
        y = line[0].y0
        if y < top:
            continue
        if y - a.word.y0 > max_reach:
            break
        band = [w for w in line if x0 <= w.x0 < x1]
        if not band:
            blanks += 1
            if blanks > LABEL_BLOCK_BLANK_TOLERANCE:
                break  # two empty rows in this column: the block has ended
            continue
        blanks = 0
        if prev_y is not None:
            gap = y - prev_y
            if pitch is None:
                # The anchor's own line to the block's first content line is a
                # LABEL's leading, not a body-pitch sample - DTSS prints it at
                # 36pt against a 14.16pt body pitch. Seeding `pitch` from it
                # (as the original `min` code always did) is fine for the
                # very next gap's threshold check, but never admitting it
                # into `gaps` keeps a two-sample median from being dragged
                # up by a value it was never representative of (task-5
                # finding 3; see task-5-report.md for the traced numbers).
                pitch = gap
            elif gap > max(LABEL_BLOCK_GAP_FLOOR, pitch * LABEL_BLOCK_GAP_FACTOR):
                break
            else:
                # Median, not min: `min` let one tight line permanently
                # redefine the block's rhythm, after which the next ORDINARY
                # gap read as a block break. Fixed for row groups in
                # 26a485d; this is the same bug in the other caller - but
                # unlike row groups, the FIRST gap here is deliberately kept
                # out of the sample pool (see above).
                gaps.append(gap)
                pitch = statistics.median(gaps)
        bands.append(band)
        prev_y = y

    # NOTE: the column gutter is deliberately NOT applied here. This region also
    # serves label/amount ladders, where the wide gap between a label and its
    # right-aligned amount is the layout, not contamination - narrowing here cut
    # the amount off and regressed Centracom and Comcast. The executor applies
    # `column_cut` only for `text_block`, because it is the only caller that knows
    # the pattern; a region resolver is pattern-blind on purpose.
    kept = [w for band in bands for w in band]
    bottom = max([a.word.y1, *(w.y1 for w in kept)])
    return (_span(page, tuple(kept), (x0, top, x1, bottom)),)


def column_cut(bands: list[list[Word]], anchor_x0: float, limit: float) -> float:
    """The near edge of the first column gutter at or right of the anchor.

    `limit` when there is none, so a single-column block keeps today's boundary.

    The gutter is only unambiguous across a block's OWN rows: projected over a wide
    band the union of many differently-indented rows occupies everything and no
    gutter survives. Measured - Centracom shows 0 gutters over y 40-320 and a clean
    224pt one over its address rows.
    """
    occupied: set[int] = set()
    for band in bands:
        for w in band:
            occupied.update(range(int(w.x0), int(w.x1) + 1))
    run: int | None = None
    for x in range(int(anchor_x0), int(limit) + 1):
        if x not in occupied:
            if run is None:
                run = x
        else:
            if run is not None and x - run >= LABEL_BLOCK_GUTTER:
                return float(run)
            run = None
    return limit


def _same_cell(
    pages: tuple[PageText, ...], meta: tuple[PageMeta, ...], anchor: Anchor | None
) -> tuple[Span, ...]:
    """The run of words around the anchor, bounded by a column-width gap.

    Without a real table model, a cell is approximated as the contiguous run on
    the anchor's line: walk outward from the anchor and stop at the first gap
    wider than `CELL_GAP`. That is what separates `BALANCE FORWARD` (a 5pt
    inter-word gap) from the `298.34` sitting in the next column.
    """
    a = _require(anchor, "same-cell")
    page = _page_of(pages, a)
    if page is None:
        return ()

    row = sorted(
        (w for w in page.words if abs(w.y0 - a.word.y0) <= page.line_tolerance),
        key=lambda w: w.x0,
    )
    if not row:
        return ()

    gap = _scaled(CELL_GAP, CELL_GAP_PITCHES, _pitch(page))
    idx = min(range(len(row)), key=lambda i: abs(row[i].x0 - a.word.x0))
    lo = idx
    while lo > 0 and row[lo].x0 - row[lo - 1].x1 <= gap:
        lo -= 1
    hi = idx
    while hi + 1 < len(row) and row[hi + 1].x0 - row[hi].x1 <= gap:
        hi += 1

    cell = tuple(row[lo : hi + 1])
    return (
        Span(
            page_number=page.page_number,
            source=page.source,
            words=cell,
            bbox=(cell[0].x0, cell[0].y0, cell[-1].x1, cell[-1].y1),
            line_tolerance=page.line_tolerance,
        ),
    )


# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------

RESOLVERS: dict[str, Resolver] = {
    "first-page": _first_page,
    "last-page": _last_page,
    "any-page": _any_page,
    "top-left": _top_third("left"),
    "top-center": _top_third("center"),
    "top-right": _top_third("right"),
    "header-block": _header_block,
    "totals-block": _totals_block,
    "remittance-block": _remittance_block,
    "line_items": _line_items,
    "last-table-row": _last_table_row,
    "near-anchor": _near_anchor,
    "label-block": _label_block,
    "same-row": _same_row,
    "same-cell": _same_cell,
}


def is_known(region: str) -> bool:
    """Whether `region` is in the section 2 enum. This is rule V3."""
    if not isinstance(region, str):
        return False
    return region in RESOLVERS or _PAGE_RE.match(region) is not None


def resolve(region: str) -> Resolver:
    """Look up a region's resolver, including the parameterized `page:N`."""
    resolver = RESOLVERS.get(region)
    if resolver is not None:
        return resolver
    m = _PAGE_RE.match(region) if isinstance(region, str) else None
    if m is not None:
        return _page_n(int(m.group(1)))
    raise ValidationError(
        f"unknown region {region!r}; the region vocabulary is closed "
        f"(selector-grammar.md section 2)"
    )
