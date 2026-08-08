"""The closed signal registry — the classification analogue of the grammar's
`BASE_ADJUST_OPS`.

Every primitive here was invented inside `northstar/ladder.py` to fix a
specific, named, real-document defect, and every one was then NOT applied to the
identical check in `digitaldirection/ladder.py` — which is how Windstream ships
a `past_due` false positive that Northstar's ladder would have rejected. Owning
them here, tested once, is what lets a declarative ladder name a signal instead
of restating its mechanics, and what makes the next fix reach both packs.

**The boundary tests matter as much as the behavioural ones.** Without them the
cutoffs are unpinned: measured on the first draft of this module, `max_line_index`
could be changed from 10 to anything in [6, 25] and every behavioural test still
passed. A constant nothing pins is a constant the next person will "tidy".
"""

from __future__ import annotations

import re

from docintel.core.models import PageMeta, PageText, Word, new_context
from docintel.packs import signals

# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


def _page(text: str, number: int = 1) -> PageText:
    """`|`-separated rows become visual lines — the convention already used in
    `test_digitaldirection_ladder.py` and `test_claim_precision.py`. Row pitch
    (14pt) is well clear of `geometry.DEFAULT_TOLERANCE`, so rows never merge."""
    words: list[Word] = []
    for row, line in enumerate(text.split("|")):
        y = 100.0 + row * 14.0
        for i, tok in enumerate(line.split()):
            words.append(
                Word(text=tok, x0=10.0 + 40.0 * i, y0=y, x1=45.0 + 40.0 * i, y1=y + 10.0)
            )
    return PageText(
        page_number=number, words=tuple(words), width=612.0, height=792.0, source="native"
    )


def _ctx(*pages_and_roles: tuple[str, str]):
    ctx = new_context("d", "/x.pdf")
    pages, meta = [], []
    for n, (text, role) in enumerate(pages_and_roles, start=1):
        pages.append(_page(text, n))
        meta.append(PageMeta(n, 100, 0, 0, role))
    ctx.pages = tuple(pages)
    ctx.page_meta = tuple(meta)
    return ctx


PAST_DUE = re.compile(r"\bPAST\s+DUE\b", re.I)
CREDIT_MEMO = re.compile(r"\b(credit memo|credit note|adjustment note)\b", re.I)
TAX = re.compile(r"\b(total tax|taxes)\b", re.I)
MONEY = re.compile(r"\d[\d,]*\.\d{2}")


def _second_to_last_nonzero(text: str) -> bool:
    """Veritiv's shape: the tax amount is the token immediately before the
    trailing grand total."""
    tokens = MONEY.findall(text)
    if not tokens:
        return False
    candidate = tokens[-2] if len(tokens) >= 2 else tokens[-1]
    try:
        return float(candidate.replace(",", "")) != 0.0
    except ValueError:
        return False


# --------------------------------------------------------------------------
# primary_pages
# --------------------------------------------------------------------------


def test_primary_pages_selects_only_primary_roles() -> None:
    ctx = _ctx(("invoice", "primary"), ("bill of lading", "supporting"))
    assert [p.page_number for p in signals.primary_pages(ctx)] == [1]


def test_primary_pages_falls_back_to_every_page_when_no_roles_assigned() -> None:
    """Mirrors `registry.primary_text`'s documented fallback: a classifier that
    classifies nothing is worse than one that reads a supporting page, and
    Stage 2 always assigns roles before Stage 3 in the real pipeline."""
    ctx = _ctx(("invoice", "primary"), ("more", "supporting"))
    ctx.page_meta = ()
    assert [p.page_number for p in signals.primary_pages(ctx)] == [1, 2]


def test_primary_text_is_built_from_primary_pages() -> None:
    """`registry.primary_text` must be the same selection, not a second copy of
    the rule that happens to agree today."""
    from docintel.packs.registry import primary_text

    ctx = _ctx(("the invoice", "primary"), ("the attachment", "supporting"))
    assert primary_text(ctx) == "\n".join(p.text for p in signals.primary_pages(ctx))
    assert "attachment" not in primary_text(ctx)


# --------------------------------------------------------------------------
# short_label_line
# --------------------------------------------------------------------------


def test_short_label_line_matches_a_standalone_banner() -> None:
    assert signals.short_label_line(_ctx(("PAST DUE", "primary")), PAST_DUE, 6) is True


