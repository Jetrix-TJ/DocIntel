"""Northstar's classification ladder and tags (pack spec section 1).

**First signal that fires wins, then the ladder stops** (spec Stage 3). Content
only, never the filename - three of the six corpus filenames state the answer
outright (`CONTRA ONLY ...`, `CANADIAN WITHOUT NOTES ...`, `... current charges
can be misleading, paying $69.62`) and a classifier that read them would score
well and teach nothing.

**Ladder order is load-bearing.** `contra_invoice` sits *above*
`invoice_with_attachment` because Federal Recycling is a single-page contra and
Complete Beverage is a multi-page invoice that also contains negative lines.
Testing "has attachments" first would classify any multi-page invoice with a
rebate line as an attachment case; testing "has negatives" first would classify
Complete Beverage as contra.

Tags are layered on and never change the type.
"""

from __future__ import annotations

import re

from docintel.core.models import JobContext
from docintel.packs import signals

# --- doc-type signals -----------------------------------------------------

_CREDIT_MEMO = re.compile(r"\b(credit memo|credit note|adjustment note)\b", re.I)
_STATEMENT = re.compile(r"\bstatement of account\b", re.I)
_NORTHSTAR_LETTERHEAD = re.compile(r"\bnorthstar recycling\b", re.I)

# A per-unit rate: a money token followed by `/UNIT`, as in Federal Recycling's
# `-40.00/ST`. The suffix is what makes it a *rate* rather than an amount, and
# `money.MONEY_RE` already accepts the form. This is the "negative-priced
# commodity column" the pack spec names, and it is the only signal in the corpus
# that separates a contra from an ordinary invoice carrying a rebate line:
# U-PAK prints `-40.500` and Complete Beverage `-0.65`, both negative unit prices
# with no per-unit suffix, and neither document is a contra.
_UNIT_RATE = re.compile(r"(?<![\w.])(-?)(\d{1,3}(?:,\d{3})*\.\d{1,4})\s*/\s*[A-Za-z]{1,4}\b")

# --- tag signals ----------------------------------------------------------

_NEGATIVE_MONEY = re.compile(r"(?<![\w.])-\d{1,3}(?:,\d{3})*\.\d{2}\b|\(\d{1,3}(?:,\d{3})*\.\d{2}\)")
_AGING_HEADER = re.compile(r"\b30\s*DAYS\b.*\b60\s*DAYS\b", re.I)
_PAST_DUE = re.compile(r"\bPAST\s+DUE\b", re.I)
_MAX_PAST_DUE_LINE_WORDS = 6
_MAX_CREDIT_MEMO_LINE_WORDS = 7
# How many of page 1's lines count as "near the top", i.e. where a genuine
# document TITLE lives. Line length alone cannot separate a credit-memo title
# from a footnote reference to one: real OCR of Complete Beverage's "For
# remaining credited items refer to Credit memo 32684." wraps across two
# SHORT lines rather than one long prose line, so the short second line
# passes the word-count check exactly like a real title would. Position is
# the real discriminator, confirmed on the two real documents (whole-branch
# review finding 1): the genuine title on `_AP Invoice 32473 ...` sits at
# page-1 line index 5 of 20; the false-positive wrapped footnote on
# `_AP Invoice 32593 ...` sits at line index 25-26 of 30, deep in the page.
# 10 is wide enough to keep index 5 with room to spare and well short of 25.
_MAX_CREDIT_MEMO_LINE_INDEX = 10
_TAX_LINE = re.compile(r"\b(total tax|taxes|h\.?\s?s\.?\s?t\.?|g\.?\s?s\.?\s?t\.?)\b", re.I)
_SUB_ACCT = re.compile(r"\*\*?\s*SUB\s*ACCT", re.I)
_DISCOUNT = re.compile(r"\bdiscount\b", re.I)
_MONEY_RE = re.compile(r"\d[\d,]*\.\d{2}")

# OCR noise above which a page is taken to be handwriting rather than print.
# Measured on the corpus: Complete Beverage's handwritten Bill of Lading pages
# score 0.51 and 0.46, its printed invoice and certificate pages 0.22 and 0.28,
# and Federal Recycling's printed page 0.17. 0.40 sits in the gap with room on
# both sides.
HANDWRITING_NOISE_RATIO = 0.40



def _credit_memo_title_present(ctx: JobContext) -> bool:
    """Whether a genuine credit-memo TITLE sits near the top of page 1.

    Short-line length alone is not enough (see `_MAX_CREDIT_MEMO_LINE_INDEX`
    above for the real-document evidence): a footnote reference wrapped by
    OCR onto a short line reads identically to a real title if position is
    not also checked. Combines BOTH constraints - short line AND near the
    top - deliberately, rather than dropping the length check: a bare
    reuse of `_is_own_paperwork`'s head-window alone (no length constraint)
    could still be fooled by a short prose aside near the top of the page,
    which the corpus has not (yet) produced but which the length check
    guards against for free.

    Reuses `_is_own_paperwork`'s idiom of checking only the first few lines
    of page 1, the same pattern for the same reason: a genuine document
    title lives at the top of the page.

    Scope note (whole-branch review finding 4): the credit-memo check used
    to scan every page via `_short_line_has`, the same all-pages widening
    flagged for `has_tax`. This rewrite is narrower than even `primary_text()`
    - literal page 1 only, first `_MAX_CREDIT_MEMO_LINE_INDEX` lines - which
    removes that concern outright: a supporting attachment page can no
    longer contribute a false `credit_memo` title match, regardless of its
    role.

    Mechanics now live in `packs.signals.title_near_top`; the two constants
    remain this pack's policy, and the evidence for them is above.
    """
    return signals.title_near_top(
        ctx,
        _CREDIT_MEMO,
        max_words=_MAX_CREDIT_MEMO_LINE_WORDS,
        max_line_index=_MAX_CREDIT_MEMO_LINE_INDEX,
    )


