"""The region vocabulary is closed (selector-grammar.md section 2).

Geometry note that governs every test in this file: `pdf.read_pages` maps
pdfplumber's `top`/`bottom` onto `Word.y0`/`y1`, so **y increases downward**.
`y0 == 0` is the top edge of the page. `header-block` is therefore a `y0 <=`
test, and `remittance-block`'s bottom-30% fallback is a `y0 >=` test.
"""

from __future__ import annotations

import pytest

from docintel.core.errors import ValidationError
from docintel.core.models import PageMeta, PageText, Word
from docintel.grammar.regions import (
    ANCHOR_REQUIRED,
    NON_NARROWING,
    RESOLVERS,
    Anchor,
    Span,
    is_known,
    resolve,
)

WIDTH = 612.0
HEIGHT = 792.0


def _anchor(text: str, x0: float, y0: float, page_number: int = 1) -> Anchor:
    """A located anchor match. The page number is part of the location: a table
    anchor found on page 3 must not resolve its region against page 1."""
    return Anchor(
        word=Word(text=text, x0=x0, y0=y0, x1=x0 + 6.0 * len(text), y1=y0 + 10.0),
        page_number=page_number,
    )


def _page(number: int, *words: tuple[str, float, float], source: str = "native") -> PageText:
    """Build a page from (text, x0, y0) triples. Each word is 10pt tall."""
    return PageText(
        page_number=number,
        words=tuple(
            Word(text=t, x0=x, y0=y, x1=x + 6.0 * len(t), y1=y + 10.0) for t, x, y in words
        ),
        width=WIDTH,
        height=HEIGHT,
        source=source,  # type: ignore[arg-type]
    )


def _meta(*pages: PageText, roles: tuple[str, ...] | None = None) -> tuple[PageMeta, ...]:
    return tuple(
        PageMeta(
            page_number=p.page_number,
            char_count=sum(len(w.text) for w in p.words),
            image_count=0,
            annot_count=0,
            role=(roles[i] if roles else "primary"),  # type: ignore[arg-type]
        )
        for i, p in enumerate(pages)
    )


def _texts(spans: tuple[Span, ...]) -> list[str]:
    return [s.text for s in spans]


def _words_in(span: Span) -> set[str]:
    return {w.text for w in span.words}


# --------------------------------------------------------------------------
# The closed vocabulary itself
# --------------------------------------------------------------------------


def test_all_fifteen_regions_exist() -> None:
    """The region vocabulary is closed - selector-grammar.md section 2.

    Fourteen from the spec, plus `label-block` added after C5b: addresses were the
    single largest remaining class of failure and no existing region could reach
    them. `page:N` is parameterized and so is not a RESOLVERS key.
    """
    assert set(RESOLVERS) == {
        "last-page", "first-page", "any-page",
        "top-left", "top-right", "top-center",
        "header-block", "totals-block", "remittance-block",
        "last-table-row", "line_items",
        "near-anchor", "label-block", "same-row", "same-cell",
    }


def test_is_known_accepts_the_enum_and_parameterized_pages() -> None:
    assert is_known("header-block")
    assert is_known("page:1")
    assert is_known("page:17")


@pytest.mark.parametrize("bad", [
    "middle-ish", "page:0", "page:-1", "page:", "page:abc", "PAGE:1",
    "header_block", "", "footer-block",
])
def test_is_known_rejects_everything_else(bad: str) -> None:
    """V3's whole job. `page:0` is rejected because pages are 1-indexed."""
    assert not is_known(bad)


def test_resolve_rejects_an_unknown_region() -> None:
    with pytest.raises(ValidationError, match="region"):
        resolve("middle-ish")


def test_any_page_is_the_only_non_narrowing_region() -> None:
    """V6 keys off this: a bare-digit regex needs a region narrower than any-page."""
    assert NON_NARROWING == frozenset({"any-page"})


# --------------------------------------------------------------------------
# Span carries provenance
# --------------------------------------------------------------------------