def test_short_label_line_rejects_the_same_phrase_inside_prose() -> None:
    """Federal Recycling's boilerplate terms, printed on every invoice that
    vendor sends, and correctly NOT tagged `past_due` in gold."""
    ctx = _ctx(
        ("PAST DUE AMOUNTS SUBJECT TO INTEREST FEES IN THE AMOUNT OF 18.99%", "primary"),
    )
    assert signals.short_label_line(ctx, PAST_DUE, 6) is False


def test_short_label_line_ignores_supporting_pages_by_default() -> None:
    """The Windstream defect. Page 3 of `Windstream_041069076` — a SUPPORTING
    page — prints the wrapped fragment 'any past due Internet balance.', which
    is 5 words, so NO word-count cutoff can reject it. Page scope can."""
    ctx = _ctx(("ordinary bill", "primary"), ("any past due Internet balance.", "supporting"))
    assert signals.short_label_line(ctx, PAST_DUE, 8) is False


def test_short_label_line_can_opt_into_every_page() -> None:
    """Northstar's `past_due` banner check deliberately reads every page —
    Federal Recycling's terms live on their own page. The widening must be
    requested explicitly, never inherited."""
    ctx = _ctx(("ordinary bill", "primary"), ("PAST DUE", "supporting"))
    assert signals.short_label_line(ctx, PAST_DUE, 8, primary_only=False) is True


def test_short_label_line_accepts_a_line_of_exactly_max_words() -> None:
    """BOUNDARY. Pins the cutoff itself, not just behaviour either side of it."""
    ctx = _ctx(("PAST DUE ON THIS ACCOUNT NOW", "primary"))  # 6 words
    assert signals.short_label_line(ctx, PAST_DUE, 6) is True


def test_short_label_line_rejects_a_line_one_word_over() -> None:
    """BOUNDARY."""
    ctx = _ctx(("PAST DUE ON THIS ACCOUNT RIGHT NOW", "primary"))  # 7 words
    assert signals.short_label_line(ctx, PAST_DUE, 6) is False


# --------------------------------------------------------------------------
# title_near_top
# --------------------------------------------------------------------------


def test_title_near_top_matches_a_real_title() -> None:
    """The genuine title on `_AP Invoice 32473` sits at page-1 line index 5."""
    body = "|".join(["filler"] * 5 + ["CREDIT MEMO"] + ["filler"] * 14)
    ctx = _ctx((body, "primary"))
    assert signals.title_near_top(ctx, CREDIT_MEMO, max_words=7, max_line_index=10) is True


def test_title_near_top_rejects_a_wrapped_footnote_deep_in_the_page() -> None:
    """`_AP Invoice 32593`'s footnote — 'For remaining credited items refer to /
    Credit memo 32684.' — wraps onto SHORT lines at index 25-26 under real OCR,
    so it passes a word-count check exactly like a title. Position is the
    discriminator."""
    body = "|".join(["filler"] * 25 + ["Credit memo 32684."] + ["filler"] * 4)
    ctx = _ctx((body, "primary"))
    assert signals.title_near_top(ctx, CREDIT_MEMO, max_words=7, max_line_index=10) is False


def test_title_near_top_reads_page_1_only() -> None:
    """Narrower than `primary_pages` on purpose: a supporting attachment page
    can never contribute a title match, whatever its role."""
    ctx = _ctx(("filler", "primary"), ("CREDIT MEMO", "primary"))
    assert signals.title_near_top(ctx, CREDIT_MEMO, max_words=7, max_line_index=10) is False


def test_title_near_top_accepts_the_last_line_inside_the_window() -> None:
    """BOUNDARY. Index 9 is inside a window of 10."""
    body = "|".join(["filler"] * 9 + ["CREDIT MEMO"] + ["filler"] * 5)
    ctx = _ctx((body, "primary"))
    assert signals.title_near_top(ctx, CREDIT_MEMO, max_words=7, max_line_index=10) is True


def test_title_near_top_rejects_the_first_line_outside_the_window() -> None:
    """BOUNDARY. Index 10 is outside a window of 10."""
    body = "|".join(["filler"] * 10 + ["CREDIT MEMO"] + ["filler"] * 5)
    ctx = _ctx((body, "primary"))
    assert signals.title_near_top(ctx, CREDIT_MEMO, max_words=7, max_line_index=10) is False


def test_title_near_top_accepts_a_line_of_exactly_max_words() -> None:
    """BOUNDARY on the OTHER constraint. Both are load-bearing: the first draft
    of this module tested only 2-3 word titles, so deleting the length check
    left every test in this file green."""
    body = "|".join([("CREDIT MEMO FOR RETURNED GOODS THIS MONTH")] + ["filler"] * 5)  # 7
    ctx = _ctx((body, "primary"))
    assert signals.title_near_top(ctx, CREDIT_MEMO, max_words=7, max_line_index=10) is True


