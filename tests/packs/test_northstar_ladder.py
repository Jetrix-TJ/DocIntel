"""Northstar's classification ladder and tags (pack spec section 1).

Content only, never the filename. Three of the six Northstar filenames state the
answer outright, so a classifier that read them would score well here and teach
nothing.
"""

from __future__ import annotations

import pytest

from docintel.core.models import PageMeta, PageText, Word, new_context
from docintel.packs.northstar.ladder import classify, doc_type_for, tags_for


def _page(text: str, number: int = 1, source: str = "native") -> PageText:
    """Build a page from `text`, where `|` starts a new visual LINE.

    Real lines matter here and an earlier draft got it wrong: putting every token
    on one line made `_is_own_paperwork` see the bill-to inside its 4-line
    letterhead window, and made every `PAST DUE` banner look like prose because
    the single line was always longer than six words. Both tests then failed
    against correct code.
    """
    words: list[Word] = []
    for row, line in enumerate(text.split("|")):
        y = 100.0 + row * 14.0
        for i, tok in enumerate(line.split()):
            words.append(
                Word(text=tok, x0=10.0 + 40.0 * i, y0=y, x1=45.0 + 40.0 * i, y1=y + 10.0)
            )
    return PageText(
        page_number=number, words=tuple(words), width=612.0, height=792.0,
        source=source,  # type: ignore[arg-type]
    )


def _ctx(*pages: PageText, roles: tuple[str, ...] | None = None, source: str = "native"):
    ctx = new_context("d", "/x.pdf")
    ctx.pages = pages
    ctx.text_source = source
    ctx.page_meta = tuple(
        PageMeta(p.page_number, 100, 0, 0, roles[i] if roles else "primary")
        for i, p in enumerate(pages)
    )
    return ctx


# --------------------------------------------------------------------------
# The ladder
# --------------------------------------------------------------------------


def test_a_plain_vendor_invoice_is_a_standard_invoice() -> None:
    ctx = _ctx(_page("D.T.S.S., Inc. Invoice Total $699.00 Balance Due $699.00"))
    assert doc_type_for(ctx)[0] == "standard_invoice"


def test_all_negative_commodity_rates_make_a_contra() -> None:
    """Federal Recycling. The `-40.00/ST` per-unit rate is the signal: the suffix
    is what makes it a RATE, and every rate on the page is negative."""
    ctx = _ctx(_page(
        "DATE TRANS NO. REFERENCE DESCRIPTION QUANTITY PRICE AMOUNT "
        "05/06/2025 380357 2436687 occ 2.495 ST -40.00/ST -99.80 USD "
        "05/06/2025 380357 2436687 HAUL FEE 200.00 200.00 USD TOTAL 481.20 USD"
    ))
    assert doc_type_for(ctx)[0] == "contra_invoice"


def test_a_negative_unit_price_without_a_rate_suffix_is_not_a_contra() -> None:
    """Complete Beverage prints `-0.65` and U-PAK `-40.500`, both negative unit
    prices with no per-unit suffix, and neither document is a contra. Without this
    distinction any invoice carrying a rebate line would be misclassified."""
    ctx = _ctx(_page(
        "SERVICE DATE ITEM DESCRIPTION QTY UNIT PRICE AMOUNT "
        "10/23/2025 2004 Clean Aluminum 100 -0.65 -65.00 BALANCE DUE $1,177.70"
    ))
    assert doc_type_for(ctx)[0] != "contra_invoice"


def test_contra_is_tested_before_attachments() -> None:
    """Ladder order, from the pack spec's own note. Federal Recycling is a
    single-page contra and Complete Beverage is a multi-page invoice that also
    has negative lines - testing attachments first would swap them."""
    ctx = _ctx(
        _page("occ 2.495 ST -40.00/ST -99.80 USD"),
        _page("supporting", number=2),
        roles=("primary", "supporting"),
    )
    assert doc_type_for(ctx)[0] == "contra_invoice"


def test_one_primary_plus_a_supporting_page_is_an_attachment_case() -> None:
    """Complete Beverage: an invoice glued to three pages of handwritten BOL."""
    ctx = _ctx(
        _page("Complete Beverage Destruction Invoice BALANCE DUE $1,177.70"),
        _page("handwritten bill of lading", number=2),
        roles=("primary", "supporting"),
    )
    assert doc_type_for(ctx)[0] == "invoice_with_attachment"


def test_a_paginated_continuation_is_not_invoice_with_attachment() -> None:
    """823283AUG25/823283SEP25: a genuine 2-page Edco invoice whose line items
    overflow onto page 2, pushing the totals label off page 1. Both pages repeat
    the same identity header and both print a footer pagination marker
    (`1 OF 2` / `2 OF 2`) - real evidence this is one paginated invoice, not an
    attachment. Confirmed by reading both pages of the real source PDF:
    `pageroles.assign` correctly marks page 2 primary / page 1 supporting (the
    totals label only appears on page 2), which is the exact (primary=1,
    supporting>=1) shape the ladder's `invoice_with_attachment` rule otherwise
    treats as an attachment pair - indistinguishable by role count alone."""
    ctx = _ctx(
        _page(
            "EDCO WASTE|25-5R 823283|HAUL 225.10|000000-001 MD9-M 1 OF 2",
            number=1,
        ),
        _page(
            "EDCO WASTE|25-5R 823283|CURRENT CHARGES: 3267.54 2479.01|"
            "000000-001 MD9-M 2 OF 2",
            number=2,
        ),
        roles=("supporting", "primary"),
    )
    assert doc_type_for(ctx)[0] != "invoice_with_attachment"


