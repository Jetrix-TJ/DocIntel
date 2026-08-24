"""Northstar's classification ladder and tags (pack spec section 1).

Content only, never the filename. Three of the six Northstar filenames state the
answer outright, so a classifier that read them would score well here and teach
nothing.
"""

from __future__ import annotations

import pytest

from docintel.core.models import PageMeta, PageText, Word, new_context
from northstar.ladder import classify, doc_type_for, tags_for


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
    attachment.

    The roles below model what `pageroles.assign` actually resolves on the real
    source PDF, confirmed by reading both pages: `_TOTALS_RE` deliberately
    excludes bare `CURRENT CHARGES` (see that module's own docstring), so
    neither page trips the anchor+totals tier and `assign` falls through to its
    tier-2 last-resort fallback - page 1 `primary`, page 2 `supporting`. That is
    still the exact (primary=1, supporting>=1) shape the ladder's
    `invoice_with_attachment` rule otherwise treats as an attachment pair, and
    the fix's correctness does not depend on which page lands which role -
    `_is_paginated_continuation` reads the printed footer, never `page_meta`, so
    only the (1 primary, >=1 supporting) *count* matters here, not which page
    holds which role."""
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
        roles=("primary", "supporting"),
    )
    assert doc_type_for(ctx)[0] != "invoice_with_attachment"


def test_a_credit_memo_title_wins_over_everything() -> None:
    ctx = _ctx(_page("CREDIT MEMO occ 2.495 ST -40.00/ST -99.80"))
    assert doc_type_for(ctx)[0] == "credit_memo"


def test_credit_memo_mentioned_in_a_line_item_note_does_not_reclassify_a_real_invoice() -> None:
    """Real Complete Beverage bug: an invoice's line-item note reads 'For
    remaining credited items refer to Credit memo 32684.' — a full sentence,
    not a document title. Must not fire _CREDIT_MEMO."""
    ctx = _ctx(_page(
        "COMPLETE BEVERAGE DESTRUCTION|BALANCE DUE $556.20|"
        "For remaining credited items refer to Credit memo 32684."
    ))
    doc_type, signal = doc_type_for(ctx)
    assert doc_type != "credit_memo"


def test_credit_memo_title_on_its_own_short_line_still_fires() -> None:
    """No regression: a genuine credit-memo document title, alone on a short
    line, must still classify as credit_memo."""
    ctx = _ctx(_page("Credit Memo|CREDIT TO CREDIT # 32473|TOTAL CREDIT $2,899.00"))
    doc_type, signal = doc_type_for(ctx)
    assert doc_type == "credit_memo"
    assert signal == "credit_memo_title"


def test_wrapped_credit_memo_footnote_deep_in_page_does_not_fire() -> None:
    """Real Complete Beverage 32593 bug (whole-branch review finding 1): the
    OCR of "For remaining credited items refer to Credit memo 32684." does
    NOT come back as one long prose line - it wraps across two SHORT lines,
    "For remaining credited items refer to" (6 words) and "Credit memo
    32684" (3 words), so the line-length check alone can no longer reject
    it the way it rejects the single-line version above.

    What still tells this apart from a genuine title is POSITION: on the
    real 32593 document this footnote sits at page-1 line index 25-26 of
    30, deep in the page; on the real genuine credit memo (32473) the title
    sits at line index 5 of 20, near the top. This fixture reproduces that
    shape - filler lines pushing the wrapped footnote down to roughly the
    same real depth - and must NOT classify as credit_memo.
    """
    filler = [f"Line {i} of unrelated invoice detail text" for i in range(23)]
    lines = [
        "COMPLETE BEVERAGE DESTRUCTION",
        "BALANCE DUE $556.20",
        *filler,
        "For remaining credited items refer to",
        "Credit memo 32684",
    ]
    ctx = _ctx(_page("|".join(lines)))
    doc_type, signal = doc_type_for(ctx)
    assert doc_type == "standard_invoice"
    assert doc_type != "credit_memo"


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


def test_a_past_due_banner_on_a_supporting_page_still_tags() -> None:
    """Pins a DELIBERATE widening that nothing else can see.

    This pack's `past_due` banner check reads every page, not just primary ones
    - Federal Recycling's terms-and-conditions page is a supporting page, and
    that decision was reviewed and accepted before the 2026-08-06 plan. The
    Digital Direction pack's identical check is correctly narrowed to primary
    pages, so the two now pass opposite `primary_only` values to the same shared
    `signals.short_label_line`.

    Without this test the widening is a comment. Flipping the flag - or
    "tidying" the explicit `primary_only=False` at the call site - leaves the
    whole suite green AND `replay-gold` byte-identical, because a gold `tags`
    assertion is a SUPERSET check and therefore cannot see a tag that stops
    firing.
    """
    ctx = _ctx(
        _page("Invoice 100.00"),
        _page("PAST DUE", number=2),
        roles=("primary", "supporting"),
    )
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
    """U-PAK prints no banner, only an aging table, with a genuinely nonzero
    bucket in the data row beneath the header."""
    ctx = _ctx(_page("AGE CURRENT 30 DAYS 60 DAYS 90 DAYS Please Pay|0.00 0.00 4476.34 0.00 4476.34"))
    assert "past_due" in tags_for(ctx)


def test_aging_header_with_all_zero_buckets_does_not_tag_past_due() -> None:
    """Real U-Pak bug: 'AGE CURRENT 30 DAYS 60 DAYS 90 DAYS Please Pay' is a
    column-header row; the data row beneath it is all $0.00. Must not fire."""
    ctx = _ctx(_page(
        "U-PAK DISPOSALS|AGE CURRENT 30 DAYS 60 DAYS 90 DAYS Please Pay|"
        "0.00 0.00 0.00 0.00 4915.80"
    ))
    assert "past_due" not in tags_for(ctx)


def test_aging_header_with_a_real_60_day_balance_still_tags_past_due() -> None:
    """No regression: a genuinely nonzero aging bucket must still tag."""
    ctx = _ctx(_page(
        "U-PAK DISPOSALS|AGE CURRENT 30 DAYS 60 DAYS 90 DAYS Please Pay|"
        "0.00 0.00 4476.34 0.00 4476.34"
    ))
    assert "past_due" in tags_for(ctx)


def test_a_tax_line_tags_has_tax() -> None:
    assert "has_tax" in tags_for(_ctx(_page("Sub Total 54.50 Taxes 7.09 Total 61.59")))


def test_a_zero_tax_value_on_the_same_line_does_not_tag_has_tax() -> None:
    """Boundary the same-line path must also hold to: a nonzero Sub Total
    (or any other token) sitting on the same line as the tax label must
    not corroborate a genuinely zero tax value. This is the exact
    false-positive class the next-line Veritiv fix exists to close -
    same-line matches need the identical rigor, not 'any nonzero token on
    the line', or a same-line document with real other charges and $0.00
    tax would still misfire."""
    ctx = _ctx(_page("Sub Total 54.50 Taxes 0.00 Total 54.50"))
    assert "has_tax" not in tags_for(ctx)


def test_zero_total_tax_does_not_tag_has_tax() -> None:
    """Real Veritiv bug: 'Total Tax' is a column-header label; the actual
    tax charged is $0.00 (items marked non-taxable). Must not fire.

    Row shape is the real one (verified against all 7 Veritiv second
    samples, e.g. `_AP Invoice 689-37584900`): Discount Allowed/On Date/
    Amount, Shipment Date/Time, Total Weight, Subtotal, Total Tax, Amount
    Due - nine columns, with Subtotal always nonzero for any real charge.
    A same-line-only or any-token-on-the-line check would misfire on
    Subtotal; only the token second-to-last (Total Tax, just before the
    trailing Amount Due) tells taxed from non-taxable."""
    ctx = _ctx(_page(
        "VERITIV OPERATING COMPANY|"
        "Allowed On Date Amount Date Time Total Weight Subtotal Total Tax|"
        "11/19/2025 6.25 00:00:00 27.10 625.00 0.00 0.00 0.00 625.00"
    ))
    assert "has_tax" not in tags_for(ctx)


def test_nonzero_total_tax_still_tags_has_tax() -> None:
    """No regression: a genuinely nonzero tax line must still tag.

    Real row from `_AP Invoice 715-33905296` (the gold Veritiv document):
    Total Tax = 299.55, second-to-last before Amount Due = 4,908.00."""
    ctx = _ctx(_page(
        "VERITIV OPERATING COMPANY|"
        "Allowed On Date Amount Date Time Total Weight Subtotal Total Tax|"
        "09/13/2025 46.08 00:00:00 2,568.49 4,608.45 0.00 0.00 299.55 4,908.00"
    ))
    assert "has_tax" in tags_for(ctx)


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