def test_title_near_top_rejects_a_line_one_word_over() -> None:
    """BOUNDARY."""
    body = "|".join([("CREDIT MEMO FOR RETURNED GOODS LATE THIS MONTH")] + ["filler"] * 5)  # 8
    ctx = _ctx((body, "primary"))
    assert signals.title_near_top(ctx, CREDIT_MEMO, max_words=7, max_line_index=10) is False


# --------------------------------------------------------------------------
# label_with_corroborating_value
# --------------------------------------------------------------------------


def test_a_nonzero_value_on_the_next_line_corroborates() -> None:
    ctx = _ctx(("Total Tax|0.00 0.00 299.55 4,908.00", "primary"))
    assert (
        signals.label_with_corroborating_value(ctx, TAX, next_line=_second_to_last_nonzero)
        is True
    )


def test_a_zero_value_does_not_corroborate() -> None:
    """The whole point. The column LABEL is printed on every Veritiv invoice,
    taxed or not — matching it alone makes the check trivially true on exactly
    the documents it exists to catch."""
    ctx = _ctx(("Total Tax|0.00 0.00 0.00 625.00", "primary"))
    assert (
        signals.label_with_corroborating_value(ctx, TAX, next_line=_second_to_last_nonzero)
        is False
    )


def test_a_label_with_no_value_row_at_all_does_not_corroborate() -> None:
    ctx = _ctx(("Total Tax", "primary"))
    assert (
        signals.label_with_corroborating_value(ctx, TAX, next_line=_second_to_last_nonzero)
        is False
    )


def test_a_same_line_value_corroborates() -> None:
    """U-PAK's shape: 'H.S.T. # 123142812RT0001    2,325.69' — label and value
    on one visual line."""
    ctx = _ctx(("Total Tax 2,325.69", "primary"))
    assert (
        signals.label_with_corroborating_value(
            ctx, TAX, same_line=lambda t: bool(MONEY.search(t))
        )
        is True
    )


def test_it_reads_primary_pages_by_default() -> None:
    """A stapled Bill of Lading naming a different tax regime is not a statement
    about the invoice it is attached to."""
    ctx = _ctx(("ordinary invoice", "primary"), ("Total Tax|0.00 0.00 299.55 4,908.00", "supporting"))
    assert (
        signals.label_with_corroborating_value(ctx, TAX, next_line=_second_to_last_nonzero)
        is False
    )


# --------------------------------------------------------------------------
# The primitives lifted out of the two packs' ladders
# --------------------------------------------------------------------------


SUB_ACCT = re.compile(r"\*\*?\s*SUB\s*ACCT", re.I)
LETTERHEAD = re.compile(r"\bnorthstar recycling\b", re.I)
UNIT_RATE = re.compile(r"(?<![\w.])(-?)(\d{1,3}(?:,\d{3})*\.\d{1,4})\s*/\s*[A-Za-z]{1,4}\b")


def test_scope_primary_excludes_supporting_pages() -> None:
    ctx = _ctx(("the invoice", "primary"), ("the attachment", "supporting"))
    assert "attachment" not in signals.scope_text(ctx, "primary")
    assert "attachment" in signals.scope_text(ctx, "all")


def test_scope_page1_is_literally_page_one() -> None:
    ctx = _ctx(("first", "primary"), ("second", "primary"))
    assert signals.scope_text(ctx, "page1") == "first"


def test_an_unknown_scope_raises_rather_than_silently_reading_nothing() -> None:
    """A declarative rung naming a bad scope must fail loudly. Returning "" would
    make the signal quietly false and the document quietly misclassified."""
    ctx = _ctx(("x", "primary"))
    try:
        signals.scope_text(ctx, "everything")
    except ValueError as exc:
        assert "everything" in str(exc)
    else:  # pragma: no cover - the assertion below is the failure message
        raise AssertionError("an unknown scope must raise")


def test_pattern_in_scope_respects_its_scope() -> None:
    ctx = _ctx(("invoice", "primary"), ("** SUB ACCT 12", "supporting"))
    assert signals.pattern_in_scope(ctx, SUB_ACCT, scope="all") is True
    assert signals.pattern_in_scope(ctx, SUB_ACCT, scope="primary") is False