def test_span_carries_page_number_source_and_bbox() -> None:
    p = _page(1, ("Total", 100.0, 700.0), source="ocr")
    (span,) = resolve("page:1")((p,), _meta(p), None)
    assert span.page_number == 1
    assert span.source == "ocr"
    assert span.bbox == (0.0, 0.0, WIDTH, HEIGHT)


def test_span_text_reads_in_visual_order() -> None:
    """Span mirrors PageText.lines(): top-to-bottom, then left-to-right."""
    p = _page(1, ("second", 10.0, 100.0), ("B", 200.0, 50.0), ("A", 10.0, 50.0))
    (span,) = resolve("first-page")((p,), _meta(p), None)
    assert span.text == "A B\nsecond"


def test_span_bbox_is_the_region_not_the_page() -> None:
    p = _page(1, ("hi", 10.0, 10.0))
    (span,) = resolve("header-block")((p,), _meta(p), None)
    assert span.bbox == (0.0, 0.0, WIDTH, HEIGHT * 0.25)


# --------------------------------------------------------------------------
# Whole-page regions
# --------------------------------------------------------------------------


def test_page_n_selects_that_page() -> None:
    p1, p2, p3 = _page(1, ("one", 10.0, 10.0)), _page(2, ("two", 10.0, 10.0)), _page(3, ("x", 1.0, 1.0))
    pages = (p1, p2, p3)
    (span,) = resolve("page:2")(pages, _meta(*pages), None)
    assert span.page_number == 2 and span.text == "two"


def test_page_n_out_of_range_is_an_empty_result_not_an_error() -> None:
    """A fingerprint drift that shortens the document is a field miss, not a crash."""
    p = _page(1, ("one", 10.0, 10.0))
    assert resolve("page:9")((p,), _meta(p), None) == ()


def test_first_and_last_page() -> None:
    p1, p2 = _page(1, ("one", 10.0, 10.0)), _page(2, ("two", 10.0, 10.0))
    pages = (p1, p2)
    assert _texts(resolve("first-page")(pages, _meta(*pages), None)) == ["one"]
    assert _texts(resolve("last-page")(pages, _meta(*pages), None)) == ["two"]


def test_any_page_returns_one_span_per_page_in_order() -> None:
    pages = (_page(1, ("a", 10.0, 10.0)), _page(2, ("b", 10.0, 10.0)), _page(3, ("c", 10.0, 10.0)))
    spans = resolve("any-page")(pages, _meta(*pages), None)
    assert [s.page_number for s in spans] == [1, 2, 3]
    assert _texts(spans) == ["a", "b", "c"]


def test_any_page_does_not_filter_supporting_pages() -> None:
    """Deliberate boundary: regions are pure geometry.

    Section 7 says field values never come off a `supporting` page, but that is
    the executor's rule to apply, not the region's - reference-pattern matching
    must still run across every page, and it uses these same resolvers.
    """
    pages = (_page(1, ("a", 10.0, 10.0)), _page(2, ("bol", 10.0, 10.0)))
    spans = resolve("any-page")(pages, _meta(*pages, roles=("primary", "supporting")), None)
    assert [s.page_number for s in spans] == [1, 2]


def test_regions_on_an_empty_document_return_nothing() -> None:
    for name in RESOLVERS:
        if name in ANCHOR_REQUIRED:
            continue
        assert RESOLVERS[name]((), (), None) == (), name


# --------------------------------------------------------------------------
# Geometric regions
# --------------------------------------------------------------------------


def test_header_block_is_the_top_quarter_of_page_one() -> None:
    p1 = _page(
        1,
        ("Account", 10.0, 20.0),          # in: y0 20 < 198
        ("Number", 90.0, 20.0),
        ("body", 10.0, 400.0),            # out: below the top quarter
    )
    p2 = _page(2, ("elsewhere", 10.0, 20.0))
    pages = (p1, p2)
    (span,) = resolve("header-block")(pages, _meta(*pages), None)
    assert span.page_number == 1
    assert _words_in(span) == {"Account", "Number"}


def test_header_block_boundary_is_inclusive() -> None:
    """A word sitting exactly on the 25% line is inside the header block."""
    p = _page(1, ("edge", 10.0, HEIGHT * 0.25))
    (span,) = resolve("header-block")((p,), _meta(p), None)
    assert _words_in(span) == {"edge"}