def _aging_buckets_nonzero(text: str) -> bool:
    """Nonzero among the 30/60/90-day bucket columns only - the money
    tokens strictly between the first (CURRENT) and last (Please Pay) on
    the row. Both ends are deliberately excluded: CURRENT and Please Pay
    are nonzero on every real U-PAK invoice carrying any balance at all,
    aged or not - treating "any nonzero token on the raw row" as
    corroboration would therefore still fire on the exact
    all-buckets-empty documents this corroboration exists to catch
    (verified: `AMOUNT 6763.96 0.00 0.00 0.00 $6763.96` has a nonzero
    CURRENT/Please Pay with nothing actually aged). Requiring a real
    30/60/90 figure is what a genuinely overdue account has that a
    current-only one does not - confirmed against real U-PAK second
    samples that DO carry one (`... 0.01 0.00 0.00 ...`, `... 0.00 4476.34
    0.02 ...`)."""
    tokens = _MONEY_RE.findall(text)
    middle = tokens[1:-1] if len(tokens) > 2 else []
    for token in middle:
        cleaned = token.replace(",", "")
        try:
            if float(cleaned) != 0.0:
                return True
        except ValueError:
            continue
    return False


def _aging_table_has_balance(ctx: JobContext) -> bool:
    """`_AGING_HEADER` finds the column-header row; this corroborates it
    against the value row, which in every corpus/second-sample document is
    either the same visual line (rare) or the next one.

    Deliberately scans every page, not just primary ones (whole-branch
    review finding 4). This is not a new widening: `past_due`'s OTHER half
    of the check, `_short_line_has(ctx, _PAST_DUE, ...)`, has scanned every
    page since before this plan (see its own docstring re: Federal
    Recycling's terms-and-conditions page), and that decision was already
    reviewed and accepted. Scoping only this corroboration to primary pages
    would not remove the risk - the disjunction it corroborates already
    reads every page - so it would just make the two halves of one `past_due`
    check inconsistent with each other for no safety gain. Empirically, this
    is also moot: every real `_AGING_HEADER` match in the corpus and
    second-samples (U-Pak) is on a primary page already, since U-Pak's
    repeating template marks every one of its pages primary."""
    everything = "\n".join(p.text for p in ctx.pages)
    if not _AGING_HEADER.search(everything):
        return False
    return signals.label_with_corroborating_value(
        ctx,
        _AGING_HEADER,
        same_line=_aging_buckets_nonzero,
        next_line=_aging_buckets_nonzero,
        # Every page, preserving the scope this docstring justifies above. Not
        # to be "tidied" to the default.
        primary_only=False,
    )


def _tax_value_nonzero(text: str) -> bool:
    """The tax amount in a column-header table (Veritiv's discount/weight/
    subtotal/'Total Tax'/'Amount Due' row) is the second-to-last money token
    on the data row, immediately before the trailing grand total - NOT just
    'any nonzero token on the line', because Subtotal (and this vendor's
    discount columns) are nonzero on every real invoice and would otherwise
    make the check trivially true on exactly the $0.00-tax documents it
    exists to catch. Verified against all 7 real Veritiv second samples:
    taxed invoices read '...0.00 0.00 299.55 4,908.00' (2nd-to-last
    nonzero); untaxed ones (non-taxable items) read '...0.00 0.00 0.00
    625.00' (2nd-to-last zero, only the trailing total is nonzero)."""
    tokens = _MONEY_RE.findall(text)
    if not tokens:
        return False
    candidate = tokens[-2] if len(tokens) >= 2 else tokens[-1]
    cleaned = candidate.replace(",", "")
    try:
        return float(cleaned) != 0.0
    except ValueError:
        return False


def _same_line_tax_value_nonzero(text: str) -> bool:
    """The tax amount immediately following the tax label on the SAME
    line - not 'any nonzero token on the line', which would let a nonzero
    Sub Total or Total (present on every real invoice) corroborate a
    genuinely zero tax value, reproducing the exact false-positive class
    this whole corroboration exists to fix. Verified against the real
    same-line match, U-PAK's 'H.S.T. # 123142812RT0001    2,325.69': the
    registration number isn't money-shaped (no decimal point), so the
    first money token found after the label match is the real tax
    amount, 2,325.69 - not the label's own text and not some other
    column's total."""
    for label_match in _TAX_LINE.finditer(text):
        after = text[label_match.end():]
        money_match = _MONEY_RE.search(after)
        if not money_match:
            continue
        cleaned = money_match.group(0).replace(",", "")
        try:
            if float(cleaned) != 0.0:
                return True
        except ValueError:
            continue
    return False


