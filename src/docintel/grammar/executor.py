"""Run a validated persona's selectors against a document's pages.

This is the whole of Stage 5a: no AI calls, only the closed grammar applied to
normalized page text. What it deliberately does **not** do is as important as
what it does, because each of these would be the executor quietly taking over
another stage's job:

* **It does not apply `adjust` ops.** Section 4 says ops run at Stage 6, in
  declaration order. `s6_capture` reads them straight off `ctx.persona`, so
  there is no need for an intermediate "pending ops" structure and no chance of
  one drifting out of sync with the persona that produced it.
* **It does not compute confidence.** It records a `match_quality` per field and
  appends modifier *names* to `ctx.modifiers`. Turning those into a number is
  Stage 6's single responsibility (`core.confidence`).
* **It does not enforce `required`.** A missing required field is a miss. Pricing
  it is Stage 6, routing it is Stage 7. Raising here would turn an ordinary,
  reviewable gap into a pipeline error.

**It does apply the section 7 page-role rule**, which `regions.py` deliberately
does not: field values never come off a `supporting` page. The role map is built
from `ctx.page_meta` and is **fail-closed** - a page with no role entry counts as
supporting, so a pipeline that skipped role assignment extracts nothing visible
rather than silently reading totals off a handwritten Bill of Lading (F10). A
loud empty result is recoverable; a confident wrong one is not.

The scan line is the documented exception: it is scoring-only, so section 7 does
not apply to it, and must not - the remittance stub of a multi-page bill
routinely lands on a continuation page that is legitimately `supporting`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from time import perf_counter
from typing import Any

from docintel.core.models import JobContext, PageText, Word
from docintel.extract import scanline as scanline_mod
from docintel.grammar import patterns, regions
from docintel.grammar.regions import Anchor, Span
from docintel.grammar.schema import (
    FieldSelector,
    Persona,
    RowGroupSelector,
    ScanlineSelector,
    SubGroup,
)

# Section 3.2's hard 50ms budget per field per document.
PATTERN_BUDGET_SECONDS = 0.050

# match_quality, the base Stage 6 applies modifiers to. An anchored hit is the
# strongest evidence the grammar can produce; a region-only hit is weaker
# because nothing on the page confirmed what the value is *labelled* as.
QUALITY_ANCHORED = 1.0
QUALITY_ANCHOR_ALT = 0.95
QUALITY_REGION_ONLY = 0.90

# Where a table ends. The `line_items` region runs from the header row to the
# foot of the page, because nothing in the page geometry says where a table
# stops - so the executor has to decide, and it decides on vertical rhythm: a
# gap much larger than the established row pitch is a structural break.
#
# This is not a corner case. Every invoice in the corpus prints a totals block
# below its line-item table, and five also print a remittance stub below that.
# Without a break rule the first row group would swallow both on every document,
# so `line_items` would contain the total as an extra row and the whole F8
# closure check would be meaningless.
TABLE_BREAK_FACTOR = 2.5   # multiples of the established row pitch
TABLE_BREAK_FLOOR = 24.0   # points; keeps a tight-leaded table from breaking early

# How far ABOVE the anchor's line a wrapped column header may sit, as a multiple of
# the page's OWN median line pitch, with an absolute floor.
#
# Relative because an absolute band assumes a font size. Measured median pitch
# across this corpus is 5.8-12.4pt, so the original fixed 12.0 covered it - but a
# document set in larger type, with 20pt leading, prints a wrapped header 20pt above
# its anchor row and a 12pt band misses it silently. Over thousands of senders that
# is a guaranteed failure class, not a hypothesis.
#
# 1.5 pitches, so the band reaches the immediately preceding line and not the one
# before that. The floor keeps behaviour identical on tightly-leaded documents
# (Complete Beverage's 5.8pt median would otherwise give an 8.7pt band, narrower
# than today's).
HEADER_BAND_PITCHES = 1.5
HEADER_BAND_MIN = 12.0

# Retained as the floor's value and as the documented default for a page whose
# pitch cannot be measured (a single-line page has no gaps).
#
# Veritiv prints `Extended Price` as two lines, with `Extended` 8.26pt above the
# row carrying the `Product No.` anchor. `page.lines()` splits at
# `_LINE_TOLERANCE = 3.0`, so `_column_bounds` never saw the amount header, bound
# only `item_code`, and matched no amounts at all. Worse, it did so SILENTLY: the
# declared-header authoring error below only fires when `bounds` is empty, and one
# surviving column is not empty.
#
# Deliberately one-directional. Reaching DOWN as well would let a first data row
# printed tight under the header be absorbed into the header row, which loses the
# row AND corrupts every column boundary derived from it - a worse failure than the
# one being fixed, and `allow_empty_cells` tables would not even reveal it.

# Patterns that make a column the AMOUNT in a header-less row group.
MONEY_PATTERNS: frozenset[str] = frozenset({"currency", "currency_signed"})

# A roll-up row inside a label/amount ladder is not a member of the list it sums.
# Centracom prints `Subtotal Current Charges $13,752.60` and `Previous Balance
# $20,123.80` inside the same block as its three real charges, and its gold
# `charges` label correctly contains only the three. This is a property of ladders
# in general rather than of one vendor, which is why it lives here.
#
# `previous\s+balance` (task-5 review, 2026-08-03): the comment above already
# claimed this filter caught `Previous Balance` - it never did, because the regex
# is anchored at the label's START (`^\s*`) and "Previous" was not one of the
# alternatives, only "balance" was. `_label_block`'s old `min`-based pitch bug
# floor-clamped the block's break threshold low enough that `Previous Balance`
# never entered the ladder's window at all, so this gap was silent. Fixing that
# bug (task-5) raised the threshold and exposed it: `Previous Balance $20,123.80`
# started reaching this filter and falling through unmatched. Added as its own
# alternative rather than loosening `balance` to match mid-string, which would
# risk matching a genuine charge whose label happens to contain the word "balance".
_ROLLUP_LABEL = re.compile(
    r"^\s*(sub\s?total|total|amount\s+due|balance|please\s+pay|previous\s+balance)\b",
    re.IGNORECASE,
)



@dataclass(frozen=True)
class AnchorMatch:
    """One occurrence of an anchor phrase, and the words that spelled it."""

    page_number: int
    words: tuple[Word, ...]

    def as_anchor(self) -> Anchor:
        return Anchor(word=self.words[0], page_number=self.page_number)


def _norm(text: str) -> str:
    """Compare anchors case-insensitively, whitespace-collapsed, colon-agnostic.

    The trailing colon is dropped from both sides because a printed label is
    written `CURRENT CHARGES:` on one document and `Current Charges` on the
    next, and a persona should not need two `anchor_alts` to survive
    punctuation. Everything else is compared strictly: an anchor that matched on
    a substring would find `TOTAL` inside `SUBTOTAL`.
    """
    return " ".join(text.split()).upper().rstrip(":")


def _runs(line: Sequence[Word], needle: str) -> list[tuple[Word, ...]]:
    """Every contiguous word run on `line` whose joined text equals `needle`.

    Shared by anchor lookup and column-header location, which are the same
    operation asked twice: find the words that spell a known phrase. The length
    guard only ever ends the *inner* scan - an earlier draft let it end the
    outer one too, which silently abandoned the search after the first header
    and put every cell of every row into the leftmost column.
    """
    upper = [w.text.upper() for w in line]
    found: list[tuple[Word, ...]] = []
    for start in range(len(line)):
        acc = ""
        for end in range(start, len(line)):
            acc = upper[start] if end == start else f"{acc} {upper[end]}"
            if _norm(acc) == needle:
                found.append(tuple(line[start : end + 1]))
                break
            if len(acc) > len(needle) + 1:
                break
    return found


def _cells(words: Sequence[Word]) -> list[list[Word]]:
    """Split a line into cells at any gap wider than a column's worth."""
    out: list[list[Word]] = []
    for w in words:
        if out and w.x0 - out[-1][-1].x1 <= regions.CELL_GAP:
            out[-1].append(w)
        else:
            out.append([w])
    return out