@pytest.mark.parametrize("region,expected", [
    ("top-left", {"L"}),
    ("top-center", {"C"}),
    ("top-right", {"R"}),
])
def test_top_thirds_split_the_top_third_horizontally(region: str, expected: set[str]) -> None:
    p = _page(
        1,
        ("L", 10.0, 20.0),      # x 10  -> left third   (0-204)
        ("C", 300.0, 20.0),     # x 300 -> center third (204-408)
        ("R", 500.0, 20.0),     # x 500 -> right third  (408-612)
        ("low", 10.0, 500.0),   # below the top third   -> excluded everywhere
    )
    (span,) = resolve(region)((p,), _meta(p), None)
    assert _words_in(span) == expected


def test_top_thirds_are_page_one_only() -> None:
    p1 = _page(1, ("first", 10.0, 20.0))
    p2 = _page(2, ("second", 10.0, 20.0))
    pages = (p1, p2)
    (span,) = resolve("top-left")(pages, _meta(*pages), None)
    assert span.page_number == 1 and _words_in(span) == {"first"}


# --------------------------------------------------------------------------
# totals-block - the U-PAK ordering rule (F9)
# --------------------------------------------------------------------------


def test_totals_block_searches_the_last_page_before_page_one() -> None:
    """F9, and the reason section 2 spells the order out.

    U-PAK's payable is on page 5 of 5; page 1 carries the `Please Pay` label
    with an EMPTY cell. Search page 1 first and you find the empty cell and
    report a confident miss.
    """
    p1 = _page(1, ("Please", 300.0, 600.0), ("Pay", 350.0, 600.0))
    p5 = _page(5, ("Please", 300.0, 600.0), ("Pay", 350.0, 600.0), ("14,789.77", 450.0, 600.0))
    pages = (p1, _page(2, ("x", 1.0, 1.0)), _page(3, ("x", 1.0, 1.0)), _page(4, ("x", 1.0, 1.0)), p5)
    spans = resolve("totals-block")(pages, _meta(*pages), None)
    assert [s.page_number for s in spans] == [5, 1]
    assert "14,789.77" in spans[0].text


def test_totals_block_on_a_one_page_document_yields_one_span() -> None:
    """Last page and page 1 are the same page; it must not be searched twice."""
    p = _page(1, ("Total", 300.0, 600.0), ("Amount", 350.0, 600.0), ("Due", 420.0, 600.0),
              ("367.96", 480.0, 600.0))
    spans = resolve("totals-block")((p,), _meta(p), None)
    assert [s.page_number for s in spans] == [1]


def test_totals_block_narrows_to_the_band_around_the_totals_label() -> None:
    """The stub below must stay out, or the scanline's trap value leaks in (F7)."""
    p = _page(
        1,
        ("Subtotal", 300.0, 100.0), ("298.34", 480.0, 100.0),   # far above: excluded
        ("Total", 300.0, 600.0), ("Amount", 350.0, 600.0), ("Due", 420.0, 600.0),
        ("367.96", 480.0, 600.0),
        ("25600770871000367962", 100.0, 760.0),                  # stub: excluded
    )
    (span,) = resolve("totals-block")((p,), _meta(p), None)
    assert "367.96" in span.text
    assert "298.34" not in span.text
    assert "25600770871000367962" not in span.text


def test_totals_block_uses_the_selectors_anchor_when_one_is_given() -> None:
    """An unusual totals phrasing still works if the persona names the anchor."""
    p = _page(1, ("Montant", 300.0, 600.0), ("1,177.70", 480.0, 600.0))
    (span,) = resolve("totals-block")((p,), _meta(p), _anchor("Montant", 300.0, 600.0))
    assert "1,177.70" in span.text


def test_totals_block_with_no_recognizable_label_falls_back_to_the_page_bottom() -> None:
    """Never an empty result: an unrecognized phrasing degrades to a wider
    search, which the confidence machinery can price, not to a certain miss."""
    p = _page(1, ("mystery", 300.0, 100.0), ("699.00", 480.0, 700.0))
    spans = resolve("totals-block")((p,), _meta(p), None)
    assert spans and "699.00" in spans[0].text


