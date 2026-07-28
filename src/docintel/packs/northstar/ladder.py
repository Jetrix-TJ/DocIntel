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
_TAX_LINE = re.compile(r"\b(total tax|taxes|h\.?\s?s\.?\s?t\.?|g\.?\s?s\.?\s?t\.?)\b", re.I)
_SUB_ACCT = re.compile(r"\*\*?\s*SUB\s*ACCT", re.I)
_DISCOUNT = re.compile(r"\bdiscount\b", re.I)

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


def _roles(ctx: JobContext) -> tuple[int, int]:
    primary = sum(1 for m in ctx.page_meta if m.role == "primary")
    supporting = sum(1 for m in ctx.page_meta if m.role != "primary")
    return primary, supporting


def doc_type_for(ctx: JobContext) -> tuple[str, str]:
    """(doc_type, signal_that_fired). The section 1 ladder, in order."""
    text = primary_text(ctx)

    if _CREDIT_MEMO.search(text):
        return "credit_memo", "credit_memo_title"

    rates = _UNIT_RATE.findall(text)
    if rates and all(sign == "-" for sign, _ in rates):
        # Every per-unit rate on the page is negative: the commodity lines are
        # all credits. Positive service lines (Federal Recycling's HAUL FEE) are
        # flat amounts with no rate, so they do not disturb this.
        return "contra_invoice", "all_commodity_rates_negative"

    primary, supporting = _roles(ctx)
    if primary == 1 and supporting >= 1:
        return "invoice_with_attachment", "one_primary_plus_supporting"

    if _STATEMENT.search(text) and not _has_table(ctx):
        return "statement_of_account", "statement_title_no_table"

    if _is_own_paperwork(ctx):
        return "own_paperwork", "northstar_letterhead"

    return "standard_invoice", "default"


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

    if _short_line_has(ctx, _PAST_DUE, _MAX_PAST_DUE_LINE_WORDS) or _AGING_HEADER.search(
        everything
    ):
        tags.append("past_due")

    if _TAX_LINE.search(text):
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
