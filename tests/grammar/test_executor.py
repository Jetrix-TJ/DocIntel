"""The selector executor: turning a validated persona into extracted values.

Boundaries this suite pins, because each is a place the executor could
plausibly overreach:

* **It does not apply `adjust` ops.** Section 4 says ops run at Stage 6. The
  executor leaves them alone; `s6_capture` reads them straight off
  `ctx.persona`, so no intermediate "pending ops" state has to exist.
* **It does not decide confidence.** It records a `match_quality` per field and
  appends modifiers to `ctx.modifiers`. Turning those into numbers is Stage 6.
* **It does not enforce `required`.** A missing required field is a miss, priced
  at Stage 6 and routed at Stage 7 - not an exception here.
* **It applies the section 7 page-role rule**, which `regions.py` deliberately
  does not: field values never come off a `supporting` page.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import PATTERN_BUDGET_SECONDS, Executor
from docintel.grammar.schema import parse_persona

WIDTH = 612.0
HEIGHT = 792.0


def _page(number: int, *words: tuple[str, float, float], source: str = "native") -> PageText:
    """Build a page from (text, x0, y0) triples. Each word is 10pt tall, 6pt/char."""
    return PageText(
        page_number=number,
        words=tuple(
            Word(text=t, x0=x, y0=y, x1=x + 6.0 * len(t), y1=y + 10.0) for t, x, y in words
        ),
        width=WIDTH,
        height=HEIGHT,
        source=source,  # type: ignore[arg-type]
    )


def _ctx(*pages: PageText, roles: tuple[str, ...] | None = None) -> JobContext:
    meta = tuple(
        PageMeta(
            page_number=p.page_number,
            char_count=sum(len(w.text) for w in p.words),
            image_count=0,
            annot_count=0,
            role=(roles[i] if roles else "primary"),  # type: ignore[arg-type]
        )
        for i, p in enumerate(pages)
    )
    return JobContext(
        document_id="d1",
        source_path="x.pdf",
        pages=pages,
        page_meta=meta,
        doc_type="standard_invoice",
    )


def _persona(*selectors: dict[str, Any], **over: Any) -> Any:
    raw: dict[str, Any] = {
        "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
        "rule_version": "v1", "status": "draft",
        "field_selectors": list(selectors), "layout_fingerprint": {},
    }
    raw.update(over)
    return parse_persona(raw)


def _run(ctx: JobContext, *selectors: dict[str, Any]) -> JobContext:
    return Executor(_persona(*selectors)).apply(ctx)


# --------------------------------------------------------------------------
# Field selectors
# --------------------------------------------------------------------------


def test_extracts_a_currency_from_the_totals_block_via_its_anchor() -> None:
    ctx = _ctx(_page(
        1,
        ("Total", 300.0, 600.0), ("Amount", 350.0, 600.0), ("Due", 420.0, 600.0),
        ("367.96", 480.0, 600.0),
    ))
    ctx = _run(ctx, {"field": "total_printed", "anchor": "Total Amount Due",
                     "region": "totals-block", "pattern": "currency"})
    assert ctx.extracted.get("total_printed") == Decimal("367.96")
    assert ctx.extracted.match_quality["total_printed"] == 1.0


def test_a_missing_anchor_is_a_miss_not_an_error() -> None:
    ctx = _ctx(_page(1, ("Nothing", 10.0, 10.0), ("relevant", 80.0, 10.0)))
    ctx = _run(ctx, {"field": "total_printed", "anchor": "Total Amount Due",
                     "region": "totals-block", "pattern": "currency"})
    assert ctx.extracted.get("total_printed") is None
    assert "total_printed" not in ctx.extracted.values


def test_a_pattern_that_matches_nothing_is_a_miss() -> None:
    ctx = _ctx(_page(1, ("Total", 300.0, 600.0), ("Due", 350.0, 600.0),
                     ("PENDING", 480.0, 600.0)))
    ctx = _run(ctx, {"field": "total_printed", "anchor": "Total Due",
                     "region": "totals-block", "pattern": "currency"})
    assert ctx.extracted.get("total_printed") is None


def test_required_false_is_no_different_here() -> None:
    """`required` is priced at Stage 6 and routed at Stage 7, not enforced here."""
    ctx = _ctx(_page(1, ("x", 10.0, 10.0)))
    ctx = _run(ctx, {"field": "prior_balance", "anchor": "BALANCE FORWARD",
                     "region": "line_items", "pattern": "currency", "required": False})
    assert ctx.extracted.get("prior_balance") is None


def test_an_unanchored_selector_scores_lower_than_an_anchored_one() -> None:
    """Region-only evidence is weaker evidence, and says so."""
    ctx = _ctx(_page(1, ("699.00", 480.0, 700.0)))
    ctx = _run(ctx, {"field": "total_printed", "region": "totals-block",
                     "pattern": "currency"})
    assert ctx.extracted.get("total_printed") == Decimal("699.00")
    assert ctx.extracted.match_quality["total_printed"] == 0.90


def test_anchor_alts_are_tried_in_order_and_recorded() -> None:
    ctx = _ctx(_page(1, ("Amount", 300.0, 600.0), ("Due", 370.0, 600.0),
                     ("1,177.70", 480.0, 600.0)))
    ctx = _run(ctx, {"field": "total_printed", "anchor": "Total Amount Due",
                     "anchor_alts": ["Balance Due", "Amount Due"],
                     "region": "totals-block", "pattern": "currency"})
    assert ctx.extracted.get("total_printed") == Decimal("1,177.70".replace(",", ""))
    assert "anchor_alt_used" in ctx.modifiers
    assert ctx.extracted.match_quality["total_printed"] == 0.95


def test_the_primary_anchor_wins_and_sets_no_alt_modifier() -> None:
    ctx = _ctx(_page(1, ("Total", 300.0, 600.0), ("Amount", 350.0, 600.0),
                     ("Due", 420.0, 600.0), ("367.96", 480.0, 600.0)))
    ctx = _run(ctx, {"field": "total_printed", "anchor": "Total Amount Due",
                     "anchor_alts": ["Amount Due"],
                     "region": "totals-block", "pattern": "currency"})
    assert "anchor_alt_used" not in ctx.modifiers


def test_anchor_matching_is_case_insensitive() -> None:
    ctx = _ctx(_page(1, ("CURRENT", 50.0, 300.0), ("CHARGES:", 120.0, 300.0),
                     ("69.62", 400.0, 300.0)))
    ctx = _run(ctx, {"field": "current_charges", "anchor": "Current Charges:",
                     "region": "same-row", "pattern": "currency"})
    assert ctx.extracted.get("current_charges") == Decimal("69.62")


def test_a_repeated_anchor_on_any_page_is_flagged_ambiguous() -> None:
    """F12: the same label in the body and on the remittance stub."""
    ctx = _ctx(_page(
        1,
        ("Amount", 100.0, 200.0), ("Due", 170.0, 200.0), ("367.96", 300.0, 200.0),
        ("Amount", 100.0, 700.0), ("Due", 170.0, 700.0), ("367.96", 300.0, 700.0),
    ))
    ctx = _run(ctx, {"field": "total_printed", "anchor": "Amount Due",
                     "region": "any-page", "pattern": "currency"})
    assert "ambiguous_anchor" in ctx.modifiers


def test_a_repeated_anchor_with_a_narrowing_region_is_not_ambiguous() -> None:
    ctx = _ctx(_page(
        1,
        ("Amount", 100.0, 200.0), ("Due", 170.0, 200.0), ("367.96", 300.0, 200.0),
        ("Amount", 100.0, 700.0), ("Due", 170.0, 700.0), ("367.96", 300.0, 700.0),
    ))
    ctx = _run(ctx, {"field": "total_printed", "anchor": "Amount Due",
                     "region": "totals-block", "pattern": "currency"})
    assert "ambiguous_anchor" not in ctx.modifiers


def test_capture_all_matches_collects_from_every_page() -> None:
    ctx = _ctx(
        _page(1, ("NS", 10.0, 100.0), ("#", 30.0, 100.0), ("2561194", 50.0, 100.0)),
        _page(2, ("NS", 10.0, 100.0), ("#", 30.0, 100.0), ("2561195", 50.0, 100.0)),
    )
    ctx = _run(ctx, {"field": "seal_number", "region": "any-page",
                     "pattern": r"NS\s?#?\s?(\d{7})", "capture": "all_matches"})
    assert ctx.extracted.get("seal_number") == ["2561194", "2561195"]


def test_capture_first_stops_at_the_first_hit() -> None:
    ctx = _ctx(
        _page(1, ("NS", 10.0, 100.0), ("2561194", 50.0, 100.0)),
        _page(2, ("NS", 10.0, 100.0), ("2561195", 50.0, 100.0)),
    )
    ctx = _run(ctx, {"field": "seal_number", "region": "any-page",
                     "pattern": r"NS\s?(\d{7})"})
    assert ctx.extracted.get("seal_number") == "2561194"


def test_the_anchor_label_is_not_offered_as_the_value() -> None:
    """F14's anchor hazard: `H.S.T. # 123142812RT0001  2,325.69`.

    A text_block on the anchor's own region must yield the address, not the
    label that located it.
    """
    ctx = _ctx(_page(
        1,
        ("FOR", 100.0, 300.0), ("SERVICE", 130.0, 300.0), ("AT:", 190.0, 300.0),
        ("1600", 100.0, 315.0), ("Industrial", 140.0, 315.0), ("Rd", 210.0, 315.0),
    ))
    ctx = _run(ctx, {"field": "service_location", "anchor": "FOR SERVICE AT:",
                     "region": "near-anchor", "pattern": "text_block"})
    value = ctx.extracted.get("service_location")
    assert value is not None
    assert "FOR SERVICE AT:" not in value
    assert "1600 Industrial Rd" in value


def test_a_currency_is_found_even_when_no_column_gap_separates_it() -> None:
    """Candidate generation has to fall back from cells to individual words."""
    ctx = _ctx(_page(1, ("Total", 300.0, 600.0), ("Due", 336.0, 600.0),
                     ("367.96", 360.0, 600.0)))
    ctx = _run(ctx, {"field": "total_printed", "anchor": "Total Due",
                     "region": "same-row", "pattern": "currency"})
    assert ctx.extracted.get("total_printed") == Decimal("367.96")


def test_a_credit_keeps_its_sign(  ) -> None:
    """F4. An abs() anywhere in the extraction path inflates the payable."""
    ctx = _ctx(_page(1, ("Payments", 100.0, 400.0), ("Credits", 180.0, 400.0),
                     ("(249.84)", 400.0, 400.0)))
    ctx = _run(ctx, {"field": "payments_credits", "anchor": "Payments Credits",
                     "region": "same-row", "pattern": "currency"})
    assert ctx.extracted.get("payments_credits") == Decimal("-249.84")


# --------------------------------------------------------------------------
# Section 7: field values never come off a supporting page
# --------------------------------------------------------------------------


def test_a_field_value_is_never_taken_from_a_supporting_page() -> None:
    """F10: Complete Beverage is an invoice glued to 3 pages of handwritten BOL.

    A selector free to roam would eventually read a BOL scrawl as the total.
    `regions.py` does not filter roles - this is the executor's rule - so this
    test is the only thing standing between a supporting page and a field value.
    """
    ctx = _ctx(
        _page(1, ("Nothing", 10.0, 10.0)),
        _page(2, ("Total", 300.0, 600.0), ("Due", 350.0, 600.0), ("999.99", 480.0, 600.0)),
        roles=("primary", "supporting"),
    )
    ctx = _run(ctx, {"field": "total_printed", "anchor": "Total Due",
                     "region": "any-page", "pattern": "currency"})
    assert ctx.extracted.get("total_printed") is None


def test_a_field_value_is_taken_from_a_primary_page() -> None:
    """The mirror of the test above: role filtering must not block real work."""
    ctx = _ctx(
        _page(1, ("Nothing", 10.0, 10.0)),
        _page(2, ("Total", 300.0, 600.0), ("Due", 350.0, 600.0), ("999.99", 480.0, 600.0)),
        roles=("supporting", "primary"),
    )
    ctx = _run(ctx, {"field": "total_printed", "anchor": "Total Due",
                     "region": "any-page", "pattern": "currency"})
    assert ctx.extracted.get("total_printed") == Decimal("999.99")


def test_an_unknown_role_page_is_treated_as_supporting() -> None:
    """Section 7: "unknown" is treated as supporting, never as primary."""
    ctx = _ctx(
        _page(1, ("Total", 300.0, 600.0), ("Due", 350.0, 600.0), ("1.00", 480.0, 600.0)),
        _page(2, ("Total", 300.0, 600.0), ("Due", 350.0, 600.0), ("999.99", 480.0, 600.0)),
        roles=("primary", "unknown"),
    )
    ctx = _run(ctx, {"field": "total_printed", "anchor": "Total Due",
                     "region": "any-page", "pattern": "currency",
                     "capture": "all_matches"})
    assert ctx.extracted.get("total_printed") == [Decimal("1.00")]


# --------------------------------------------------------------------------
# Row groups - F19
# --------------------------------------------------------------------------


def _table_ctx() -> JobContext:
    return _ctx(_page(
        1,
        ("DESCRIPTION", 50.0, 300.0), ("QTY", 300.0, 300.0), ("AMOUNT", 400.0, 300.0),
        ("Swap", 50.0, 320.0), ("1", 300.0, 320.0), ("550.00", 400.0, 320.0),
        ("Haul", 50.0, 340.0), ("2", 300.0, 340.0), ("149.00", 400.0, 340.0),
    ))


def test_a_row_group_extracts_rows_keyed_by_column_name() -> None:
    ctx = _run(_table_ctx(), {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"description": "text", "quantity": "integer", "amount": "currency"},
        "column_headers": {"description": "DESCRIPTION", "quantity": "QTY",
                           "amount": "AMOUNT"},
    })
    assert ctx.row_groups["line_items"] == [
        {"description": "Swap", "quantity": 1, "amount": Decimal("550.00")},
        {"description": "Haul", "quantity": 2, "amount": Decimal("149.00")},
    ]


def test_columns_are_matched_by_header_text_not_by_index() -> None:
    """F19: U-PAK and Veritiv both reorder columns between template revisions.

    The same persona must survive the reorder, so this page puts AMOUNT before
    QTY while the persona declares them the other way round.
    """
    ctx = _ctx(_page(
        1,
        ("DESCRIPTION", 50.0, 300.0), ("AMOUNT", 300.0, 300.0), ("QTY", 450.0, 300.0),
        ("Swap", 50.0, 320.0), ("550.00", 300.0, 320.0), ("1", 450.0, 320.0),
    ))
    ctx = _run(ctx, {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"description": "text", "quantity": "integer", "amount": "currency"},
        "column_headers": {"description": "DESCRIPTION", "quantity": "QTY",
                           "amount": "AMOUNT"},
    })
    assert ctx.row_groups["line_items"] == [
        {"description": "Swap", "quantity": 1, "amount": Decimal("550.00")},
    ]


def test_column_headers_default_to_the_column_name() -> None:
    ctx = _run(_table_ctx(), {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"description": "text", "amount": "currency"},
    })
    rows = ctx.row_groups["line_items"]
    assert [r["amount"] for r in rows] == [Decimal("550.00"), Decimal("149.00")]


def test_empty_cells_are_omitted_when_allowed() -> None:
    """F15: a blank cell is a blank cell, not a zero."""
    ctx = _ctx(_page(
        1,
        ("DESCRIPTION", 50.0, 300.0), ("AMOUNT", 400.0, 300.0),
        ("BALANCE", 50.0, 320.0), ("FORWARD", 110.0, 320.0),
        ("Haul", 50.0, 340.0), ("149.00", 400.0, 340.0),
    ))
    ctx = _run(ctx, {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"description": "text", "amount": "currency"},
        "allow_empty_cells": True,
    })
    rows = ctx.row_groups["line_items"]
    assert rows[0] == {"description": "BALANCE FORWARD"}
    assert "amount" not in rows[0]
    assert rows[1]["amount"] == Decimal("149.00")


def test_a_row_with_no_matching_cell_at_all_is_dropped() -> None:
    """A page footer below the table must not become a line item."""
    ctx = _ctx(_page(
        1,
        ("DESCRIPTION", 50.0, 300.0), ("AMOUNT", 400.0, 300.0),
        ("Haul", 50.0, 320.0), ("149.00", 400.0, 320.0),
        ("~~~~", 250.0, 700.0),
    ))
    ctx = _run(ctx, {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"amount": "currency"},
    })
    assert ctx.row_groups["line_items"] == [{"amount": Decimal("149.00")}]


def test_a_table_ends_at_a_structural_gap_not_at_the_page_foot() -> None:
    """The universal case, not a corner case.

    Every invoice in the corpus prints a totals block below its line-item
    table, and five print a remittance stub below that. The `line_items` region
    runs to the foot of the page, so without a break rule the first row group
    swallows the total as an extra row and the F8 closure check it exists to
    support becomes meaningless.
    """
    ctx = _ctx(_page(
        1,
        ("DESCRIPTION", 50.0, 100.0), ("AMOUNT", 400.0, 100.0),
        ("Swap", 50.0, 120.0), ("550.00", 400.0, 120.0),
        ("Haul", 50.0, 140.0), ("149.00", 400.0, 140.0),
        # 120pt below the last row: the totals block, not a seventh line item
        ("Total", 300.0, 260.0), ("699.00", 400.0, 260.0),
        ("25600770871000367962", 100.0, 700.0),
    ))
    ctx = _run(ctx, {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"description": "text", "amount": "currency"},
    })
    assert ctx.row_groups["line_items"] == [
        {"description": "Swap", "amount": Decimal("550.00")},
        {"description": "Haul", "amount": Decimal("149.00")},
    ]


def test_a_uniformly_spaced_table_is_not_broken_up() -> None:
    """The mirror: the break rule must not truncate a long ordinary table."""
    words: list[tuple[str, float, float]] = [
        ("DESCRIPTION", 50.0, 100.0), ("AMOUNT", 400.0, 100.0),
    ]
    for i in range(20):
        y = 120.0 + i * 20.0
        words += [(f"Item{i}", 50.0, y), (f"{i + 1}.00", 400.0, y)]
    ctx = _run(_ctx(_page(1, *words)), {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"description": "text", "amount": "currency"},
    })
    assert len(ctx.row_groups["line_items"]) == 20


def test_a_tightly_leaded_table_survives_a_modest_gap() -> None:
    """A 6pt row pitch must not make a 15pt gap look structural - hence the floor."""
    words: list[tuple[str, float, float]] = [
        ("DESCRIPTION", 50.0, 100.0), ("AMOUNT", 400.0, 100.0),
    ]
    for i, y in enumerate((106.0, 112.0, 127.0, 133.0)):
        words += [(f"Item{i}", 50.0, y), (f"{i + 1}.00", 400.0, y)]
    ctx = _run(_ctx(_page(1, *words)), {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"description": "text", "amount": "currency"},
    })
    assert len(ctx.row_groups["line_items"]) == 4


def test_a_label_block_stops_at_the_column_gutter() -> None:
    """`LABEL_BLOCK_RIGHT = 300.0` is a constant, and every telecom bill here is a
    two-column layout flattened into one interleaved line stream - so on Centracom
    the window reached straight through 224pt of whitespace into the next column and
    `vendor_address` came back as
    'Balance, PO BOX 7, Payments, FAIRVIEW UT 84629, Previous, Please, ...'.

    The block's own rows are where the gutter is unambiguous: projecting word
    occupancy across just those lines leaves one wide empty run, and that is the
    real column edge.
    """
    ctx = _ctx(_page(
        1,
        ("ACME", 50.0, 100.0),
        ("PO", 50.0, 112.0), ("BOX", 70.0, 112.0), ("7", 95.0, 112.0),
        ("Balance", 300.0, 112.0),                    # other column, inside 300pt
        ("FAIRVIEW", 50.0, 124.0), ("Payments", 300.0, 124.0),
    ))
    ctx = _run(ctx, {
        "field": "vendor_address", "anchor": "ACME", "region": "label-block",
        "pattern": "text_block",
    })
    # `adjust` ops run at Stage 6, so the executor's own output is newline-joined.
    assert ctx.extracted.get("vendor_address") == "PO BOX 7\nFAIRVIEW"


def test_a_wide_single_column_block_is_not_narrowed() -> None:
    """The guard. Gutter detection may only ever NARROW the window, and it must not
    fire on ordinary word spacing inside one column - an address line's internal
    gaps are a few points, well under a column's worth."""
    ctx = _ctx(_page(
        1,
        ("ACME", 50.0, 100.0),
        ("ATTN:", 50.0, 112.0), ("Support", 85.0, 112.0), ("Services", 140.0, 112.0),
        ("131", 50.0, 124.0), ("W", 70.0, 124.0), ("Matthews", 85.0, 124.0),
        ("St", 140.0, 124.0),
    ))
    ctx = _run(ctx, {
        "field": "return_address", "anchor": "ACME", "region": "label-block",
        "pattern": "text_block",
    })
    assert ctx.extracted.get("return_address") == (
        "ATTN: Support Services\n131 W Matthews St"
    )