# --------------------------------------------------------------------------
# remittance-block
# --------------------------------------------------------------------------


@pytest.mark.parametrize("marker", [
    "DETACH", "Detach", "detach and return", "RETURN TOP PORTION", "Return top portion",
])
def test_remittance_block_starts_below_a_detach_marker(marker: str) -> None:
    words = [(tok, 10.0 + 60.0 * i, 500.0) for i, tok in enumerate(marker.split())]
    p = _page(
        1,
        ("above", 10.0, 100.0),
        *words,
        ("25600770871000367962", 100.0, 600.0),
    )
    (span,) = resolve("remittance-block")((p,), _meta(p), None)
    assert "25600770871000367962" in span.text
    assert "above" not in span.text


def test_remittance_block_falls_back_to_the_bottom_thirty_percent() -> None:
    p = _page(
        1,
        ("body", 10.0, 100.0),                       # y0 100  < 554.4 -> out
        ("stub", 10.0, 700.0),                       # y0 700 >= 554.4 -> in
    )
    (span,) = resolve("remittance-block")((p,), _meta(p), None)
    assert _words_in(span) == {"stub"}


def test_remittance_block_is_taken_from_the_last_page() -> None:
    """The stub is on the final page of a multi-page bill."""
    p1 = _page(1, ("body", 10.0, 700.0))
    p2 = _page(2, ("stub", 10.0, 700.0))
    pages = (p1, p2)
    (span,) = resolve("remittance-block")(pages, _meta(*pages), None)
    assert span.page_number == 2 and _words_in(span) == {"stub"}


# --------------------------------------------------------------------------
# Anchor-relative regions
# --------------------------------------------------------------------------


def test_anchor_required_regions_are_declared() -> None:
    assert ANCHOR_REQUIRED == frozenset({
        "near-anchor", "same-row", "same-cell", "line_items", "last-table-row",
        "label-block",
    })


@pytest.mark.parametrize("region", sorted(ANCHOR_REQUIRED))
def test_an_anchor_relative_region_without_an_anchor_is_an_error(region: str) -> None:
    p = _page(1, ("x", 10.0, 10.0))
    with pytest.raises(ValidationError, match="anchor"):
        resolve(region)((p,), _meta(p), None)


def test_near_anchor_is_300pt_right_and_40pt_below() -> None:
    anchor = _anchor("FOR", 100.0, 300.0)
    p = _page(
        1,
        ("FOR", 100.0, 300.0),
        ("value", 200.0, 300.0),        # right, same line          -> in
        ("below", 120.0, 335.0),        # 35pt below                -> in
        ("toofar", 460.0, 300.0),       # 360pt right of anchor x0  -> out
        ("waybelow", 120.0, 400.0),     # 100pt below               -> out
        ("left", 10.0, 300.0),          # left of the anchor        -> out
    )
    (span,) = resolve("near-anchor")((p,), _meta(p), anchor)
    assert _words_in(span) == {"FOR", "value", "below"}


def test_same_row_is_the_anchor_line_only() -> None:
    anchor = _anchor("Total", 300.0, 600.0)
    p = _page(
        1,
        ("Total", 300.0, 600.0),
        ("367.96", 480.0, 600.0),          # same line       -> in
        ("Subtotal", 300.0, 588.0),        # line above      -> out
        ("Tax", 300.0, 615.0),             # line below      -> out
    )
    (span,) = resolve("same-row")((p,), _meta(p), anchor)
    assert _words_in(span) == {"Total", "367.96"}


def test_same_row_tolerates_baseline_jitter() -> None:
    """OCR puts words on the same visual row at slightly different y."""
    anchor = _anchor("Total", 300.0, 600.0)
    p = _page(1, ("Total", 300.0, 600.0), ("367.96", 480.0, 602.0))
    (span,) = resolve("same-row")((p,), _meta(p), anchor)
    assert "367.96" in span.text