def test_text_near_top_matches_a_long_letterhead_line() -> None:
    """The case `title_near_top` deliberately cannot serve: a letterhead is a
    company name and address block, legitimately longer than a title."""
    body = "Northstar Recycling Company LLC 94 Maple St East Longmeadow MA 01028|rest"
    assert signals.text_near_top(_ctx((body, "primary")), LETTERHEAD, max_line_index=4) is True


def test_text_near_top_ignores_the_same_name_further_down() -> None:
    """Every corpus document names Northstar somewhere - it is the bill-to on all
    six - so a whole-page search would call every one own paperwork."""
    body = "|".join(["ACME VENDOR"] * 6 + ["Bill To Northstar Recycling"])
    assert signals.text_near_top(_ctx((body, "primary")), LETTERHEAD, max_line_index=4) is False


def test_all_matches_negative_when_every_rate_is_negative() -> None:
    ctx = _ctx(("OCC -40.00/ST|HAUL FEE 200.00", "primary"))
    assert signals.all_matches_negative(ctx, UNIT_RATE, scope="primary") is True


def test_all_matches_negative_is_false_when_one_rate_is_positive() -> None:
    ctx = _ctx(("OCC -40.00/ST|MIXED 12.50/ST", "primary"))
    assert signals.all_matches_negative(ctx, UNIT_RATE, scope="primary") is False


def test_all_matches_negative_requires_at_least_one_match() -> None:
    """"No rates at all" is not "all rates negative". A vacuous truth here would
    make every invoice without a rate column a contra."""
    ctx = _ctx(("HAUL FEE 200.00", "primary"))
    assert signals.all_matches_negative(ctx, UNIT_RATE, scope="primary") is False


def test_role_shape_matches_one_primary_plus_supporting() -> None:
    ctx = _ctx(("inv", "primary"), ("bol", "supporting"))
    assert signals.role_shape(ctx, primary_exactly=1, supporting_at_least=1) is True


def test_role_shape_rejects_an_all_primary_document() -> None:
    """U-PAK's five-page repeating template comes out all-primary, and must not
    read as an invoice with an attachment."""
    ctx = _ctx(("p1", "primary"), ("p2", "primary"))
    assert signals.role_shape(ctx, primary_exactly=1, supporting_at_least=1) is False


def test_money_table_present_needs_several_money_tokens_on_one_line() -> None:
    assert signals.money_table_present(_ctx(("1.00 2.00 3.00", "primary"))) is True
    assert signals.money_table_present(_ctx(("Total 1.00", "primary"))) is False


def test_text_source_is() -> None:
    ctx = _ctx(("x", "primary"))
    ctx.text_source = "ocr"
    assert signals.text_source_is(ctx, value="ocr") is True
    assert signals.text_source_is(ctx, value="native") is False


def test_noise_ratio_reads_supporting_pages_only() -> None:
    """Federal Recycling carries a handwritten margin note that OCR transcribes,
    but it is a single-page document with no supporting page - and its gold
    label is correctly not tagged."""
    noisy = "eo eS xz qq zz ll pp mm nn bb vv cc"
    ctx = _ctx((noisy, "primary"))
    ctx.text_source = "ocr"
    assert signals.noise_ratio_above(ctx, threshold=0.40) is False

    ctx2 = _ctx(("a clean printed invoice line", "primary"), (noisy, "supporting"))
    ctx2.text_source = "ocr"
    assert signals.noise_ratio_above(ctx2, threshold=0.40) is True


def test_noise_ratio_is_native_text_blind() -> None:
    """A text layer is not handwriting, whatever its tokens look like."""
    ctx = _ctx(("clean", "primary"), ("eo eS xz qq zz ll", "supporting"))
    ctx.text_source = "native"
    assert signals.noise_ratio_above(ctx, threshold=0.40) is False


class _FakePack:
    vendor_aliases = {"lumen": "lumen", "centurylink": "lumen", "comcast": "comcast"}


def test_distinct_printed_aliases_reads_the_packs_own_table() -> None:
    ctx = _ctx(("LUMEN a CenturyLink company", "primary"))
    ctx.pack = _FakePack()
    assert signals.distinct_printed_aliases_at_least(ctx, count=2) is True
    assert signals.distinct_printed_aliases_at_least(ctx, count=3) is False


def test_distinct_printed_aliases_with_no_pack_is_false_not_an_error() -> None:
    """Stage 3 runs the ladder after `resolve_pack`, but a hook or a test may
    reach a signal with no pack bound; a crash there would dead-letter a
    document over a tag."""
    ctx = _ctx(("LUMEN", "primary"))
    assert signals.distinct_printed_aliases_at_least(ctx, count=1) is False
