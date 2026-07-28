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