def test_same_cell_stops_at_a_column_gap() -> None:
    """A cell is the run of words around the anchor, bounded by a wide gap."""
    anchor = _anchor("BALANCE", 100.0, 400.0)
    p = _page(
        1,
        # The helper gives each character 6pt, so BALANCE spans x 100-142.
        ("BALANCE", 100.0, 400.0),
        ("FORWARD", 147.0, 400.0),      # 5pt gap   -> same cell
        ("298.34", 480.0, 400.0),       # 291pt gap -> a different cell
    )
    (span,) = resolve("same-cell")((p,), _meta(p), anchor)
    assert _words_in(span) == {"BALANCE", "FORWARD"}


def test_line_items_is_the_table_body_below_the_header_row() -> None:
    anchor = _anchor("DESCRIPTION", 50.0, 300.0)
    p = _page(
        1,
        ("Bill", 50.0, 200.0), ("To", 90.0, 200.0),           # above header -> out
        ("DESCRIPTION", 50.0, 300.0), ("CHARGES", 400.0, 300.0),  # header row -> out
        ("BALANCE", 50.0, 320.0), ("FORWARD", 110.0, 320.0), ("298.34", 400.0, 320.0),
        ("CURRENT", 50.0, 340.0), ("CHARGES:", 110.0, 340.0), ("69.62", 400.0, 340.0),
    )
    (span,) = resolve("line_items")((p,), _meta(p), anchor)
    assert "298.34" in span.text and "69.62" in span.text
    assert "Bill" not in span.text
    assert "DESCRIPTION" not in span.text


def test_last_table_row_is_the_final_body_row() -> None:
    anchor = _anchor("DESCRIPTION", 50.0, 300.0)
    p = _page(
        1,
        ("DESCRIPTION", 50.0, 300.0),
        ("BALANCE", 50.0, 320.0), ("298.34", 400.0, 320.0),
        ("CURRENT", 50.0, 340.0), ("69.62", 400.0, 340.0),
    )
    (span,) = resolve("last-table-row")((p,), _meta(p), anchor)
    assert _words_in(span) == {"CURRENT", "69.62"}


def test_line_items_uses_the_anchors_own_page() -> None:
    """A table anchor found on page 3 must not resolve against page 1."""
    p1 = _page(1, ("DESCRIPTION", 50.0, 300.0), ("wrong", 50.0, 320.0))
    p3 = _page(3, ("DESCRIPTION", 50.0, 300.0), ("right", 50.0, 320.0))
    pages = (p1, _page(2, ("x", 1.0, 1.0)), p3)
    anchor = _anchor("DESCRIPTION", 50.0, 300.0, page_number=3)
    spans = resolve("line_items")(pages, _meta(*pages), anchor)
    assert spans[0].page_number == 3
    assert "right" in spans[0].text and "wrong" not in spans[0].text


# --------------------------------------------------------------------------
# label-block - the anchor's column, down to the next blank line
# --------------------------------------------------------------------------


def test_label_block_reaches_a_whole_multi_line_address() -> None:
    """What `near-anchor` could not do. Its 40pt window covers the street line
    but not the city line beneath it, which is why every gold address failed."""
    p = _page(
        1,
        ("Bill", 30.0, 100.0), ("To", 60.0, 100.0),
        ("Northstar", 30.0, 114.0), ("Recycling", 95.0, 114.0),
        ("P.O.", 30.0, 128.0), ("Box", 60.0, 128.0), ("188", 90.0, 128.0),
        ("East", 30.0, 142.0), ("Longmeadow,", 60.0, 142.0), ("MA", 140.0, 142.0),
    )
    (span,) = resolve("label-block")((p,), _meta(p), _anchor("Bill To", 30.0, 100.0))
    assert "P.O. Box 188" in span.text
    assert "East Longmeadow, MA" in span.text