def test_an_anchor_can_target_its_last_occurrence() -> None:
    """`_resolve_anchor` returns `hits[0]`, so a label printed more than once always
    resolves to the first one in reading order. Four remit addresses fail purely for
    this reason: EDCO prints its own name 3x, `VERITIV OPERATING COMPANY` and
    `Windstream` twice each, and the occurrence above the remittance block is the
    LAST one - so the correct anchor exists and is simply unreachable.
    """
    ctx = _ctx(_page(
        1,
        ("ACME", 50.0, 100.0), ("letterhead", 50.0, 112.0),
        ("ACME", 50.0, 300.0), ("PO", 50.0, 312.0), ("BOX", 70.0, 312.0), ("7", 95.0, 312.0),
    ))
    ctx = _run(ctx, {
        "field": "remit_address", "anchor": "ACME", "region": "label-block",
        "pattern": "text_block", "anchor_occurrence": "last",
        "adjust": ["join_lines_comma"],
    })
    assert ctx.extracted.get("remit_address") == "PO BOX 7"


def test_the_default_occurrence_is_still_the_first() -> None:
    """Pinned, because flipping the default would silently move every anchored
    selector in both packs."""
    ctx = _ctx(_page(
        1,
        ("ACME", 50.0, 100.0), ("letterhead", 50.0, 112.0),
        ("ACME", 50.0, 300.0), ("PO", 50.0, 312.0), ("BOX", 70.0, 312.0), ("7", 95.0, 312.0),
    ))
    ctx = _run(ctx, {
        "field": "remit_address", "anchor": "ACME", "region": "label-block",
        "pattern": "text_block",
    })
    assert ctx.extracted.get("remit_address") == "letterhead"


