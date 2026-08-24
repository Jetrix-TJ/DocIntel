"""Read TXT/CSV/HTML directly into the same `PageText`/`PageMeta` shape every
other format produces - no OCR, no vision, no rendering, ever.

These three formats are already text (or, for HTML, text plus markup with no
genuine visual/layout signal worth preserving - see the Gemini-capability
research this project's Stage 2 architecture review is built on: Google's own
docs state non-PDF document types are reduced to plain text with formatting
discarded regardless). There is nothing to gain by routing them through
`extract.convert`'s renderer the way DOCX/XLSX genuinely need to, and nothing
to gain by asking a vision model to look at them either.

**Deliberately no synthetic 2D layout.** Each source line/row becomes one
`PageText` line, at a synthetic y-position spaced to survive `line_tolerance`
grouping, with tokens laid out left-to-right in reading order - the same
"give the grammar system geometry it can trust, don't invent structure a flow
format doesn't have" reasoning `extract.convert`'s own docstring already
applies to DOCX/XLSX. A `RowGroupSelector`'s column-boundary logic is
calibrated against MEASURED geometry from real rendered pages (F19); a CSV's
cells have no such geometry, so this module does not pretend they do. What
these formats get is text/pattern-based extraction (classification, anchors,
simple field patterns) - genuinely tabular selectors are not a use case this
module tries to serve.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from html.parser import HTMLParser

from docintel.core.geometry import line_tolerance
from docintel.core.models import PageMeta, PageText, Word

# Synthetic layout constants. Not measured against anything real (there is no
# real page these formats printed onto) - just spaced far enough apart that
# `core.geometry.group_lines`/`line_tolerance` never merges two distinct
# source lines into one, and far enough apart in x that word order survives.
ROW_HEIGHT = 12.0
CHAR_WIDTH = 6.0

# The `ctx.source_format` values `s2_filter.py` assigns for these suffixes
# (`.txt` -> "txt", `.csv` -> "csv", `.html`/`.htm` -> "html"). Exposed here,
# not re-derived from `convert.TEXT_SUFFIXES`, because a *suffix* set and a
# *source_format* set are different vocabularies (`.htm` and `.html` are two
# suffixes but one source_format) - `pipeline/stages/s5b_vision.py` reads
# this to skip vision entirely for these formats: none of the three carries
# visual content a vision model could add anything by looking at (see this
# module's own docstring), and Gemini does not accept any of them as a
# document input at all, so attempting the call would either waste a request
# or - with the real adapter - raise outright.
SOURCE_FORMATS: frozenset[str] = frozenset({"txt", "csv", "html"})

# Tags whose boundary must become a genuine line break (a new "row").
_LINE_BREAK_TAGS = frozenset({
    "p", "div", "br", "li", "tr", "table", "ul", "ol",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "hr", "thead", "tbody",
})
# Tags whose boundary must become at least a space - two adjacent table
# cells with no separator between them would otherwise glue into one
# unreadable token (`<td>Total</td><td>900.00</td>` -> "Total900.00"),
# which would defeat pattern matching on the merged result.
_CELL_BREAK_TAGS = frozenset({"td", "th"})
_SKIP_TAGS = frozenset({"script", "style"})


def load_document(path: str, suffix: str) -> tuple[tuple[PageText, ...], tuple[PageMeta, ...], str]:
    """The TXT/CSV/HTML counterpart to `normalize.load_document`/
    `normalize.load_image_document`: one native (never OCR'd) `PageText`,
    built from whichever reader `suffix` selects.

    `text_source` is always `"native"` - there is no OCR concept for an
    already-text format - and `PageMeta.image_count`/`annot_count` are always
    0, since none of these three formats can carry an embedded image or a PDF
    annotation object.
    """
    if suffix == ".csv":
        rows = _read_csv_rows(path)
    elif suffix in (".html", ".htm"):
        rows = _read_html_rows(path)
    else:
        rows = _read_text_rows(path)

    page = _build_page(rows)
    meta = (PageMeta(page_number=1, char_count=len(page.text), image_count=0, annot_count=0),)
    return (page,), meta, "native"


def _read_text_rows(path: str) -> list[list[str]]:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return [line.split() for line in fh.read().splitlines()]


def _read_csv_rows(path: str) -> list[list[str]]:
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        return [[cell for cell in row] for row in csv.reader(fh)]


def _read_html_rows(path: str) -> list[list[str]]:
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw_html = fh.read()
    extractor = _TextExtractor()
    extractor.feed(raw_html)
    return [line.split() for line in extractor.text().splitlines() if line.strip()]


class _TextExtractor(HTMLParser):
    """Strips markup down to text, inserting a line break at block-level tag
    boundaries so a page of `<p>`/`<div>`/`<tr>` elements doesn't collapse
    into one unreadable run - and dropping `<script>`/`<style>` bodies
    entirely, since neither is ever page content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        self._boundary(tag)

    def handle_startendtag(self, tag: str, attrs: object) -> None:
        self._boundary(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        self._boundary(tag)

    def _boundary(self, tag: str) -> None:
        if tag in _LINE_BREAK_TAGS:
            self._chunks.append("\n")
        elif tag in _CELL_BREAK_TAGS:
            self._chunks.append(" ")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


def _build_page(rows: Sequence[Sequence[str]]) -> PageText:
    words = _words_for_rows(rows)
    height = max(len(rows), 1) * ROW_HEIGHT
    longest_row_chars = max((sum(len(t) + 1 for t in row) for row in rows), default=1)
    width = max(longest_row_chars * CHAR_WIDTH, CHAR_WIDTH)
    return PageText(
        page_number=1,
        words=words,
        width=width,
        height=height,
        source="native",
        line_tolerance=line_tolerance(words),
    )


def _words_for_rows(rows: Sequence[Sequence[str]]) -> tuple[Word, ...]:
    """Lay out already-tokenized rows - each row becomes one `PageText` line,
    each element becomes one word - at synthetic positions: the same y within
    a row (spaced `ROW_HEIGHT` apart between rows, comfortably clear of
    `core.geometry.DEFAULT_TOLERANCE`/`MIN_TOLERANCE`), strictly increasing x
    within a row so word order survives `group_lines`' left-to-right sort.
    """
    words: list[Word] = []
    for row_index, row in enumerate(rows):
        y0 = float(row_index) * ROW_HEIGHT
        y1 = y0 + ROW_HEIGHT
        char_offset = 0
        for token in row:
            if not token:
                continue
            x0 = float(char_offset) * CHAR_WIDTH
            x1 = x0 + max(len(token), 1) * CHAR_WIDTH
            words.append(Word(text=token, x0=x0, y0=y0, x1=x1, y1=y1))
            char_offset += len(token) + 1
    return tuple(words)