def test_a_credit_memo_title_wins_over_everything() -> None:
    ctx = _ctx(_page("CREDIT MEMO occ 2.495 ST -40.00/ST -99.80"))
    assert doc_type_for(ctx)[0] == "credit_memo"


def test_northstars_own_letterhead_is_own_paperwork() -> None:
    ctx = _ctx(_page("Northstar Recycling Company LLC|Packing Slip"))
    assert doc_type_for(ctx)[0] == "own_paperwork"


def test_being_the_bill_to_is_not_own_paperwork() -> None:
    """Every document in the corpus names Northstar - it is the bill-to on all six
    - so only the letterhead position counts."""
    ctx = _ctx(_page(
        "D.T.S.S., Inc. Invoice|500 North Defiance Trail|Spencerville OH 45887|"
        "Bill To|Northstar Recycling Company, LLC|Total $699.00"
    ))
    assert doc_type_for(ctx)[0] != "own_paperwork"


def test_a_statement_title_with_no_table_is_a_statement_of_account() -> None:
    """`statement_of_account` has no corpus document and, until now, no test:
    nothing would have noticed if the branch stopped firing."""
    ctx = _ctx(_page(
        "ABC Vendor Co|Statement of Account|Balance Forward 500.00|"
        "Please remit payment"
    ))
    assert doc_type_for(ctx) == ("statement_of_account", "statement_title_no_table")


def test_a_statement_title_with_a_table_is_not_a_statement_of_account() -> None:
    """Both halves of the signal are required. A table - a line with three or
    more money tokens - means there are line items to reconcile, not merely a
    running balance, so the title alone must not be enough."""
    ctx = _ctx(_page(
        "ABC Vendor Co|Statement of Account|100.00 200.00 300.00 Total Due"
    ))
    assert doc_type_for(ctx) == ("standard_invoice", "default")


# --------------------------------------------------------------------------
# Tags
# --------------------------------------------------------------------------


def test_negative_amounts_tag_mixed_sign() -> None:
    ctx = _ctx(_page("HAUL FEE 200.00 occ -99.80"))
    assert "mixed_sign" in tags_for(ctx)


def test_a_past_due_banner_tags_past_due() -> None:
    ctx = _ctx(_page("Invoice 100.00|PAST DUE"))
    assert "past_due" in tags_for(ctx)


def test_past_due_boilerplate_in_prose_does_not_tag() -> None:
    """Federal Recycling's terms print "PAST DUE AMOUNTS SUBJECT TO INTEREST FEES
    IN THE AMOUNT OF 18.99% ANNUALLY..." on every invoice it sends, and its gold
    label is correctly not tagged. Line length is the discriminator."""
    ctx = _ctx(_page(
        "PAST DUE AMOUNTS SUBJECT TO INTEREST FEES IN THE AMOUNT OF 18.99% "
        "ANNUALLY OR THE MAXIMUM AMOUNT ALLOWED BY STATE LAW WHICHEVER IS LOWER"
    ))
    assert "past_due" not in tags_for(ctx)


def test_aging_buckets_tag_past_due() -> None:
    """U-PAK prints no banner, only an aging table."""
    ctx = _ctx(_page("AGE CURRENT 30 DAYS 60 DAYS 90 DAYS Please Pay"))
    assert "past_due" in tags_for(ctx)


def test_a_tax_line_tags_has_tax() -> None:
    assert "has_tax" in tags_for(_ctx(_page("Sub Total 54.50 Taxes 7.09 Total 61.59")))


def test_sub_acct_markers_tag_sub_accounts() -> None:
    ctx = _ctx(_page("** SUB ACCT: 1 - 22335 SHEARER'S FOODS CANADA R/O"))
    assert "sub_accounts" in tags_for(ctx)


def test_ocr_source_tags_ocr_only() -> None:
    assert "ocr_only" in tags_for(_ctx(_page("anything"), source="ocr"))


def test_a_noisy_supporting_page_tags_handwritten_supporting() -> None:
    """Measured: Complete Beverage's handwritten BOL pages score 0.51 and 0.46 on
    the noise ratio, its printed pages 0.22 and 0.28."""
    ctx = _ctx(
        _page("Complete Beverage Destruction Invoice BALANCE DUE 1,177.70"),
        _page("eo eS Al F Cyst Zips CARTER TA NA ARAL el A Traotor Looeition", number=2),
        roles=("primary", "supporting"),
        source="ocr",
    )
    assert "handwritten_supporting" in tags_for(ctx)


def test_a_handwritten_note_on_a_PRIMARY_page_does_not_tag() -> None:
    """Federal Recycling carries a handwritten margin note that OCR transcribes,
    but it is single-page so there is no supporting page to examine - and its gold
    label is correctly not tagged."""
    ctx = _ctx(
        _page("Yes and I added a few to update what had thanks CGS 6/9 occ -40.00/ST"),
        source="ocr",
    )
    assert "handwritten_supporting" not in tags_for(ctx)


def test_classify_sets_type_signal_and_tags_together() -> None:
    ctx = _ctx(_page("Sub Total 54.50|Taxes 7.09|PAST DUE"))
    out = classify(ctx)
    assert out.doc_type == "standard_invoice"
    assert out.signal_that_fired == "default"
    assert "has_tax" in out.tags and "past_due" in out.tags


@pytest.mark.parametrize("text", ["", "   "])
def test_an_empty_document_still_gets_a_type(text: str) -> None:
    ctx = _ctx(_page(text))
    assert doc_type_for(ctx)[0] == "standard_invoice"