# --------------------------------------------------------------------------
# anchor_occurrence: "mid_line" - the remittance stub's own occurrence (8c)
# --------------------------------------------------------------------------
#
# `first` and `last` are ordinal, so they can only be right by count. EDCO prints
# `EDCO WASTE & RECYCLING SERVICE` three times on its primary page and the
# remittance block is under the MIDDLE one, which neither ordinal reaches - which
# is why its `remit_address` was stuck anchoring on `P.O. BOX 5488`, a value in
# the anchor.
#
# Measured, all three occurrences have an address block under them (letterhead,
# remittance stub, and the "PLEASE MAIL ALL OTHER CORRESPONDENCE TO" notice), so
# "the occurrence with a block under it" cannot separate them either. What does
# separate them is whether the name BEGINS its visual line:
#
#     EDCO WASTE & RECYCLING SERVICE                     <- letterhead, begins
#     NORTHSTAR RECYCLING   EDCO WASTE & RECYCLING SERVICE  <- stub, does NOT
#     EDCO WASTE & RECYCLING SERVICE FOR SERVICE AT:     <- notice, begins
#
# and the intended cause is that a payment stub prints remit-to in the right-hand
# column beside bill-to in the left, so in the flattened line stream the stub's
# payee name has the other column's text before it, while a letterhead, a section
# heading and a prose sentence all start their line.
#
# Measured on the three GOLD documents that print their payee more than once
# (EDCO, Veritiv, Windstream), where it selects the stub occurrence. That is the
# extent of the claim: it is a property of those layouts, not of the personas.
# OCR line-grouping breaks it on a real Windstream sample, which is why
# `mid_line` is withheld on OCR-sourced documents - see
# `test_mid_line_never_answers_on_an_ocr_sourced_document`.


def test_mid_line_reaches_the_middle_of_three_occurrences() -> None:
    """The EDCO shape, which no ordinal can express.

    Three occurrences, each with a real address block beneath it, and the wanted
    one is neither first nor last. It is the only one printed beside another
    column rather than starting its own line.
    """
    ctx = _ctx(_page(
        1,
        # 1: letterhead, begins its line, with an address under it
        ("ACME", 50.0, 100.0),
        ("224", 50.0, 112.0), ("LAS", 75.0, 112.0), ("POSAS", 100.0, 112.0),
        # 2: the stub - bill-to on the left, ACME beside it on the right
        ("CUSTOMER", 50.0, 300.0), ("ACME", 300.0, 300.0),
        ("PO", 50.0, 312.0), ("BOX", 70.0, 312.0), ("188", 95.0, 312.0),
        ("PO", 300.0, 312.0), ("BOX", 320.0, 312.0), ("5488", 345.0, 312.0),
        # 3: the correspondence notice, begins its line, address under it
        ("ACME", 50.0, 500.0), ("MAIL", 90.0, 500.0), ("TO:", 130.0, 500.0),
        ("224", 50.0, 512.0), ("LAS", 75.0, 512.0), ("POSAS", 100.0, 512.0),
    ))
    ctx = _run(ctx, {
        "field": "remit_address", "anchor": "ACME", "region": "label-block",
        "pattern": "text_block", "anchor_occurrence": "mid_line",
    })
    assert ctx.extracted.get("remit_address") == "PO BOX 5488"