def _short_line_has_nonzero_tax(ctx: JobContext) -> bool:
    """Whether a tax label on the primary page(s) is corroborated by a
    nonzero value, same line or the next.

    Narrowed to primary-role pages (whole-branch review finding 4): Task 6
    introduced this helper scanning EVERY page, which contradicts
    `primary_text()`'s documented contract (registry.py) that a supporting
    page - a Bill of Lading, a certificate - may carry facts (a different
    tax regime, a different total) that are not statements about the
    invoice it's attached to. A stapled BOL naming an unrelated "Taxes"
    line would, under the all-pages version, wrongly tag a tax-exempt
    parent invoice `has_tax`. Narrowing to primary pages costs nothing real:
    every actual `_TAX_LINE` match in the corpus and all 7 Veritiv plus all
    U-Pak second samples is already on that document's own primary page(s)."""
    return signals.label_with_corroborating_value(
        ctx,
        _TAX_LINE,
        same_line=_same_line_tax_value_nonzero,
        next_line=_tax_value_nonzero,
        primary_only=True,
    )



def doc_type_for(ctx: JobContext) -> tuple[str, str]:
    """(doc_type, signal_that_fired). The section 1 ladder, in order.

    Every rung is now a composition of `packs.signals` primitives plus this
    pack's own patterns and cutoffs. That split is what lets the ladder be
    expressed as data: the mechanics are named, the policy stays here.
    """
    if _credit_memo_title_present(ctx):
        return "credit_memo", "credit_memo_title"

    if signals.all_matches_negative(ctx, _UNIT_RATE, scope="primary"):
        # Every per-unit rate on the page is negative: the commodity lines are
        # all credits. Positive service lines (Federal Recycling's HAUL FEE) are
        # flat amounts with no rate, so they do not disturb this.
        return "contra_invoice", "all_commodity_rates_negative"

    if signals.role_shape(
        ctx, primary_exactly=1, supporting_at_least=1
    ) and not signals.shared_pagination_footer(ctx):
        return "invoice_with_attachment", "one_primary_plus_supporting"

    if signals.pattern_in_scope(
        ctx, _STATEMENT, scope="primary"
    ) and not signals.money_table_present(ctx):
        return "statement_of_account", "statement_title_no_table"

    if signals.text_near_top(ctx, _NORTHSTAR_LETTERHEAD, max_line_index=4):
        # Every document in the corpus names Northstar somewhere - it is the
        # bill-to on all six - so only the first few lines can carry this.
        return "own_paperwork", "northstar_letterhead"

    return "standard_invoice", "default"





def tags_for(ctx: JobContext) -> list[str]:
    """Every tag the document earns. Layered on; never changes the type."""
    tags: list[str] = []

    if signals.pattern_in_scope(ctx, _NEGATIVE_MONEY, scope="primary"):
        tags.append("mixed_sign")

    # `primary_only=False` is DELIBERATE and must not be tidied to the default.
    # Federal Recycling's terms-and-conditions page is a supporting page, and
    # this check has read every page since before the 2026-08-06 plan - a
    # decision that was reviewed and accepted then. Pinned by
    # `test_northstar_ladder.py::test_a_past_due_banner_on_a_supporting_page_still_tags`,
    # because a superset gold assertion cannot see a tag that stops firing.
    banner = signals.short_label_line(
        ctx, _PAST_DUE, _MAX_PAST_DUE_LINE_WORDS, primary_only=False
    )
    if banner or _aging_table_has_balance(ctx):
        tags.append("past_due")

    if _short_line_has_nonzero_tax(ctx):
        tags.append("has_tax")

    if signals.pattern_in_scope(ctx, _SUB_ACCT, scope="all"):
        tags.append("sub_accounts")

    if signals.text_source_is(ctx, value="ocr"):
        tags.append("ocr_only")

    if signals.pattern_in_scope(ctx, _DISCOUNT, scope="primary"):
        tags.append("early_pay_discount")

    # Supporting pages only (F10, Complete Beverage p2-p3), which removes the
    # whole false-positive risk: Federal Recycling carries a handwritten margin
    # note that OCR transcribes, but it is a single-page document with no
    # supporting page, and its gold label is correctly not tagged.
    if signals.noise_ratio_above(ctx, threshold=HANDWRITING_NOISE_RATIO):
        tags.append("handwritten_supporting")

    return tags



def classify(ctx: JobContext) -> JobContext:
    """Set `doc_type`, `signal_that_fired` and the tags. Idempotent."""
    doc_type, signal = doc_type_for(ctx)
    ctx.doc_type = doc_type
    ctx.signal_that_fired = signal
    ctx.classification_confidence = 0.95 if signal != "default" else 0.80
    for tag in tags_for(ctx):
        ctx.add_tag(tag)
    return ctx