def test_label_block_stays_inside_its_own_column() -> None:
    """Every telecom bill in the corpus is a two-column layout flattened into one
    interleaved line stream, so a full-width region picks up the other column."""
    p = _page(
        1,
        ("Remit", 30.0, 100.0), ("To:", 70.0, 100.0), ("Total", 400.0, 100.0),
        ("CENTRACOM", 30.0, 114.0), ("Amount", 400.0, 114.0), ("Due", 460.0, 114.0),
        ("PO", 30.0, 128.0), ("BOX", 55.0, 128.0), ("7", 90.0, 128.0),
        ("33,876.40", 400.0, 128.0),
    )
    (span,) = resolve("label-block")((p,), _meta(p), _anchor("Remit To:", 30.0, 100.0))
    assert "CENTRACOM" in span.text
    assert "PO BOX 7" in span.text
    assert "33,876.40" not in span.text
    assert "Amount" not in span.text


def test_TWO_lines_blank_in_THIS_column_end_the_block() -> None:
    """Blank means blank in the column, not blank on the page - that is what makes
    the region column-aware rather than merely narrow.

    Two rows, not one. A single empty row is a GAP: on Comcast's bill the left
    column's `Account number` label is taller than the right column's content
    beside it, and a zero-tolerance rule stopped the charges ladder after its
    first row. See LABEL_BLOCK_BLANK_TOLERANCE.
    """
    p = _page(
        1,
        ("Bill", 30.0, 100.0), ("To", 60.0, 100.0),
        ("Acme", 30.0, 114.0), ("Widgets", 70.0, 114.0),
        # two consecutive rows with nothing in the LEFT column
        ("Page", 400.0, 128.0), ("1", 440.0, 128.0),
        ("of", 400.0, 142.0), ("6", 440.0, 142.0),
        # ...so this must NOT be reached
        ("SHOULD", 30.0, 156.0), ("NOT", 90.0, 156.0), ("APPEAR", 130.0, 156.0),
    )
    (span,) = resolve("label-block")((p,), _meta(p), _anchor("Bill To", 30.0, 100.0))
    assert "Acme Widgets" in span.text
    assert "SHOULD" not in span.text


def test_ONE_line_blank_in_this_column_is_only_a_gap() -> None:
    """Comcast's charges ladder, reduced. The row between the two charges carries
    only left-column content, and the ladder continues past it."""
    p = _page(
        1,
        ("New", 317.0, 93.0), ("charges", 339.0, 93.0),
        ("Comcast", 317.0, 107.0), ("services", 395.0, 107.0), ("217.89", 542.0, 107.0),
        ("Account", 35.0, 121.0), ("number", 80.0, 121.0),
        ("Taxes", 317.0, 135.0), ("fees", 361.0, 135.0), ("3.22", 552.0, 135.0),
    )
    (span,) = resolve("label-block")((p,), _meta(p), _anchor("New charges", 317.0, 93.0))
    assert "217.89" in span.text
    assert "3.22" in span.text
    assert "Account" not in span.text


def test_a_large_vertical_gap_ends_the_block() -> None:
    p = _page(
        1,
        ("Remit", 30.0, 100.0), ("To:", 70.0, 100.0),
        ("CENTRACOM", 30.0, 114.0),
        ("PO", 30.0, 128.0), ("BOX", 55.0, 128.0), ("7", 90.0, 128.0),
        ("UNRELATED", 30.0, 220.0),
    )
    (span,) = resolve("label-block")((p,), _meta(p), _anchor("Remit To:", 30.0, 100.0))
    assert "PO BOX 7" in span.text
    assert "UNRELATED" not in span.text


def test_label_block_is_capped_so_it_never_becomes_the_page() -> None:
    words = [("Bill", 30.0, 100.0), ("To", 60.0, 100.0)]
    for i in range(40):
        words.append((f"line{i}", 30.0, 114.0 + i * 14.0))
    p = _page(1, *words)
    (span,) = resolve("label-block")((p,), _meta(p), _anchor("Bill To", 30.0, 100.0))
    assert span.bbox[3] - span.bbox[1] <= 160.0


def test_label_block_needs_an_anchor() -> None:
    p = _page(1, ("x", 10.0, 10.0))
    with pytest.raises(ValidationError, match="anchor"):
        resolve("label-block")((p,), _meta(p), None)


def test_label_block_narrows_so_a_bare_digit_pattern_is_legal_in_it() -> None:
    assert "label-block" not in NON_NARROWING