def test_mid_line_ignores_an_occurrence_that_begins_a_boilerplate_line() -> None:
    """Why this is more robust than `last`, not merely different.

    `last` is one punctuation change away from a footer: `_norm` strips a trailing
    colon but not a comma or period, so `Veritiv,` and `Windstream.` miss today
    purely by luck. Every such occurrence is a brand name STARTING a sentence, so
    `mid_line` excludes the whole class by construction rather than relying on the
    stub happening to be printed last.
    """
    ctx = _ctx(_page(
        1,
        ("CUSTOMER", 50.0, 100.0), ("ACME", 300.0, 100.0),
        ("PO", 300.0, 112.0), ("BOX", 320.0, 112.0), ("5488", 345.0, 112.0),
        # a later boilerplate line that STARTS with the anchor: `last` would
        # take this one and read the paragraph under it as an address.
        ("ACME", 50.0, 400.0), ("reserves", 90.0, 400.0), ("the", 150.0, 400.0),
        ("right", 50.0, 412.0), ("to", 90.0, 412.0), ("amend", 115.0, 412.0),
    ))
    ctx = _run(ctx, {
        "field": "remit_address", "anchor": "ACME", "region": "label-block",
        "pattern": "text_block", "anchor_occurrence": "mid_line",
    })
    assert ctx.extracted.get("remit_address") == "PO BOX 5488"


def test_mid_line_takes_the_last_qualifying_occurrence() -> None:
    """Two occurrences printed beside another column: the later one wins.

    Measured on the drift case the plan warns about - if `_norm` were changed to
    strip a trailing period, Windstream's `Detach and return this payment slip
    with your check payable to OKLAHOMA WINDSTREAM, LLC.` would start matching,
    and it is mid-line too. On that page the boilerplate mention precedes the
    stub, so `last` among the qualifying occurrences is the safer tiebreak.

    Note this is a tiebreak, not the mechanism: on all three real personas
    exactly one occurrence qualifies today. It is also why `mid_line` is not a
    universal replacement for `last` - see `FieldSelector.anchor_occurrence` for
    the OCR measurement that keeps Veritiv and Windstream on `last`.
    """
    ctx = _ctx(_page(
        1,
        ("payable", 50.0, 100.0), ("to", 100.0, 100.0), ("ACME", 130.0, 100.0),
        ("Amount", 130.0, 112.0), ("Due", 180.0, 112.0),
        ("CUSTOMER", 50.0, 400.0), ("ACME", 300.0, 400.0),
        ("PO", 300.0, 412.0), ("BOX", 320.0, 412.0), ("5488", 345.0, 412.0),
    ))
    ctx = _run(ctx, {
        "field": "remit_address", "anchor": "ACME", "region": "label-block",
        "pattern": "text_block", "anchor_occurrence": "mid_line",
    })
    assert ctx.extracted.get("remit_address") == "PO BOX 5488"


def test_mid_line_never_answers_on_an_ocr_sourced_document() -> None:
    """The guard that makes `mid_line` safe, and the only thing that does.

    `mid_line` reads a fact about visual line bands - the payee printed beside the
    bill-to column - and OCR line-grouping does not preserve it. Measured on the
    real OCR-sourced `Windstream_021942648_09022025`: the stub's `WINDSTREAM` came
    back alone on its line, so `mid_line` skipped it and resolved to an earlier
    mid-line prose mention (`Please call Kinetic Susiness by Windstream or visit
    Sur website.`), turning a correct `PO BOX 9001908, LOUISVILLE, KY 40290-1908`
    into `by`. That is a wrong remit address on a payment, arriving silently.

    A persona's `layout_fingerprint.text_source` is NOT what protects this: no
    runtime code reads any fingerprint member (it is validated at write time and
    never consulted), and `windstream.json` itself declares `"native"` while four
    of its five real samples are OCR-sourced. `ctx.text_source` is the signal that
    actually exists at run time - the same one `s6_capture` and the Northstar
    ladder key off.

    The fixture below is that shape: the wanted occurrence has been grouped onto
    its own line, so the only mid-line candidate left is boilerplate whose block is
    not an address.
    """
    words = (
        # boilerplate, mid-line, with something that is not an address under it
        ("Please", 50.0, 100.0), ("call", 100.0, 100.0), ("ACME", 140.0, 100.0),
        ("or", 140.0, 112.0), ("visit", 165.0, 112.0),
        # the stub's own occurrence, grouped alone on its line by OCR
        ("ACME", 300.0, 400.0),
        ("PO", 300.0, 412.0), ("BOX", 320.0, 412.0), ("5488", 345.0, 412.0),
    )
    selector = {
        "field": "remit_address", "anchor": "ACME", "region": "label-block",
        "pattern": "text_block", "anchor_occurrence": "mid_line",
    }

    # Native: the boilerplate mention is the only mid-line candidate, so this is
    # exactly the wrong answer the guard exists to suppress.
    native = _run(_ctx(_page(1, *words)), selector)
    assert native.extracted.get("remit_address") == "or visit"

    ocr = _ctx(_page(1, *words, source="ocr"))
    ocr.text_source = "ocr"
    ocr = _run(ocr, selector)
    assert ocr.extracted.get("remit_address") is None


def test_the_ordinal_occurrence_modes_still_work_on_ocr() -> None:
    """The guard is scoped to `mid_line` alone.

    `first` and `last` are ordinal, so they do not depend on line grouping and
    have no reason to be withheld - `windstream`'s `remit_address` reads correctly
    off `last` on that same OCR'd document, which is why it keeps `last`.
    """
    ocr = _ctx(_page(
        1,
        ("ACME", 50.0, 100.0), ("letterhead", 90.0, 100.0),
        ("ACME", 50.0, 300.0),
        ("PO", 50.0, 312.0), ("BOX", 70.0, 312.0), ("5488", 95.0, 312.0),
        source="ocr",
    ))
    ocr.text_source = "ocr"
    ocr = _run(ocr, {
        "field": "remit_address", "anchor": "ACME", "region": "label-block",
        "pattern": "text_block", "anchor_occurrence": "last",
    })
    assert ocr.extracted.get("remit_address") == "PO BOX 5488"


def test_mid_line_with_no_qualifying_occurrence_is_an_ordinary_miss() -> None:
    """A visible empty field, never a fallback to an occurrence that begins a line.

    If EDCO's bill-to block ever shifted a line so the payee no longer sat beside
    it, the honest answer is nothing: `core.coverage` escalates the empty required
    field, whereas silently taking the letterhead would put the vendor's street
    address on a payment.
    """
    ctx = _ctx(_page(
        1,
        ("ACME", 50.0, 100.0),
        ("PO", 50.0, 112.0), ("BOX", 70.0, 112.0), ("5488", 95.0, 112.0),
    ))
    ctx = _run(ctx, {
        "field": "remit_address", "anchor": "ACME", "region": "label-block",
        "pattern": "text_block", "anchor_occurrence": "mid_line",
    })
    assert ctx.extracted.get("remit_address") is None


def test_mid_line_falls_through_to_anchor_alts() -> None:
    """"No occurrence qualified" is the same kind of nothing as "the label is
    absent", so the declared alternates still get their turn."""
    ctx = _ctx(_page(
        1,
        # the declared anchor appears, but only at the head of a line
        ("ACME", 50.0, 100.0), ("letterhead", 90.0, 100.0),
        # the alternate is the rendering used in the stub, beside the bill-to
        ("CUSTOMER", 50.0, 300.0), ("ACME-CORP", 300.0, 300.0),
        ("PO", 300.0, 312.0), ("BOX", 320.0, 312.0), ("5488", 345.0, 312.0),
    ))
    ctx = _run(ctx, {
        "field": "remit_address", "anchor": "ACME", "anchor_alts": ["ACME-CORP"],
        "region": "label-block", "pattern": "text_block",
        "anchor_occurrence": "mid_line",
    })
    assert ctx.extracted.get("remit_address") == "PO BOX 5488"


def test_a_row_equal_to_the_running_sum_ends_the_table() -> None:
    """Every invoice in the corpus prints a totals row below its items, and on
    Complete Beverage and Federal Recycling it is TIGHTER than the body it follows
    (16.56pt against an 18.00pt pitch; 16.92 against 19.98), so no gap multiple
    greater than 1 can ever terminate it. Arithmetic can: the row's amount equals
    the sum of the rows above it.

    Measured: CB's 12 gold rows sum to exactly 1177.70 and FR's 10 to exactly
    481.20 - which are precisely the values being swallowed as a 13th and 11th row.
    """
    words: list[tuple[str, float, float]] = [
        ("DESCRIPTION", 50.0, 100.0), ("AMOUNT", 400.0, 100.0),
        ("One", 50.0, 120.0), ("10.00", 400.0, 120.0),
        ("Two", 50.0, 140.0), ("15.00", 400.0, 140.0),
        ("Three", 50.0, 160.0), ("5.00", 400.0, 160.0),
        ("TOTAL", 50.0, 180.0), ("30.00", 400.0, 180.0),
    ]
    ctx = _run(_ctx(_page(1, *words)), {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"description": "text", "amount": "currency"},
        "stop_at_subtotal": True,
    })
    assert [str(r["amount"]) for r in ctx.row_groups["line_items"]] == [
        "10.00", "15.00", "5.00",
    ]