def _median_pitch(page: PageText) -> float | None:
    """The page's median gap between consecutive line tops, or None.

    Median rather than mean: every invoice here mixes body text with widely spaced
    section headings, and a mean is dragged upward by the headings.
    """
    tops = [line[0].y0 for line in page.lines()]
    gaps = [b - a for a, b in zip(tops, tops[1:]) if b > a]
    return median(gaps) if gaps else None


def _header_band(page: PageText, base: list[Word]) -> list[Word]:
    """`base` plus any wrapped header words sitting just above it, in x order.

    Sorted by x0 because `_cells` walks the sequence and compares each word's `x0`
    against the previous word's `x1` - it splits on horizontal whitespace and has
    no opinion about y, so an unsorted merge would invent cell boundaries.
    """
    pitch = _median_pitch(page)
    band = HEADER_BAND_MIN if pitch is None else max(
        HEADER_BAND_MIN, pitch * HEADER_BAND_PITCHES
    )
    top = base[0].y0
    merged = list(base)
    for line in page.lines():
        if top - band <= line[0].y0 < top:
            merged.extend(line)
    return sorted(merged, key=lambda w: w.x0)


class Executor:
    """Applies one persona to one document."""

    def __init__(self, persona: Persona) -> None:
        self.persona = persona
        self._budget_seconds = PATTERN_BUDGET_SECONDS

    # -- public ------------------------------------------------------------

    def apply(self, ctx: JobContext) -> JobContext:
        """Extract everything this persona describes. Mutates and returns `ctx`.

        The same context object comes back out: the pipeline threads one mutable
        JobContext through all eight stages, and a clone here would silently
        drop whatever an earlier stage had recorded on it.
        """
        for selector in self.persona.field_selectors:
            if isinstance(selector, ScanlineSelector):
                self._apply_scanline(ctx, selector)
            elif isinstance(selector, RowGroupSelector):
                self._apply_row_group(ctx, selector)
            else:
                self._apply_field(ctx, selector)
        return ctx

    # -- page roles --------------------------------------------------------

    def _role(self, ctx: JobContext, page_number: int) -> str:
        """Fail-closed: no role entry means `supporting`, never `primary`."""
        for meta in ctx.page_meta:
            if meta.page_number == page_number:
                return meta.role
        return "supporting"

    def _page(self, ctx: JobContext, page_number: int) -> PageText | None:
        for page in ctx.pages:
            if page.page_number == page_number:
                return page
        return None

    # -- anchors -----------------------------------------------------------

    def _find_anchors(
        self, ctx: JobContext, phrase: str, primary_only: bool = True
    ) -> list[AnchorMatch]:
        """Every occurrence of `phrase` as a contiguous word run on one line."""
        needle = _norm(phrase)
        if not needle:
            return []
        found: list[AnchorMatch] = []
        for page in ctx.pages:
            if primary_only and self._role(ctx, page.page_number) != "primary":
                continue
            for line in page.lines():
                for run in _runs(line, needle):
                    found.append(AnchorMatch(page.page_number, run))
        return found

    def _resolve_anchor(
        self, ctx: JobContext, selector: FieldSelector
    ) -> tuple[AnchorMatch | None, bool, bool]:
        """(match, used_alt, ambiguous). Alts are tried in declaration order."""
        if selector.anchor is None:
            return None, False, False

        # `hits` is in reading order, so "last" is simply the other end. An
        # ambiguous anchor stays ambiguous either way: the modifier still applies,
        # because choosing an occurrence deliberately is not the same as the page
        # having only one.
        pick = -1 if selector.anchor_occurrence == "last" else 0

        hits = self._find_anchors(ctx, selector.anchor)
        if hits:
            return hits[pick], False, len(hits) > 1

        for alt in selector.anchor_alts:
            hits = self._find_anchors(ctx, alt)
            if hits:
                return hits[pick], True, len(hits) > 1
        return None, False, False

    # -- candidate generation ---------------------------------------------

    def _candidates(
        self, span: Span, pattern: str, skip: frozenset[Word]
    ) -> Iterator[str]:
        """Strings to try the pattern against, most specific first.

        Cells before individual words before the whole line: a totals line reads
        `Total Amount Due   367.96`, which splits into two cells and matches on
        the second, but when the gap is tight enough that it stays one cell the
        per-word pass still finds the figure.

        `skip` holds the words that spelled the anchor. Excluding them is what
        stops a `text_block` on `near-anchor` returning the label it was
        located by instead of the address next to it.
        """
        if pattern == "text_block":
            bands = [[w for w in line if w not in skip] for line in span.lines()]
            # Stop at the real column edge rather than the region's nominal right
            # bound. Only `text_block` does this: it is the pattern that captures a
            # multi-line block, so a neighbouring column is contamination. A
            # label/amount ladder on the same region needs the opposite - the wide
            # gap before its right-aligned amount IS the layout - and `regions.py`
            # cannot tell the two apart because a resolver never sees the pattern.
            left = min((w.x0 for w in skip), default=span.bbox[0])
            cut = regions.column_cut(bands, left, span.bbox[2])
            lines = [
                " ".join(w.text for w in band if w.x0 < cut) for band in bands
            ]
            block = "\n".join(line for line in lines if line.strip())
            if block.strip():
                yield block
            return

        seen: set[str] = set()
        for line in span.lines():
            words = [w for w in line if w not in skip]
            if not words:
                continue
            groups = [*_cells(words), *([w] for w in words), words]
            for group in groups:
                text = " ".join(w.text for w in group)
                if text and text not in seen:
                    seen.add(text)
                    yield text

    # -- field selectors ---------------------------------------------------

    def _apply_field(self, ctx: JobContext, selector: FieldSelector) -> None:
        match, used_alt, ambiguous = self._resolve_anchor(ctx, selector)
        if selector.anchor is not None and match is None:
            return  # the label is not on this document: an ordinary miss

        anchor = match.as_anchor() if match is not None else None
        skip = frozenset(match.words) if match is not None else frozenset()

        spans = regions.resolve(selector.region)(ctx.pages, ctx.page_meta, anchor)
        spans = tuple(s for s in spans if self._role(ctx, s.page_number) == "primary")

        matcher = patterns.resolve(selector.pattern)
        values: list[Any] = []
        deadline = perf_counter() + self._budget_seconds
        want_all = selector.capture == "all_matches"

        for span in spans:
            for candidate in self._candidates(span, selector.pattern, skip):
                if perf_counter() > deadline:
                    # Section 3.2: a blown budget is a miss plus a modifier,
                    # never a wedged worker. Whatever was found so far is
                    # discarded - a partial all_matches list is worse than a
                    # visible miss, because it looks complete.
                    ctx.add_field_modifier(selector.field, "pattern_timeout")
                    ctx.log(f"s5a: pattern budget exceeded for {selector.field!r}")
                    return
                value = matcher(candidate)
                if value is not None:
                    values.append(value)
                    if not want_all:
                        break
            if values and not want_all:
                break

        if not values:
            return

        if used_alt:
            ctx.add_field_modifier(selector.field, "anchor_alt_used")
        if ambiguous and selector.region in regions.NON_NARROWING:
            # F12: the same label in the body and on the stub, with nothing to
            # say which one was meant.
            ctx.add_field_modifier(selector.field, "ambiguous_anchor")

        quality = (
            QUALITY_ANCHOR_ALT
            if used_alt
            else QUALITY_ANCHORED
            if selector.anchor is not None
            else QUALITY_REGION_ONLY
        )
        ctx.extracted.set(selector.field, values if want_all else values[0], quality)

    # -- row groups --------------------------------------------------------

    def _column_bounds(
        self, header_line: list[Word], headers: dict[str, str], page_width: float
    ) -> list[tuple[str, float, float]]:
        """Locate each column by its HEADER TEXT and derive its x range (F19).

        Never by index: U-PAK and Veritiv both reorder columns between revisions
        of the same template, and surviving that reorder is the whole point of
        matching on header text.

        The grid is built from **every** cell of the header row, not only the
        columns the persona declared, and boundaries fall midway between
        adjacent header cells. That distinction is load-bearing: a persona that
        declares only `amount` on a `DESCRIPTION | AMOUNT` table must still get
        the right-hand column. Deriving boundaries from the declared columns
        alone let that single column stretch across the full page width, so
        every cell of every row landed in it and `currency` matched none of them.

        The first and last header cells do extend to the page edges, so a long
        description or a right-aligned figure that overhangs its own header is
        still attributed to it.
        """
        cells = _cells(header_line)
        if not cells:
            return []

        grid: list[tuple[str, float, float]] = []
        for i, cell in enumerate(cells):
            left = 0.0 if i == 0 else (cells[i - 1][-1].x1 + cell[0].x0) / 2.0
            right = (
                page_width
                if i == len(cells) - 1
                else (cell[-1].x1 + cells[i + 1][0].x0) / 2.0
            )
            grid.append((" ".join(w.text for w in cell), left, right))

        bounds: list[tuple[str, float, float]] = []
        for column, header_text in headers.items():
            needle = _norm(header_text)
            column_cell = next((g for g in grid if _norm(g[0]) == needle), None)
            if column_cell is None:
                # A declared header may name part of a wider printed one -
                # "AMOUNT" against a cell printed "AMOUNT DUE".
                column_cell = next((g for g in grid if needle in _norm(g[0])), None)
            if column_cell is not None:
                bounds.append((column, column_cell[1], column_cell[2]))
        return bounds

    def _headerless_columns(self, selector: RowGroupSelector) -> tuple[str, str] | None:
        """(label column, amount column) for a header-less ladder, or None.

        A header-less row group must declare exactly two columns, one of them with
        a money pattern. That is not an arbitrary restriction - it is the whole
        shape: `Internet Charges 140.90` has a name and a number and nothing else,
        so a third column would have nothing to read.
        """
        if len(selector.columns) != 2:
            return None
        money = [n for n, p in selector.columns.items() if p in MONEY_PATTERNS]
        if len(money) != 1:
            return None
        amount = money[0]
        label = next(n for n in selector.columns if n != amount)
        return label, amount

    def _headerless_row(
        self,
        selector: RowGroupSelector,
        line: list[Word],
        matchers: dict[str, Any],
    ) -> dict[str, Any]:
        """Split one line as `label... amount`, the last money token being the amount.

        Used when a row group declares no `column_headers` and the table prints no
        header row - the shape Centracom and Comcast both use for their charges:

            Internet Charges                              140.90
            Internet Taxes, Surcharges, & Fees              0.20
            Comcast Business services                    217.89

        **This relies on the region being column-bounded.** On a two-column layout
        flattened into one line stream, a full-width region would put the other
        column's text into the label - `For All Billing Inquiries, call
        435-427-3331 Internet Taxes, Surcharges, & Fees`. `label-block` is the
        region that makes this honest.
        """
        names = self._headerless_columns(selector)
        if names is None:
            return {}
        label_column, amount_column = names
        matcher = matchers[amount_column]

        # Rightmost money token wins: a charge line reads name-then-number, and an
        # id or a date earlier on the line must not be mistaken for the amount.
        split_at = None
        for index in range(len(line) - 1, -1, -1):
            if matcher(line[index].text) is not None:
                split_at = index
                break
        if split_at is None or split_at == 0:
            return {}  # no amount, or no label: not a charge row

        label = " ".join(w.text for w in line[:split_at]).strip()
        if not label or _ROLLUP_LABEL.match(label):
            return {}

        amount = matcher(line[split_at].text)
        label_matcher = matchers[label_column]
        label_value = label_matcher(label)
        if label_value is None:
            return {}
        return {label_column: label_value, amount_column: amount}

    def _sub_group_value(
        self, sub: SubGroup, line: list[Word], deadline: float
    ) -> str | None:
        text = " ".join(w.text for w in line)
        if _norm(sub.anchor) not in _norm(text):
            return None
        if perf_counter() > deadline:
            return None
        value = patterns.resolve(sub.pattern)(text)
        return None if value is None else str(value)

    def _apply_row_group(self, ctx: JobContext, selector: RowGroupSelector) -> None:
        rows: list[dict[str, Any]] = []
        ctx.row_groups.setdefault(selector.row_group, rows)

        hits = self._find_anchors(ctx, selector.table_anchor)
        if not hits:
            return
        header = hits[0]
        page = self._page(ctx, header.page_number)
        if page is None:
            return

        anchor_line = next(
            (line for line in page.lines() if header.words[0] in line), list(header.words)
        )
        header_line = _header_band(page, anchor_line)
        headers = dict(selector.column_headers) or {name: name for name in selector.columns}
        bounds = self._column_bounds(header_line, headers, page.width)

        headerless = False
        if not bounds:
            if selector.column_headers:
                # Headers were declared and none of them matched a cell of the
                # header row. That is an authoring error, not a header-less table:
                # silently falling back would hide a typo behind plausible output.
                ctx.log(
                    f"s5a: row_group {selector.row_group!r} declared column_headers "
                    f"{sorted(selector.column_headers)} but none matched the "
                    f"{selector.table_anchor!r} row"
                )
                return
            headerless = self._headerless_columns(selector) is not None
            if not headerless:
                return

        region = selector.region or "line_items"
        spans = regions.resolve(region)(ctx.pages, ctx.page_meta, header.as_anchor())
        spans = tuple(s for s in spans if self._role(ctx, s.page_number) == "primary")

        matchers = {name: patterns.resolve(p) for name, p in selector.columns.items()}
        deadline = perf_counter() + self._budget_seconds

        # A line of an invoice's item table that carries no money value is not a
        # row: it is a wrapped description, a terms-and-conditions paragraph, or a
        # footer. `if row:` alone counted all of them - five T&C lines on Veritiv,
        # ten description wraps on Complete Beverage, one OCR fragment on Federal
        # Recycling.
        #
        # OPT-IN, and it has to be. F15 says a blank cell is a blank cell, and
        # `test_empty_cells_are_omitted_when_allowed` pins `BALANCE FORWARD` with no
        # amount as a legitimate row - EDCO's gold treats three such rows the same
        # way. Nothing in the geometry separates those from Veritiv's boilerplate,
        # so the persona has to say which shape its table is.
        #
        # Also guarded on the group DECLARING money, so setting the flag on a ladder
        # that has no money column is inert rather than emptying it.
        declared_money = {n for n, p in selector.columns.items() if p in MONEY_PATTERNS}
        money_columns = declared_money if selector.require_amount else set()

        # The column a subtotal would be a subtotal OF: the RIGHTMOST money column
        # in the resolved bounds, not the last declared one. Complete Beverage
        # declares both `unit_price` and `amount` as currency, and summing unit
        # prices would be arithmetic about nothing. Rightmost is the geometric
        # convention every invoice in the corpus follows for a line total, and it
        # does not depend on the order someone happened to write the JSON in.
        total_column: str | None = None
        if selector.stop_at_subtotal:
            money_bounds = [(c, left) for c, left, _ in bounds if c in declared_money]
            if money_bounds:
                total_column = max(money_bounds, key=lambda b: b[1])[0]
        running_sum = Decimal("0")

        # Vertical rhythm, seeded from the header-to-first-row gap.
        #
        # The pitch is the MEDIAN of the gaps seen so far, not the minimum. A
        # minimum lets one tight line - a wrapped description, an OCR fragment -
        # permanently redefine the table's rhythm as that outlier, which collapses
        # the break threshold to `TABLE_BREAK_FLOOR` and makes the next ordinary
        # gap look structural. Measured collapses on the corpus: Complete Beverage
        # 18.00pt -> 3.60, Federal Recycling 19.98 -> 4.68.
        #
        # A median keeps the estimate honest in both directions: it ignores a lone
        # outlier, and it still tracks a table that is genuinely tightly leaded,
        # because then the tight gaps ARE the majority.
        prev_y: float | None = header_line[0].y0
        gaps: list[float] = []

        for span in spans:
            for line in span.lines():
                if perf_counter() > deadline:
                    ctx.add_modifier("pattern_timeout")
                    ctx.log(f"s5a: pattern budget exceeded for row_group {selector.row_group!r}")
                    return

                y = line[0].y0
                if prev_y is not None and y > prev_y:
                    gap = y - prev_y
                    if not gaps:
                        gaps.append(gap)
                    else:
                        pitch = median(gaps)
                        if gap > max(TABLE_BREAK_FLOOR, pitch * TABLE_BREAK_FACTOR):
                            ctx.log(
                                f"s5a: row_group {selector.row_group!r} ended at a "
                                f"{gap:.0f}pt gap (row pitch {pitch:.0f}pt)"
                            )
                            return
                        gaps.append(gap)
                prev_y = y

                if selector.sub_group is not None:
                    value = self._sub_group_value(selector.sub_group, line, deadline)
                    if value is not None:
                        # An annotation line belongs to the row above it, not to
                        # a row of its own (F19's one permitted nesting level).
                        if rows:
                            rows[-1][selector.sub_group.field] = value
                        continue

                if headerless:
                    ladder_row = self._headerless_row(selector, line, matchers)
                    if ladder_row:
                        rows.append(ladder_row)
                    continue

                row: dict[str, Any] = {}
                for column, left, right in bounds:
                    matcher = matchers.get(column)
                    if matcher is None:
                        continue
                    cell = [w for w in line if left <= (w.x0 + w.x1) / 2.0 < right]
                    if not cell:
                        continue
                    text = " ".join(w.text for w in cell)
                    value = matcher(text)
                    if value is not None:
                        row[column] = value
                # A row that matched nothing is not a row - it is a page footer,
                # a continuation note, or the blank space below the table. Nor is a
                # row that matched no money on a table that prints money.
                if row and (not money_columns or not money_columns.isdisjoint(row)):
                    total = row.get(total_column) if total_column else None
                    if (
                        isinstance(total, Decimal)
                        # Two rows above, so a repeated service priced the same
                        # twice (`10.00 / 10.00`) is not read as its own total.
                        and len(rows) >= 2
                        # A credit memo nets to zero part-way down. Without this
                        # the next 0.00 row would look like the total so far.
                        and running_sum != 0
                        and total == running_sum
                    ):
                        ctx.log(
                            f"s5a: row_group {selector.row_group!r} ended at a "
                            f"subtotal row ({total_column}={total})"
                        )
                        return
                    rows.append(row)
                    if isinstance(total, Decimal):
                        running_sum += total

        # `row_count` is a stated expectation, not a filter. Truncating to `max`
        # would silently discard real rows, and raising would turn a layout
        # change into a pipeline error - so a violation is logged and left
        # visible for the gate to act on. There is no confidence modifier for it
        # in the closed section 5 enum, and inventing one here is exactly the
        # kind of quiet vocabulary growth the grammar forbids; wiring this to
        # review is C4's call, with a modifier added deliberately if it needs one.
        if selector.row_count is not None:
            low, high = selector.row_count
            if not low <= len(rows) <= high:
                ctx.log(
                    f"s5a: row_group {selector.row_group!r} found {len(rows)} rows, "
                    f"outside the declared range {low}-{high}"
                )

    # -- scanline ----------------------------------------------------------

    def _apply_scanline(self, ctx: JobContext, selector: ScanlineSelector) -> None:
        """Record the stub's digit run. Produces no field value, ever (F7).

        Not role-filtered: a scan line is scoring-only, so section 7's
        primary-page rule does not apply, and applying it would lose the stub on
        every multi-page bill whose final page is a continuation.

        The `asserts` are not consumed here either - corroborating an extracted
        value against these digits is `crosscheck_scanline`, a Stage 6 op.
        """
        spans = regions.resolve(selector.region)(ctx.pages, ctx.page_meta, None)
        if not spans:
            return

        # scanline.find works on pages, so each span is presented as a page
        # carrying only the words inside the region. This is what keeps the
        # region honest: a long digit run in the invoice body is not a scan line.
        as_pages: list[PageText] = []
        for span in spans:
            source_page = self._page(ctx, span.page_number)
            if source_page is None:
                continue
            as_pages.append(
                PageText(
                    page_number=span.page_number,
                    words=span.words,
                    width=source_page.width,
                    height=source_page.height,
                    source=span.source,
                    # Inherited from the real page, not recomputed from the
                    # span's (windowed) words — same reasoning as `Span`
                    # inheriting its page's tolerance in `regions._span`.
                    line_tolerance=source_page.line_tolerance,
                )
            )

        raw = scanline_mod.find(tuple(as_pages))
        if raw is not None:
            ctx.scanline = raw
