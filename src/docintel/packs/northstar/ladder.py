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

from docintel.core import pagination
from docintel.core.models import JobContext
from docintel.packs.registry import primary_text

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
_ODD_CHARS = re.compile(r"[^\w\s.,/$#&()'-]")


def _noise_ratio(text_tokens: list[str]) -> float:
    """Share of tokens that do not look like printed words.

    Three cheap signals, because OCR of handwriting fails in three ways: it
    produces fragments (`eo`, `eS`), it drops vowels (`Traotor`, `Looeition`),
    and it invents punctuation. None is reliable alone; the ratio is.
    """
    if not text_tokens:
        return 0.0

    def odd(token: str) -> bool:
        if len(token) <= 2:
            return True
        if token.isalpha() and not re.search(r"[aeiouAEIOU]", token):
            return True
        return bool(_ODD_CHARS.search(token))

    return sum(odd(t) for t in text_tokens) / len(text_tokens)


def _short_line_has(ctx: JobContext, pattern: re.Pattern[str], max_words: int) -> bool:
    """Whether `pattern` appears on a SHORT line, not buried in prose.

    Federal Recycling's terms and conditions read "PAST DUE AMOUNTS SUBJECT TO
    INTEREST FEES IN THE AMOUNT OF 18.99% ANNUALLY..." - boilerplate on every
    invoice this vendor sends, and its gold label is correctly not tagged
    `past_due`. EDCO's is a standalone `PAST DUE` banner. The difference is line
    length, the same discriminator `extract.pageroles` uses for the same reason.
    """
    for page in ctx.pages:
        for line in page.lines():
            if len(line) > max_words:
                continue
            if pattern.search(" ".join(w.text for w in line)):
                return True
    return False


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
    """
    if not ctx.pages:
        return False
    head = ctx.pages[0].lines()[:_MAX_CREDIT_MEMO_LINE_INDEX]
    for line in head:
        if len(line) > _MAX_CREDIT_MEMO_LINE_WORDS:
            continue
        if _CREDIT_MEMO.search(" ".join(w.text for w in line)):
            return True
    return False


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


def _primary_pages(ctx: JobContext) -> list:
    """Pages restricted to primary role, mirroring `primary_text()`'s own
    fallback (registry.py): if no roles are assigned yet, every page counts,
    since Stage 2 always assigns roles before Stage 3 runs for real."""
    primary = {m.page_number for m in ctx.page_meta if m.role == "primary"}
    if not primary:
        return list(ctx.pages)
    return [p for p in ctx.pages if p.page_number in primary]


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
    for page in ctx.pages:
        lines = page.lines()
        for i, line in enumerate(lines):
            text = " ".join(w.text for w in line)
            if not _AGING_HEADER.search(text):
                continue
            if _aging_buckets_nonzero(text):
                return True
            if i + 1 < len(lines):
                next_text = " ".join(w.text for w in lines[i + 1])
                if _aging_buckets_nonzero(next_text):
                    return True
    return False


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
    for page in _primary_pages(ctx):
        lines = page.lines()
        for i, line in enumerate(lines):
            text = " ".join(w.text for w in line)
            if not _TAX_LINE.search(text):
                continue
            if _same_line_tax_value_nonzero(text):
                return True
            if i + 1 < len(lines):
                next_text = " ".join(w.text for w in lines[i + 1])
                if _tax_value_nonzero(next_text):
                    return True
    return False


def _roles(ctx: JobContext) -> tuple[int, int]:
    primary = sum(1 for m in ctx.page_meta if m.role == "primary")
    supporting = sum(1 for m in ctx.page_meta if m.role != "primary")
    return primary, supporting


def doc_type_for(ctx: JobContext) -> tuple[str, str]:
    """(doc_type, signal_that_fired). The section 1 ladder, in order."""
    text = primary_text(ctx)

    if _credit_memo_title_present(ctx):
        return "credit_memo", "credit_memo_title"

    rates = _UNIT_RATE.findall(text)
    if rates and all(sign == "-" for sign, _ in rates):
        # Every per-unit rate on the page is negative: the commodity lines are
        # all credits. Positive service lines (Federal Recycling's HAUL FEE) are
        # flat amounts with no rate, so they do not disturb this.
        return "contra_invoice", "all_commodity_rates_negative"

    primary, supporting = _roles(ctx)
    if primary == 1 and supporting >= 1 and not _is_paginated_continuation(ctx):
        return "invoice_with_attachment", "one_primary_plus_supporting"

    if _STATEMENT.search(text) and not _has_table(ctx):
        return "statement_of_account", "statement_title_no_table"

    if _is_own_paperwork(ctx):
        return "own_paperwork", "northstar_letterhead"

    return "standard_invoice", "default"


def _is_paginated_continuation(ctx: JobContext) -> bool:
    """True if every page carries a `N OF M` footer with M == len(ctx.pages).

    A real attachment (a Bill of Lading stapled behind an invoice) has no
    reason to share the invoice's own pagination sequence. A genuine
    multi-page invoice whose totals label overflowed onto a later page - the
    same (primary=1, supporting>=1) role shape the ladder otherwise reads as
    "invoice plus attachment" - does. Reading the real printed footer, not
    guessing from role counts, is what tells the two apart.
    """
    return pagination.shared_footer_pages(ctx.pages) is not None


def _has_table(ctx: JobContext) -> bool:
    """A crude but honest table test: a line with three or more money tokens."""
    for page in ctx.pages:
        for line in page.lines():
            money = sum(1 for w in line if re.fullmatch(r"[\d,]+\.\d{2}", w.text))
            if money >= 3:
                return True
    return False


def _is_own_paperwork(ctx: JobContext) -> bool:
    """Northstar's own letterhead, i.e. this is not a vendor invoice at all.

    Checked on the FIRST few lines only. Every document in the corpus names
    Northstar somewhere - it is the bill-to on all six - so a whole-page search
    would classify every one of them as own paperwork.
    """
    if not ctx.pages:
        return False
    head = ctx.pages[0].lines()[:4]
    return any(
        _NORTHSTAR_LETTERHEAD.search(" ".join(w.text for w in line)) for line in head
    )


def tags_for(ctx: JobContext) -> list[str]:
    """Every tag the document earns. Layered on; never changes the type."""
    text = primary_text(ctx)
    everything = "\n".join(p.text for p in ctx.pages)
    tags: list[str] = []

    if _NEGATIVE_MONEY.search(text):
        tags.append("mixed_sign")

    if _short_line_has(ctx, _PAST_DUE, _MAX_PAST_DUE_LINE_WORDS) or _aging_table_has_balance(ctx):
        tags.append("past_due")

    if _short_line_has_nonzero_tax(ctx):
        tags.append("has_tax")

    if _SUB_ACCT.search(everything):
        tags.append("sub_accounts")

    if ctx.text_source == "ocr":
        tags.append("ocr_only")

    if _DISCOUNT.search(text):
        tags.append("early_pay_discount")

    if _handwritten_supporting(ctx):
        tags.append("handwritten_supporting")

    return tags


def _handwritten_supporting(ctx: JobContext) -> bool:
    """Handwriting on a supporting page (F10, Complete Beverage p2-p3).

    Only supporting pages are examined, which removes the whole false-positive
    risk: Federal Recycling carries a handwritten margin note that OCR
    transcribes, but it is a single-page document with no supporting page, and
    its gold label is correctly not tagged.
    """
    if ctx.text_source != "ocr":
        return False
    supporting = {m.page_number for m in ctx.page_meta if m.role != "primary"}
    for page in ctx.pages:
        if page.page_number not in supporting:
            continue
        if _noise_ratio([w.text for w in page.words]) >= HANDWRITING_NOISE_RATIO:
            return True
    return False


def classify(ctx: JobContext) -> JobContext:
    """Set `doc_type`, `signal_that_fired` and the tags. Idempotent."""
    doc_type, signal = doc_type_for(ctx)
    ctx.doc_type = doc_type
    ctx.signal_that_fired = signal
    ctx.classification_confidence = 0.95 if signal != "default" else 0.80
    for tag in tags_for(ctx):
        ctx.add_tag(tag)
    return ctx