def test_the_subtotal_rule_needs_at_least_two_rows_above_it() -> None:
    """A two-row table whose second row happens to equal the first is a coincidence,
    not a total - and `10.00 / 10.00` is an ordinary shape on a repeated service."""
    words: list[tuple[str, float, float]] = [
        ("DESCRIPTION", 50.0, 100.0), ("AMOUNT", 400.0, 100.0),
        ("One", 50.0, 120.0), ("10.00", 400.0, 120.0),
        ("Two", 50.0, 140.0), ("10.00", 400.0, 140.0),
    ]
    ctx = _run(_ctx(_page(1, *words)), {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"description": "text", "amount": "currency"},
        "stop_at_subtotal": True,
    })
    assert len(ctx.row_groups["line_items"]) == 2


def test_a_zero_running_sum_never_terminates_the_table() -> None:
    """A credit memo nets to zero part-way through. Without the guard the next 0.00
    row would look like the total of everything above it."""
    words: list[tuple[str, float, float]] = [
        ("DESCRIPTION", 50.0, 100.0), ("AMOUNT", 400.0, 100.0),
        ("Charge", 50.0, 120.0), ("50.00", 400.0, 120.0),
        ("Credit", 50.0, 140.0), ("-50.00", 400.0, 140.0),
        ("Nil", 50.0, 160.0), ("0.00", 400.0, 160.0),
        ("After", 50.0, 180.0), ("7.00", 400.0, 180.0),
    ]
    ctx = _run(_ctx(_page(1, *words)), {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"description": "text", "amount": "currency_signed"},
        "stop_at_subtotal": True,
    })
    assert len(ctx.row_groups["line_items"]) == 4


def test_a_line_matching_only_a_text_column_is_not_a_row() -> None:
    """Wrapped descriptions and boilerplate match the text column and nothing else.
    `if row:` counted them, so Veritiv's five terms-and-conditions lines became
    five line items.

    Opt-in, because F15's `BALANCE FORWARD` row is the same shape and IS a row -
    see `test_empty_cells_are_omitted_when_allowed`, which pins the default.
    """
    words: list[tuple[str, float, float]] = [
        ("DESCRIPTION", 50.0, 100.0), ("AMOUNT", 400.0, 100.0),
        ("Real", 50.0, 120.0), ("10.00", 400.0, 120.0),
        ("wrapped", 50.0, 140.0),                       # description only - not a row
        ("Also", 50.0, 160.0), ("20.00", 400.0, 160.0),
    ]
    ctx = _run(_ctx(_page(1, *words)), {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"description": "text", "amount": "currency"},
        "require_amount": True,
    })
    assert [r.get("description") for r in ctx.row_groups["line_items"]] == ["Real", "Also"]


def test_the_same_table_without_the_flag_keeps_the_text_only_line() -> None:
    """The default is F15's, not the new rule's. Flipping the default would silently
    drop EDCO's three blank-charge rows the moment its `row_group` is authored."""
    words: list[tuple[str, float, float]] = [
        ("DESCRIPTION", 50.0, 100.0), ("AMOUNT", 400.0, 100.0),
        ("Real", 50.0, 120.0), ("10.00", 400.0, 120.0),
        ("wrapped", 50.0, 140.0),
    ]
    ctx = _run(_ctx(_page(1, *words)), {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"description": "text", "amount": "currency"},
    })
    assert [r.get("description") for r in ctx.row_groups["line_items"]] == ["Real", "wrapped"]


def test_require_amount_is_inert_on_a_group_with_no_money_column() -> None:
    """U-PAK's `sub_account` group declares no money column. Setting the flag there
    must not empty it."""
    words: list[tuple[str, float, float]] = [
        ("CODE", 50.0, 100.0), ("NAME", 300.0, 100.0),
        ("A1", 50.0, 120.0), ("Acme", 300.0, 120.0),
        ("B2", 50.0, 140.0),
    ]
    ctx = _run(_ctx(_page(1, *words)), {
        "row_group": "accounts", "table_anchor": "CODE",
        "columns": {"code": "text", "name": "text"},
        "column_headers": {"code": "CODE", "name": "NAME"},
        "require_amount": True,
    })
    assert len(ctx.row_groups["accounts"]) == 2


def test_a_header_wrapped_onto_the_line_above_still_binds_its_column() -> None:
    """Veritiv prints `Extended Price` as two lines: `Extended` 8.26pt above the
    row the `Product No.` anchor sits on. `page.lines()` splits at
    `_LINE_TOLERANCE = 3.0`, so `_column_bounds` never saw the amount header at
    all - and because `bounds` came back non-empty (item_code alone) the declared-
    header authoring error did not fire either. It silently proceeded one-column
    and matched no amounts.
    """
    words: list[tuple[str, float, float]] = [
        ("Extended", 500.0, 92.0),                     # wrapped header, 8pt above
        ("Product", 50.0, 100.0), ("No.", 95.0, 100.0), ("Price", 505.0, 100.0),
    ]
    for i, y in enumerate((120.0, 140.0)):
        words += [(f"Item{i}", 50.0, y), ("4608.45", 510.0, y)]
    ctx = _run(_ctx(_page(1, *words)), {
        "row_group": "line_items", "table_anchor": "Product No.",
        "columns": {"item_code": "text", "amount": "currency"},
        "column_headers": {"item_code": "Product No.", "amount": "Extended"},
    })
    rows = ctx.row_groups["line_items"]
    assert [r.get("amount") for r in rows] == [Decimal("4608.45"), Decimal("4608.45")]


def test_the_header_band_scales_with_the_document_s_own_line_pitch() -> None:
    """A fixed 12pt band assumes a font size. The corpus happens to sit at 5.8-12.4pt
    median line pitch, so 12.0 covers it - but a document set in larger type, with
    20pt leading, would print a wrapped header 20pt above its anchor row and the
    band would silently miss it. Across thousands of senders that is a guaranteed
    class of failure, not a hypothetical.

    Here the page's own pitch is 20pt and the wrapped header sits 18pt up.
    """
    words: list[tuple[str, float, float]] = [
        ("Extended", 500.0, 82.0),                    # wrapped header, 18pt above
        ("Product", 50.0, 100.0), ("No.", 95.0, 100.0), ("Price", 505.0, 100.0),
    ]
    for i, y in enumerate((120.0, 140.0, 160.0)):     # 20pt pitch
        words += [(f"Item{i}", 50.0, y), ("11.00", 510.0, y)]
    ctx = _run(_ctx(_page(1, *words)), {
        "row_group": "line_items", "table_anchor": "Product No.",
        "columns": {"item_code": "text", "amount": "currency"},
        "column_headers": {"item_code": "Product No.", "amount": "Extended"},
    })
    assert [r.get("amount") for r in ctx.row_groups["line_items"]] == [
        Decimal("11.00"), Decimal("11.00"), Decimal("11.00"),
    ]


def test_the_header_band_reaches_up_but_never_down_into_the_first_row() -> None:
    """The band is deliberately one-directional. Reaching DOWN would let a first
    data row printed tight under the header be absorbed into the header itself,
    which would both lose the row and corrupt the column boundaries."""
    words: list[tuple[str, float, float]] = [
        ("DESCRIPTION", 50.0, 100.0), ("AMOUNT", 400.0, 100.0),
        ("Item0", 50.0, 108.0), ("1.00", 400.0, 108.0),   # 8pt below the header
        ("Item1", 50.0, 128.0), ("2.00", 400.0, 128.0),
    ]
    ctx = _run(_ctx(_page(1, *words)), {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"description": "text", "amount": "currency"},
    })
    assert [r.get("amount") for r in ctx.row_groups["line_items"]] == [
        Decimal("1.00"), Decimal("2.00"),
    ]


def test_one_tight_line_does_not_collapse_the_established_row_pitch() -> None:
    """A wrapped description line sits close under its own row. With `pitch =
    min(pitch, gap)` that single 4pt gap became the established pitch for the rest
    of the table, dropping the break threshold to the floor - so the very next
    ordinary gap read as structural and truncated the table early.

    Synthetic on purpose (standing rule 2): the corpus contains the *swallowing*
    direction of this bug, not the truncating direction, so no gold document can
    detect it. Real measured collapses: Complete Beverage 18.00pt -> 3.60,
    Federal Recycling 19.98 -> 4.68.
    """
    words: list[tuple[str, float, float]] = [
        ("DESCRIPTION", 50.0, 100.0), ("AMOUNT", 400.0, 100.0),
    ]
    # Pitch 20pt, then one tight 4pt line, then an ordinary 30pt gap that is well
    # inside 2.5x the real pitch and must NOT end the table.
    for i, y in enumerate((120.0, 140.0, 160.0, 164.0, 194.0)):
        words += [(f"Item{i}", 50.0, y), (f"{i + 1}.00", 400.0, y)]
    ctx = _run(_ctx(_page(1, *words)), {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"description": "text", "amount": "currency"},
    })
    assert len(ctx.row_groups["line_items"]) == 5


def test_a_genuinely_loose_table_still_breaks_on_a_structural_gap() -> None:
    """The mirror of the test above: a robust pitch must not make the break rule
    unreachable. Pitch 20pt, then a 60pt gap - past 2.5x - still ends the table."""
    words: list[tuple[str, float, float]] = [
        ("DESCRIPTION", 50.0, 100.0), ("AMOUNT", 400.0, 100.0),
    ]
    for i, y in enumerate((120.0, 140.0, 160.0, 220.0)):
        words += [(f"Item{i}", 50.0, y), (f"{i + 1}.00", 400.0, y)]
    ctx = _run(_ctx(_page(1, *words)), {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"description": "text", "amount": "currency"},
    })
    assert len(ctx.row_groups["line_items"]) == 3


def test_a_missing_table_anchor_yields_no_rows() -> None:
    ctx = _run(_ctx(_page(1, ("nothing", 10.0, 10.0))), {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"amount": "currency"},
    })
    assert ctx.row_groups.get("line_items", []) == []


def test_charges_and_sub_account_are_row_groups_too() -> None:
    """The four contract keys are not four mechanisms; three are row groups."""
    ctx = _ctx(_page(
        1,
        ("LABEL", 50.0, 300.0), ("AMOUNT", 400.0, 300.0),
        ("FUEL", 50.0, 320.0), ("SURCHARGE", 100.0, 320.0), ("1218.04", 400.0, 320.0),
    ))
    ctx = _run(ctx, {
        "row_group": "charges", "table_anchor": "LABEL",
        "columns": {"label": "text", "amount": "currency"},
        "column_headers": {"label": "LABEL", "amount": "AMOUNT"},
    })
    assert ctx.row_groups["charges"] == [
        {"label": "FUEL SURCHARGE", "amount": Decimal("1218.04")},
    ]


def test_a_row_group_respects_page_roles() -> None:
    ctx = _ctx(
        _page(1, ("nothing", 10.0, 10.0)),
        _page(2, ("DESCRIPTION", 50.0, 300.0), ("AMOUNT", 400.0, 300.0),
              ("Haul", 50.0, 320.0), ("149.00", 400.0, 320.0)),
        roles=("primary", "supporting"),
    )
    ctx = _run(ctx, {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"amount": "currency"},
    })
    assert ctx.row_groups.get("line_items", []) == []


def test_a_sub_group_captures_a_value_off_its_anchor_line() -> None:
    """F19's one permitted nesting level: U-PAK's `WORK ORDER#:` under a row."""
    ctx = _ctx(_page(
        1,
        ("DESCRIPTION", 50.0, 300.0), ("AMOUNT", 400.0, 300.0),
        ("Haul", 50.0, 320.0), ("149.00", 400.0, 320.0),
        ("WORK", 60.0, 335.0), ("ORDER#:", 100.0, 335.0), ("4378107", 170.0, 335.0),
        ("Swap", 50.0, 355.0), ("550.00", 400.0, 355.0),
    ))
    ctx = _run(ctx, {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"description": "text", "amount": "currency"},
        "sub_group": {"anchor": "WORK ORDER#:", "field": "work_order",
                      "pattern": r"ORDER#:\s?(\d{7})"},
    })
    rows = ctx.row_groups["line_items"]
    assert rows[0]["work_order"] == "4378107"
    assert rows[0]["amount"] == Decimal("149.00")
    assert "work_order" not in rows[1]


# --------------------------------------------------------------------------
# Scanline - scoring only
# --------------------------------------------------------------------------


def test_the_scanline_is_recorded_and_produces_no_field_value() -> None:
    ctx = _ctx(_page(
        1,
        ("body", 10.0, 100.0),
        ("25600770871000367962", 100.0, 700.0),
    ))
    ctx = _run(ctx, {"scanline": True, "region": "remittance-block",
                     "asserts": [{"field": "total_printed", "as": "digits_no_decimal"}]})
    assert ctx.scanline == "25600770871000367962"
    assert dict(ctx.extracted.values) == {}


def test_the_scanline_is_looked_for_only_inside_its_region() -> None:
    """A long digit run in the body is not a remittance scan line."""
    ctx = _ctx(_page(
        1,
        ("11112222333344445555", 100.0, 100.0),   # body: outside the stub
        ("shortstub", 100.0, 700.0),
    ))
    ctx = _run(ctx, {"scanline": True, "region": "remittance-block",
                     "asserts": [{"field": "total_printed", "as": "digits_only"}]})
    assert ctx.scanline is None


def test_the_scanline_is_read_from_a_supporting_page_if_that_is_where_it_is() -> None:
    """Section 7 restricts FIELD VALUES. A scanline is scoring-only, so the
    page-role rule does not apply to it - and must not, because the remittance
    stub of a multi-page bill routinely lands on a continuation page."""
    ctx = _ctx(
        _page(1, ("body", 10.0, 100.0)),
        _page(2, ("25600770871000367962", 100.0, 700.0)),
        roles=("primary", "supporting"),
    )
    ctx = _run(ctx, {"scanline": True, "region": "last-page",
                     "asserts": [{"field": "total_printed", "as": "digits_only"}]})
    assert ctx.scanline == "25600770871000367962"


# --------------------------------------------------------------------------
# The 50ms budget
# --------------------------------------------------------------------------


def test_the_pattern_budget_is_fifty_milliseconds() -> None:
    assert PATTERN_BUDGET_SECONDS == pytest.approx(0.050)


def test_a_blown_budget_is_a_field_miss_plus_a_modifier() -> None:
    """Section 3.2: "Timeout -> field miss + pattern_timeout modifier, never a
    wedged worker." The budget is checked BETWEEN candidate strings, so total
    time per field is bounded by the budget plus one candidate's runtime."""
    many_words = tuple(
        (f"word{i}", 10.0 + (i % 40) * 12.0, 100.0 + (i // 40) * 12.0)
        for i in range(4000)
    )
    ctx = _ctx(_page(1, *many_words))
    executor = Executor(_persona(
        {"field": "total_printed", "region": "any-page", "pattern": "currency"},
    ))
    executor._budget_seconds = 0.0  # every candidate is already over budget
    ctx = executor.apply(ctx)
    assert ctx.extracted.get("total_printed") is None
    assert "pattern_timeout" in ctx.modifiers


def test_a_normal_extraction_does_not_report_a_timeout() -> None:
    ctx = _ctx(_page(1, ("Total", 300.0, 600.0), ("367.96", 480.0, 600.0)))
    ctx = _run(ctx, {"field": "total_printed", "anchor": "Total",
                     "region": "same-row", "pattern": "currency"})
    assert "pattern_timeout" not in ctx.modifiers


# --------------------------------------------------------------------------
# Whole-persona behaviour
# --------------------------------------------------------------------------


def test_selectors_are_independent_one_miss_does_not_stop_the_rest() -> None:
    ctx = _ctx(_page(
        1,
        ("Total", 300.0, 600.0), ("Due", 350.0, 600.0), ("367.96", 480.0, 600.0),
        ("Invoice", 50.0, 100.0), ("#", 110.0, 100.0), ("6060", 130.0, 100.0),
    ))
    ctx = _run(
        ctx,
        {"field": "vendor_name", "anchor": "NOT PRESENT", "region": "header-block",
         "pattern": "text"},
        {"field": "total_printed", "anchor": "Total Due", "region": "totals-block",
         "pattern": "currency"},
        {"field": "invoice_number", "anchor": "Invoice #", "region": "header-block",
         "pattern": "integer"},
    )
    assert ctx.extracted.get("vendor_name") is None
    assert ctx.extracted.get("total_printed") == Decimal("367.96")
    assert ctx.extracted.get("invoice_number") == 6060


def test_the_executor_does_not_apply_adjust_ops() -> None:
    """Section 4: ops run at Stage 6, in declaration order. The executor leaves
    the raw extracted value alone - `s6_capture` reads the ops off ctx.persona,
    so no intermediate "pending ops" state has to exist anywhere."""
    ctx = _ctx(_page(1, ("Account", 50.0, 100.0), ("8495 44 462", 200.0, 100.0)))
    ctx = _run(ctx, {"field": "account_number", "anchor": "Account",
                     "region": "same-row", "pattern": "text",
                     "adjust": ["strip_internal_whitespace", "uppercase"]})
    value = ctx.extracted.get("account_number")
    assert value is not None and " " in str(value), "whitespace must survive Stage 5"


def test_apply_returns_the_same_context_object() -> None:
    """The pipeline threads one mutable JobContext; the executor must not clone."""
    ctx = _ctx(_page(1, ("x", 10.0, 10.0)))
    assert Executor(_persona()).apply(ctx) is ctx


def test_an_empty_document_extracts_nothing_and_does_not_raise() -> None:
    ctx = JobContext(document_id="d1", source_path="x.pdf")
    ctx = _run(ctx, {"field": "total_printed", "anchor": "Total",
                     "region": "totals-block", "pattern": "currency"})
    assert dict(ctx.extracted.values) == {}


def test_a_persona_targeting_a_derived_field_raises_rather_than_leaking() -> None:
    """The validator rejects this at write time (V10). If an unvalidated persona
    reaches the executor anyway, ExtractedFields refuses the write rather than
    letting a derived field be populated from a page."""
    ctx = _ctx(_page(1, ("Total", 300.0, 600.0), ("367.96", 480.0, 600.0)))
    with pytest.raises(ValueError, match="derived_only"):
        _run(ctx, {"field": "amount_payable", "anchor": "Total",
                   "region": "same-row", "pattern": "currency"})


# --------------------------------------------------------------------------
# End to end: a real persona through Stage 5a into the Stage 8 record
# --------------------------------------------------------------------------


def test_a_validated_persona_reaches_the_record_through_all_four_new_keys() -> None:
    """The C2b deliverable, proven end to end rather than per-unit.

    Before these keys existed the scorecard could not assert four whole gold
    sections, so the convergence loop was blind to F7, F8, F14 and F19. This
    test is what says the path from a persona to those record keys is real.
    """
    from docintel.core.contract import build_record, validate_record
    from docintel.grammar.validator import validate_persona
    from docintel.pipeline.stages.s5a_cached import ApplyCachedRules
    from docintel.pipeline.stages.s6_capture import CaptureFields

    raw = {
        "sender_fingerprint": "edcodisposal.com|edco",
        "doc_type": "standard_invoice",
        "rule_version": "v1",
        "status": "draft",
        "field_selectors": [
            {"field": "total_printed", "anchor": "Total Amount Due",
             "region": "totals-block", "pattern": "currency"},
            {"row_group": "line_items", "table_anchor": "DESCRIPTION",
             "columns": {"description": "text", "charges": "currency"},
             "column_headers": {"description": "DESCRIPTION", "charges": "CHARGES"},
             "row_count": {"min": 1, "max": 40}},
            {"row_group": "charges", "table_anchor": "SURCHARGE",
             "columns": {"label": "text", "amount": "currency"},
             "column_headers": {"label": "SURCHARGE", "amount": "FEE"}},
            {"scanline": True, "region": "remittance-block",
             "asserts": [{"field": "total_printed", "as": "digits_no_decimal"}]},
        ],
        "layout_fingerprint": {"page_count": {"min": 1, "max": 2}},
    }
    validate_persona(raw, pack=None)

    ctx = _ctx(_page(
        1,
        ("DESCRIPTION", 50.0, 100.0), ("CHARGES", 400.0, 100.0),
        ("CANCEL", 50.0, 120.0), ("SERVICE", 110.0, 120.0), ("69.62", 400.0, 120.0),
        ("SURCHARGE", 50.0, 200.0), ("FEE", 400.0, 200.0),
        ("FUEL", 50.0, 220.0), ("1218.04", 400.0, 220.0),
        ("Total", 300.0, 400.0), ("Amount", 350.0, 400.0), ("Due", 420.0, 400.0),
        ("367.96", 480.0, 400.0),
        ("25600770871000367962", 100.0, 700.0),
    ))
    ctx.persona = parse_persona(raw)
    ctx.persona_status = "hit"
    ctx.sender_fingerprint = "edcodisposal.com|edco"
    ctx.extraction_rule_version = "v1"

    ctx = ApplyCachedRules().run(ctx)
    assert ctx.extraction_route == "5a_cached"

    # Stage 6 too: since C3 a processed record must carry document_identity, and
    # running the real stage here is what makes this a whole-path test rather
    # than a Stage 5a test that happens to build a record.
    ctx = CaptureFields().run(ctx)

    record = build_record(ctx)
    validate_record(record)

    assert record["fields"]["total_printed"] == "367.96"
    assert record["line_items"] == [{"description": "CANCEL SERVICE", "charges": "69.62"}]
    assert record["charges"] == [{"label": "FUEL", "amount": "1218.04"}]
    assert record["scanline"] == "25600770871000367962"
    assert record["sub_account"] == []
    # Stage 6 derived the identity from the invoice-number rung being absent and
    # no account number extracted, so it recorded that it looked and could not.
    assert "document_identity" in record["derived"]
    assert "identity_basis" in record["derived"]


def test_a_row_count_violation_is_logged_and_never_silently_truncates() -> None:
    """`row_count` is a stated expectation, not a filter.

    Truncating to `max` would silently discard real rows - the exact class of
    quiet data loss this design refuses. There is also no confidence modifier
    for it in the closed section 5 enum, and inventing one here would be the
    vocabulary growth the grammar forbids, so it is logged and left visible.
    """
    words: list[tuple[str, float, float]] = [
        ("DESCRIPTION", 50.0, 100.0), ("AMOUNT", 400.0, 100.0),
    ]
    for i in range(5):
        y = 120.0 + i * 20.0
        words += [(f"Item{i}", 50.0, y), (f"{i + 1}.00", 400.0, y)]
    ctx = _run(_ctx(_page(1, *words)), {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"description": "text", "amount": "currency"},
        "row_count": {"min": 1, "max": 2},
    })
    assert len(ctx.row_groups["line_items"]) == 5, "rows must never be truncated"
    assert any("outside the declared range 1-2" in e for e in ctx.events)


def test_a_satisfied_row_count_logs_nothing() -> None:
    ctx = _run(_table_ctx(), {
        "row_group": "line_items", "table_anchor": "DESCRIPTION",
        "columns": {"description": "text", "amount": "currency"},
        "row_count": {"min": 1, "max": 40},
    })
    assert not any("outside the declared range" in e for e in ctx.events)


# --------------------------------------------------------------------------
# Header-less row groups — label/amount ladders with no header row
# --------------------------------------------------------------------------


def _ladder_ctx() -> JobContext:
    """Centracom's charges block, reduced: a right-hand column with no header row."""
    return _ctx(_page(
        1,
        ("This", 421.0, 147.0), ("Month", 447.0, 147.0),
        ("Internet", 325.0, 161.0), ("Charges", 364.0, 161.0), ("140.90", 549.0, 161.0),
        ("Special", 325.0, 175.0), ("Circuit", 358.0, 175.0), ("Charges", 391.0, 175.0),
        ("13,611.50", 536.0, 175.0),
        ("Subtotal", 325.0, 189.0), ("Current", 370.0, 189.0), ("Charges", 407.0, 189.0),
        ("$13,752.60", 527.0, 189.0),
    ))


def test_a_row_group_with_no_column_headers_reads_a_label_amount_ladder() -> None:
    """Three gold files carry `charges` and none of their tables has a header row:

        Internet Charges                              140.90
        Comcast Business services                     217.89

    The row-group model builds its column grid from a header row, so there was
    nothing to build from. Absent `column_headers`, each line is split as
    label-then-trailing-amount instead.
    """
    ctx = _run(_ladder_ctx(), {
        "row_group": "charges", "table_anchor": "Internet Charges",
        "region": "label-block",
        "columns": {"label": "text", "amount": "currency"},
    })
    assert ctx.row_groups["charges"] == [
        {"label": "Internet Charges", "amount": Decimal("140.90")},
        {"label": "Special Circuit Charges", "amount": Decimal("13611.50")},
    ]


def test_a_roll_up_row_inside_the_ladder_is_not_a_charge() -> None:
    """Centracom prints `Subtotal Current Charges $13,752.60` inside the same block
    as its three real charges, and its gold `charges` label contains only the three.
    A row that sums a list is not a member of it."""
    ctx = _run(_ladder_ctx(), {
        "row_group": "charges", "table_anchor": "Internet Charges",
        "region": "label-block",
        "columns": {"label": "text", "amount": "currency"},
    })
    labels = [r["label"] for r in ctx.row_groups["charges"]]
    assert not any(label.startswith("Subtotal") for label in labels)


def test_a_previous_balance_row_inside_the_ladder_is_not_a_charge() -> None:
    """Centracom also prints `Previous Balance $20,123.80` inside the same block
    as its three real charges - a second roll-up phrasing, distinct from
    `Subtotal ...` above. `_ROLLUP_LABEL`'s comment already claimed to catch this
    one, but the regex never actually matched it: it starts with `Previous`, not
    one of the filter's leading alternatives (task-5 review, 2026-08-03). This was
    silent while `_label_block`'s old `min`-based pitch bug floor-clamped the
    block's break threshold low enough that `Previous Balance` never reached this
    filter in the first place; fixing that bug exposed the pre-existing gap here."""
    ctx = _ctx(_page(
        1,
        ("This", 421.0, 147.0), ("Month", 447.0, 147.0),
        ("Internet", 325.0, 161.0), ("Charges", 364.0, 161.0), ("140.90", 549.0, 161.0),
        ("Special", 325.0, 175.0), ("Circuit", 358.0, 175.0), ("Charges", 391.0, 175.0),
        ("13,611.50", 536.0, 175.0),
        ("Previous", 325.0, 189.0), ("Balance", 363.0, 189.0), ("$20,123.80", 530.0, 189.0),
    ))
    ctx = _run(ctx, {
        "row_group": "charges", "table_anchor": "Internet Charges",
        "region": "label-block",
        "columns": {"label": "text", "amount": "currency"},
    })
    labels = [r["label"] for r in ctx.row_groups["charges"]]
    assert not any(label.startswith("Previous") for label in labels)


def test_the_RIGHTMOST_money_token_is_the_amount() -> None:
    """A charge line reads name-then-number, so an id or a date earlier on the line
    must not be mistaken for the amount."""
    ctx = _ctx(_page(
        1,
        ("Circuit", 325.0, 100.0), ("4351003276", 380.0, 100.0), ("750.00", 540.0, 100.0),
    ))
    ctx = _run(ctx, {
        "row_group": "charges", "table_anchor": "Circuit", "region": "label-block",
        "columns": {"label": "text", "amount": "currency"},
    })
    (row,) = ctx.row_groups["charges"]
    assert row["amount"] == Decimal("750.00")
    assert row["label"] == "Circuit 4351003276"


def test_a_line_with_no_amount_is_not_a_charge_row() -> None:
    ctx = _ctx(_page(
        1,
        ("New", 317.0, 100.0), ("charges", 339.0, 100.0),
        ("Comcast", 317.0, 114.0), ("services", 380.0, 114.0), ("217.89", 542.0, 114.0),
    ))
    ctx = _run(ctx, {
        "row_group": "charges", "table_anchor": "New charges", "region": "label-block",
        "columns": {"label": "text", "amount": "currency"},
    })
    assert ctx.row_groups["charges"] == [
        {"label": "Comcast services", "amount": Decimal("217.89")},
    ]


def test_a_line_with_only_an_amount_is_not_a_charge_row() -> None:
    """No label means nothing to bill it against."""
    ctx = _ctx(_page(1, ("Total", 325.0, 100.0), ("99.00", 540.0, 114.0)))
    ctx = _run(ctx, {
        "row_group": "charges", "table_anchor": "Total", "region": "label-block",
        "columns": {"label": "text", "amount": "currency"},
    })
    assert ctx.row_groups.get("charges", []) == []


def test_header_less_mode_needs_exactly_two_columns_one_of_them_money() -> None:
    """Not an arbitrary restriction - it IS the shape. `Internet Charges 140.90`
    has a name and a number and nothing else, so a third column has nothing to
    read from."""
    ctx = _run(_ladder_ctx(), {
        "row_group": "charges", "table_anchor": "Internet Charges",
        "region": "label-block",
        "columns": {"label": "text", "extra": "text", "amount": "currency"},
    })
    assert ctx.row_groups.get("charges", []) == []


def test_declared_headers_that_match_nothing_are_an_error_not_a_fallback() -> None:
    """A typo'd `column_headers` must not silently produce plausible output through
    the header-less path - that would hide the typo behind a result."""
    ctx = _run(_ladder_ctx(), {
        "row_group": "charges", "table_anchor": "Internet Charges",
        "region": "label-block",
        "columns": {"label": "text", "amount": "currency"},
        "column_headers": {"label": "DESCRIPTION", "amount": "AMOUNT"},
    })
    assert ctx.row_groups.get("charges", []) == []
    assert any("none matched" in e for e in ctx.events)


# --------------------------------------------------------------------------
# `scope` - which candidates the region offers the pattern
# --------------------------------------------------------------------------
#
# GRAMMAR EXTENSION, section 1.1. Until it existed, `_candidates` chose between
# per-line candidates and one column-cut block by testing whether the selector's
# pattern was the literal string `"text_block"` - so the column cut, the thing
# that keeps a two-column layout's other column out of the capture, was reachable
# only by a pattern that accepts anything at all. A selector that needs BOTH the
# cut and a shape constraint could not be written.
#
# Measured need (U-PAK `bill_to_name`): `Bill To` sits at x0=90 and the
# service-location column at x0=355.1, inside `near-anchor`'s 300pt reach, and the
# two columns' rows interleave. With per-line candidates a party-name shape
# returns the SERVICE LOCATION on 6 of 12 real second samples; with the block it
# returns the party or nothing.

def _two_column_block_page() -> PageText:
    """U-PAK's real page-1 geometry, reduced to the two columns that matter.

    `Bill To:` labels the left column at x0=90; `Location:` labels the right at
    x0=355.1, on the same row. The customer's own block interleaves with the
    service location's, one row apart, and the service location's first row sits
    ABOVE the customer's name - which is what makes reading order alone wrong.
    """
    return _page(
        1,
        ("Bill", 90.0, 135.68), ("To:", 104.6, 135.68), ("Location:", 355.1, 135.68),
        ("ROYAL", 355.1, 169.18), ("CANIN", 384.4, 169.18),
        ("NORTHSTAR", 90.0, 173.18), ("RECYCLING", 142.0, 173.18),
    )


PARTY_SHAPE = r"^([A-Za-z0-9][A-Za-z0-9&.,'()/#-]{1,29} [A-Za-z0-9 &.,'()/#-]{1,44})$"


def test_line_scope_offers_the_neighbouring_column_as_a_candidate() -> None:
    """The behaviour `scope: "block"` exists to escape, pinned first so the
    extension is measured against something rather than asserted.

    `near-anchor` is x-bounded at `anchor.x0 + 300` = 390, which takes in the
    right column at x0=355.1. Its row is 4pt above the customer's, so it is
    offered first and a party-name shape accepts it."""
    ctx = _run(_ctx(_two_column_block_page()), {
        "field": "bill_to_name", "anchor": "Bill To",
        "region": "near-anchor", "pattern": PARTY_SHAPE,
    })
    assert ctx.extracted.get("bill_to_name") == "ROYAL CANIN"


def test_block_scope_applies_the_column_cut_to_a_regex_pattern() -> None:
    """The extension itself: the same region, the same pattern, the same page -
    and the right column is gone, because the block is cut at the column gutter
    exactly as `text_block` has always cut it."""
    ctx = _run(_ctx(_two_column_block_page()), {
        "field": "bill_to_name", "anchor": "Bill To",
        "region": "near-anchor", "pattern": PARTY_SHAPE, "scope": "block",
    })
    assert ctx.extracted.get("bill_to_name") == "NORTHSTAR RECYCLING"


def test_block_scope_makes_an_anchored_pattern_reject_a_multi_line_block() -> None:
    """Why an anchored shape plus block scope is a SAFE idiom rather than merely
    a narrower one. `re` matches `^...$` against the whole string unless
    `re.MULTILINE` is set, and `compile_restricted` never sets it, so a block
    carrying anything besides the name cannot match - a clean miss, which falls
    through to `resolve_bill_to_alias`'s roster rung, rather than a wrong value.

    Real geometry: `_AP Invoice 4421470 U-Pak` prints `ATTN: SEAN LEES` at
    top=161.18, above the party at top=169.18, both inside near-anchor's window.
    """
    ctx = _run(_ctx(_page(
        1,
        ("Bill", 90.0, 135.68), ("To:", 104.6, 135.68),
        ("ATTN:", 90.0, 161.18), ("SEAN", 115.3, 161.18), ("LEES", 139.3, 161.18),
        ("NORTHSTAR", 90.0, 169.18), ("RECYCLING", 142.0, 169.18),
    )), {
        "field": "bill_to_name", "anchor": "Bill To",
        "region": "near-anchor", "pattern": PARTY_SHAPE, "scope": "block",
    })
    assert ctx.extracted.get("bill_to_name") is None


def test_block_scope_still_drops_the_anchors_own_words() -> None:
    """The `skip` set applies on both paths. Without it a block-scoped capture
    would return the label that located it (F14's anchor hazard)."""
    ctx = _run(_ctx(_page(
        1,
        ("FOR", 100.0, 300.0), ("SERVICE", 130.0, 300.0), ("AT:", 190.0, 300.0),
        ("1600", 100.0, 315.0), ("Industrial", 140.0, 315.0), ("Rd", 210.0, 315.0),
    )), {
        "field": "service_location", "anchor": "FOR SERVICE AT:",
        "region": "near-anchor", "pattern": r"^(.{1,60})$", "scope": "block",
    })
    assert ctx.extracted.get("service_location") == "1600 Industrial Rd"


def test_text_block_behaves_identically_with_and_without_the_explicit_scope() -> None:
    """The backward-compatibility claim, asserted rather than argued: every
    persona shipping `text_block` predates `scope`, so `text_block` alone must
    keep producing exactly what `text_block` plus `scope: "block"` produces."""
    implicit = _run(_ctx(_two_column_block_page()), {
        "field": "bill_to_address", "anchor": "Bill To",
        "region": "near-anchor", "pattern": "text_block",
    })
    explicit = _run(_ctx(_two_column_block_page()), {
        "field": "bill_to_address", "anchor": "Bill To",
        "region": "near-anchor", "pattern": "text_block", "scope": "block",
    })
    assert implicit.extracted.get("bill_to_address") == "NORTHSTAR RECYCLING"
    assert explicit.extracted.get("bill_to_address") == implicit.extracted.get(
        "bill_to_address"
    )
