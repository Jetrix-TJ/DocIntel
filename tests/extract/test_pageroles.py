import glob
import json
import logging
import os

import pytest

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.extract import pageroles
from docintel.extract.normalize import load_document
from docintel.pipeline.stages import s2_filter

GOLD_DIR = os.path.join("docs", "corpus", "gold")

# ---------------------------------------------------------------------------
# Synthetic fixtures. The corpus-driven tests above and below this section
# can only prove the rule *fits* the ten real documents; they are structurally
# unable to prove it *generalizes*, since a rule tuned to always pick page 1
# would pass every one of them too. These build fabricated PageText/PageMeta
# objects directly, so they can exercise page-index-independent behaviour
# that no document in the corpus happens to require.
# ---------------------------------------------------------------------------


def _line_words(words: list[str], y0: float) -> list[Word]:
    x = 0.0
    out = []
    for w in words:
        out.append(Word(text=w, x0=x, y0=y0, x1=x + len(w), y1=y0 + 10.0))
        x += len(w) + 5.0
    return out


def _page(number: int, lines: list[list[str]], source: str = "native") -> PageText:
    """Build a PageText whose visual lines are exactly `lines` — each inner
    list of word-strings becomes one line, spaced 20pt apart vertically so
    `PageText.lines()`'s y-tolerance grouping can't merge them.
    """
    words: list[Word] = []
    for i, line in enumerate(lines):
        words.extend(_line_words(line, y0=i * 20.0))
    return PageText(page_number=number, words=tuple(words), width=612.0, height=792.0, source=source)


def _blank_page(number: int, source: str = "native") -> PageText:
    return PageText(page_number=number, words=(), width=612.0, height=792.0, source=source)


def _meta(pages: list[PageText]) -> tuple[PageMeta, ...]:
    return tuple(
        PageMeta(page_number=p.page_number, char_count=len(p.words), image_count=0, annot_count=0)
        for p in pages
    )


ANCHOR_LINE = ["Account", "Number:", "12345"]
TOTALS_LINE = ["Total", "Amount", "Due:", "$500.00"]
NOISE_LINE = ["Some", "unrelated", "line", "item", "text"]


def _gold_cases():
    cases = []
    for path in sorted(glob.glob(os.path.join(GOLD_DIR, "*.json"))):
        with open(path) as fh:
            gold = json.load(fh)
        cases.append((gold["gold_id"], gold["source_file"], gold["classification"]["page_roles"]))
    return cases


GOLD_CASES = _gold_cases()


@pytest.mark.parametrize(
    "gold_id,source_file,expected_roles", GOLD_CASES, ids=[c[0] for c in GOLD_CASES]
)
def test_assigned_roles_match_the_gold_label(gold_id, source_file, expected_roles):
    path = os.path.join("docs", source_file)
    pages, meta, _ = load_document(path)
    new_meta, _ = pageroles.assign(pages, meta)
    got = [m.role for m in new_meta]
    assert got == expected_roles


def test_upak_is_primary_on_every_page():
    """F10: the same template repeats, totals resolving only on the last page."""
    path = "docs/CANADIAN WITHOUT NOTES U- PAK 4378107 (1).pdf"
    pages, meta, _ = load_document(path)
    new_meta, used_last_resort = pageroles.assign(pages, meta)
    roles = [m.role for m in new_meta]
    assert roles == ["primary"] * 5
    assert used_last_resort is False


def test_complete_beverage_bol_pages_are_supporting_not_primary(caplog):
    """The invoice page is primary; the three scanned BOL pages are not, so
    field capture cannot accidentally read a value off a BOL page. This
    document's page 1 has a totals label but no machine-findable anchor
    label, so this exercises the tier-1 fallback, not the direct anchor+
    totals rule - confirmed by capturing the log warning below.
    """
    path = "docs/_AP Invoice 32930 Complete Beverage Destruction 1177.70000.pdf"
    pages, meta, _ = load_document(path)
    with caplog.at_level(logging.WARNING, logger="docintel.extract.pageroles"):
        new_meta, used_last_resort = pageroles.assign(pages, meta)
    roles = [m.role for m in new_meta]
    assert roles == ["primary", "supporting", "supporting", "supporting"]
    assert "falling back to page 1, the first page carrying a totals label" in caplog.text
    assert used_last_resort is False  # tier 1, not tier 2 - not tagged


def test_dtss_falls_back_to_the_page_with_a_totals_label(caplog):
    """DTSS's only page has 'Balance Due' but no machine-findable anchor
    label, so this is the other tier-1 fallback case in the corpus."""
    path = "docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf"
    pages, meta, _ = load_document(path)
    with caplog.at_level(logging.WARNING, logger="docintel.extract.pageroles"):
        new_meta, used_last_resort = pageroles.assign(pages, meta)
    roles = [m.role for m in new_meta]
    assert roles == ["primary"]
    assert "falling back to page 1, the first page carrying a totals label" in caplog.text
    assert used_last_resort is False  # tier 1, not tier 2 - not tagged


def test_edco_falls_back_to_page_1_as_a_last_resort(caplog):
    """EDCO's only page has neither a machine-findable anchor label nor a
    totals-block label under the tightened, prose-resistant regexes - its
    account number and total appear only in a scan-line code and a bare
    'Current Charges:' recap line, neither of which qualifies. This is the
    tier-2, last-resort fallback, and the one corpus document that must
    come back with `used_last_resort=True` - `s2_filter.py` turns this into
    the `page_role_fallback` tag on the emitted record (fix round 2)."""
    path = "docs/EDCO 77087APR25 current charges can be misleading, paying $69.62.pdf"
    pages, meta, _ = load_document(path)
    with caplog.at_level(logging.WARNING, logger="docintel.extract.pageroles"):
        new_meta, used_last_resort = pageroles.assign(pages, meta)
    roles = [m.role for m in new_meta]
    assert roles == ["primary"]
    assert "last resort" in caplog.text
    assert used_last_resort is True


def test_assign_does_not_mutate_or_corrupt_the_memoized_meta():
    """`assign` must build a new tuple of new PageMeta instances. Confirms
    the precondition directly: calling assign and then re-loading the same
    document must still see the untouched ("unknown"-role) memoized meta -
    PageMeta is frozen and load_document's memo hands out the same tuple
    object to every caller.
    """
    path = "docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf"
    pages, meta_before, _ = load_document(path)
    assert all(m.role == "unknown" for m in meta_before)

    assigned, _ = pageroles.assign(pages, meta_before)
    assert assigned is not meta_before
    assert all(a is not m for a, m in zip(assigned, meta_before))
    assert [m.role for m in assigned] == ["primary"]

    _, meta_after, _ = load_document(path)
    assert meta_after is meta_before
    assert all(m.role == "unknown" for m in meta_after)


def test_assign_on_empty_pages_returns_meta_unchanged():
    assert pageroles.assign((), ()) == ((), False)


# ---------------------------------------------------------------------------
# Synthetic tests. These are the point of this round: a rule that only ever
# picks page 1 would pass every corpus-driven test above, because in 9 of
# the 10 real documents the primary page IS page 1. These fixtures put the
# qualifying signals on a page that is NOT page 1, and check the rule
# follows the signals rather than the position.
# ---------------------------------------------------------------------------


def test_balance_payable_and_now_due_resolve_a_page_2_case_without_cascading_to_tier_2(caplog):
    """Fix round 2: 'Balance Payable' and 'Amount Now Due' are common
    invoice phrasings the original six-phrase enumeration missed entirely -
    neither matched `_TOTALS_RE`, so a document phrased this way had no
    page satisfying the direct rule AND no totals-only page for tier 1
    either, cascading straight to tier 2 ("page 1, last resort") even
    though the real totals block was sitting right there on page 2. That
    silently reproduced the exact cover-page-1 bug the Critical finding was
    about, just relocated into the phrase list. With both phrases added,
    this must resolve directly - no fallback, no log warning, no tag.
    """
    pages = (
        _page(1, [NOISE_LINE, ["Routing", "sheet", "-", "internal", "use", "only"]]),
        _page(2, [ANCHOR_LINE, ["Balance", "Payable:", "$500.00"]]),
        _page(3, [NOISE_LINE, ["Amount", "Now", "Due:", "$500.00"]]),
    )
    meta = _meta(list(pages))
    with caplog.at_level(logging.WARNING, logger="docintel.extract.pageroles"):
        new_meta, used_last_resort = pageroles.assign(pages, meta)
    roles = [m.role for m in new_meta]
    assert roles == ["supporting", "primary", "supporting"]
    assert used_last_resort is False
    assert caplog.text == ""  # no fallback fired at all - direct rule sufficed

    # And "Amount Now Due" alone (no anchor) still recognizes NOW DUE as a
    # totals label on its own, exercising it independently of BALANCE PAYABLE.
    solo_pages = (_page(1, [["Amount", "Now", "Due:", "$500.00"]]),)
    solo_meta = _meta(list(solo_pages))
    solo_new_meta, solo_used_last_resort = pageroles.assign(solo_pages, solo_meta)
    assert [m.role for m in solo_new_meta] == ["primary"]
    assert solo_used_last_resort is False  # tier 1: totals label present, just no anchor


def test_total_invoice_amount_is_a_totals_label_so_no_last_resort_guess_is_needed(caplog):
    """Finding 3: the "Windstream Enterprise" bill template names its payable
    `TOTAL INVOICE AMOUNT`, which the enumeration missed.

    Two real documents (`Windstream_205577168_08222025_BILL.pdf`,
    `Windstream_216713099_08272025_BILL.pdf`) print exactly that, and their
    header stacks the identity label over two visual lines -

        Account    Invoice        Total
        Number     Date           Amount Due

    - so `_ANCHOR_RE` finds no contiguous "Account Number" either. With
    NEITHER signal recognized, both documents cascaded to the tier-2 last
    resort and carried `page_role_fallback` on the record: a blind guess tag
    on a page that in fact prints its total in 8pt caps.

    `TOTAL INVOICE AMOUNT` is added under the enumeration's stated policy (see
    the module docstring): an obvious, common invoice phrasing the list
    happened to miss, observed printed on real documents - not a loosening of
    the pattern into a general phrase detector. The cross-line identity label
    is deliberately NOT addressed; recognizing labels split over two lines
    would change the page-role signal for every document. Tier 1 covers this
    case correctly on its own, and tier 1 is a reasoned inference rather than
    a guess, so it carries no tag.
    """
    pages = (
        _page(1, [["Account", "Invoice", "Total"], ["TOTAL", "INVOICE", "AMOUNT", "$4.82"]]),
        _page(2, [NOISE_LINE]),
    )
    meta = _meta(list(pages))
    with caplog.at_level(logging.WARNING, logger="docintel.extract.pageroles"):
        new_meta, used_last_resort = pageroles.assign(pages, meta)
    assert [m.role for m in new_meta] == ["primary", "supporting"]
    assert used_last_resort is False, "tier 2 fired: TOTAL INVOICE AMOUNT was not recognized"
    assert "last resort" not in caplog.text


def test_page_2_is_primary_when_the_anchor_and_totals_first_appear_there():
    """A 3-page document with a cover/routing page 1 that carries neither
    signal, real content (anchor + totals) on page 2, and an unrelated
    detail page 3. If the rule ever regresses to hardcoding page 1, this
    is what catches it: page 1 must NOT be primary here.
    """
    pages = (
        _page(1, [NOISE_LINE, ["Routing", "sheet", "-", "internal", "use", "only"]]),
        _page(2, [ANCHOR_LINE, TOTALS_LINE]),
        _page(3, [NOISE_LINE]),
    )
    meta = _meta(list(pages))
    new_meta, used_last_resort = pageroles.assign(pages, meta)
    roles = [m.role for m in new_meta]
    assert roles == ["supporting", "primary", "supporting"]
    assert used_last_resort is False


def test_fallback_fires_when_no_page_carries_both_signals(caplog):
    """Two pages, neither carrying both signals: page 1 has only a totals
    label, page 2 has neither. The tier-1 fallback must pick page 1 (the
    page that actually carries the payable), and the fallback must be
    logged - not a silent special case.
    """
    pages = (
        _page(1, [TOTALS_LINE]),
        _page(2, [NOISE_LINE]),
    )
    meta = _meta(list(pages))
    with caplog.at_level(logging.WARNING, logger="docintel.extract.pageroles"):
        new_meta, used_last_resort = pageroles.assign(pages, meta)
    roles = [m.role for m in new_meta]
    assert roles == ["primary", "supporting"]
    assert "falling back" in caplog.text
    assert used_last_resort is False  # tier 1 (a totals-only page exists), not tier 2


def test_single_page_with_anchor_but_no_totals_is_still_primary(caplog):
    """A lone page with an identity anchor but no totals label satisfies
    neither the direct rule nor the tier-1 (totals-only) fallback, so this
    exercises the tier-2 last-resort fallback - and a document must still
    end up with a primary page, or field capture has nowhere to read from.
    """
    pages = (_page(1, [ANCHOR_LINE]),)
    meta = _meta(list(pages))
    with caplog.at_level(logging.WARNING, logger="docintel.extract.pageroles"):
        new_meta, used_last_resort = pageroles.assign(pages, meta)
    roles = [m.role for m in new_meta]
    assert roles == ["primary"]
    assert "last resort" in caplog.text
    assert used_last_resort is True


def test_page_with_neither_signal_in_a_multipage_document_is_supporting():
    """A page carrying real content but no anchor and no totals label is
    confidently NOT primary - `supporting`, not `unknown`. `unknown` is
    reserved for pages with no content at all (see the blank-page test
    below): a page full of ordinary text is known content, just not the
    totals page.
    """
    pages = (
        _page(1, [ANCHOR_LINE, TOTALS_LINE]),
        _page(2, [NOISE_LINE, NOISE_LINE]),
    )
    meta = _meta(list(pages))
    new_meta, used_last_resort = pageroles.assign(pages, meta)
    roles = [m.role for m in new_meta]
    assert roles == ["primary", "supporting"]
    assert used_last_resort is False


def test_blank_page_is_unknown_not_supporting():
    """A page with zero words carries no information to classify at all -
    it is reported `unknown`, distinct from a `supporting` page (which is
    confidently known to be part of the document, just not primary). No
    document in the corpus has a blank page, so this branch is otherwise
    untested.
    """
    pages = (
        _page(1, [ANCHOR_LINE, TOTALS_LINE]),
        _blank_page(2),
    )
    meta = _meta(list(pages))
    new_meta, used_last_resort = pageroles.assign(pages, meta)
    roles = [m.role for m in new_meta]
    assert roles == ["primary", "unknown"]
    assert used_last_resort is False


def test_blank_first_page_still_becomes_primary_via_last_resort_fallback(caplog):
    """Every page blank: the tier-2 fallback still marks page 1 primary
    (there is no better candidate), even though that page is also, by the
    blank-page rule, otherwise `unknown`-worthy. The explicit fallback
    takes priority over the blank-page default.
    """
    pages = (_blank_page(1), _blank_page(2))
    meta = _meta(list(pages))
    with caplog.at_level(logging.WARNING, logger="docintel.extract.pageroles"):
        new_meta, used_last_resort = pageroles.assign(pages, meta)
    roles = [m.role for m in new_meta]
    assert roles == ["primary", "unknown"]
    assert "last resort" in caplog.text
    assert used_last_resort is True


# ---------------------------------------------------------------------------
# Fix round 2: the tier-2 last-resort fallback must be visible on the
# emitted record (a `page_role_fallback` tag), not just in a log line
# nobody is watching. These exercise `s2_filter.AttachmentFilter`, which is
# what actually turns `pageroles.assign`'s second return value into
# `ctx.tags` - `assign`'s own boolean return is already covered above.
# ---------------------------------------------------------------------------


def test_page_role_fallback_tag_appears_when_no_page_carries_either_signal(tmp_path, monkeypatch):
    """Fully synthetic: no real PDF is read. `load_document` and
    `annotations.detect_flattened` are faked so this exercises exactly
    `s2_filter`'s wiring of `pageroles.assign`'s tier-2 result into a tag,
    for a single blank page that carries neither signal.
    """
    dummy = tmp_path / "dummy.pdf"
    dummy.write_bytes(b"%PDF-1.4\n%%EOF\n")  # never actually parsed

    page = _blank_page(1)
    meta = _meta([page])

    monkeypatch.setattr(s2_filter, "load_document", lambda path: ((page,), meta, "native"))
    monkeypatch.setattr(
        s2_filter.annotations, "detect_flattened", lambda path, pages, meta: False
    )

    ctx = JobContext(document_id="d1", source_path=str(dummy))
    s2_filter.AttachmentFilter().run(ctx)

    assert "page_role_fallback" in ctx.tags


def test_page_role_fallback_tag_absent_for_a_normal_synthetic_document(tmp_path, monkeypatch):
    """Same wiring, but the page carries both signals directly - no
    fallback at all - so the tag must NOT appear.
    """
    dummy = tmp_path / "dummy.pdf"
    dummy.write_bytes(b"%PDF-1.4\n%%EOF\n")

    page = _page(1, [ANCHOR_LINE, TOTALS_LINE])
    meta = _meta([page])

    monkeypatch.setattr(s2_filter, "load_document", lambda path: ((page,), meta, "native"))
    monkeypatch.setattr(
        s2_filter.annotations, "detect_flattened", lambda path, pages, meta: False
    )

    ctx = JobContext(document_id="d1", source_path=str(dummy))
    s2_filter.AttachmentFilter().run(ctx)

    assert "page_role_fallback" not in ctx.tags


def test_edco_the_one_corpus_tier_2_document_carries_the_fallback_tag():
    """The concrete corpus proof: EDCO is the only one of the ten real
    documents that hits the tier-2 last-resort fallback (see
    `test_edco_falls_back_to_page_1_as_a_last_resort` above), so it must be
    the only one whose emitted record carries `page_role_fallback`.
    """
    path = "docs/EDCO 77087APR25 current charges can be misleading, paying $69.62.pdf"
    ctx = JobContext(document_id="d1", source_path=path)
    s2_filter.AttachmentFilter().run(ctx)
    assert "page_role_fallback" in ctx.tags


@pytest.mark.parametrize(
    "path",
    [
        "docs/_AP Invoice 715-33905296    Veritiv Operating Company 4908.00000.pdf",
        "docs/_AP Invoice 32930 Complete Beverage Destruction 1177.70000.pdf",  # tier 1
        "docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf",  # tier 1
        "docs/CANADIAN WITHOUT NOTES U- PAK 4378107 (1).pdf",
    ],
)
def test_other_corpus_documents_do_not_carry_the_fallback_tag(path):
    """Direct-rule and tier-1 documents must NOT carry `page_role_fallback`
    - only EDCO's tier-2 last resort does. Includes both of the tier-1
    documents explicitly, since tier 1 is a targeted inference and must
    stay untagged even though it IS a fallback of sorts.
    """
    ctx = JobContext(document_id="d1", source_path=path)
    s2_filter.AttachmentFilter().run(ctx)
    assert "page_role_fallback" not in ctx.tags


# ---------------------------------------------------------------------------
# Fix round 3: a per-section usage subtotal row ("GRAND TOTAL 113 72.6
# $2.6400") must not be mistaken for the document's own totals block just
# because it also shares a page with a routine running-header anchor. See
# Windstream_2389882_08272025_BILL.pdf (real 472-page second-sample).
# ---------------------------------------------------------------------------


def test_totals_only_page_1_wins_over_a_usage_detail_page_with_a_coincidental_grand_total() -> None:
    """Reproduces the real Windstream_2389882 bug: page 1 has a totals-only
    line (split-anchor template, tier-1 candidate) but a later page has BOTH
    an anchor (routine running-header) and a `GRAND TOTAL` match that is
    really a per-section usage subtotal row (extra bare numeric tokens beside
    the money value, not a label/value pair). Before the fix, the later
    page's coincidental both-signal match makes `primary_idx` non-empty and
    tier-1 never runs, so page 1 loses primary status."""
    page1 = _page(1, [["TOTAL", "INVOICE", "AMOUNT", "$116,258.78"]])
    page2 = _page(2, [
        ["INVOICE", "NUMBER", "77178223"],
        ["GRAND", "TOTAL", "113", "72.6", "$2.6400"],
    ])
    meta, used_last_resort = pageroles.assign((page1, page2), _meta([page1, page2]))
    assert meta[0].role == "primary"
    assert used_last_resort is False


def test_grand_total_with_exactly_one_money_token_still_qualifies_as_primary() -> None:
    """Guard against over-correcting: a genuine `GRAND TOTAL $500.00` label/value
    line, alone with its own anchor, must still qualify a page as primary on
    its own (no fallback needed) — this is the ordinary case the regex exists
    to catch."""
    page = _page(1, [ANCHOR_LINE, ["GRAND", "TOTAL", "$500.00"]])
    meta, used_last_resort = pageroles.assign((page,), _meta([page]))
    assert meta[0].role == "primary"
    assert used_last_resort is False


# ---------------------------------------------------------------------------
# Fix round 4: real EDCO bug (823283AUG25/823283SEP25). EDCO's totals-box
# labels render as non-text graphics, so a genuinely two-page continued
# invoice has NO page carrying either signal at all — true tier-2. But both
# pages share a matching `N OF M` pagination footer, real proof this is one
# continuous invoice rather than an invoice-plus-attachment, so tier-2 should
# trust that proof over a blind page-1-only guess.
# ---------------------------------------------------------------------------


def test_tier_2_fallback_marks_every_page_of_a_proven_continuation_sequence_primary() -> None:
    """Reproduces the real EDCO 823283 bug: neither page carries any anchor
    or totals signal at all (true tier-2), but both pages share a matching
    `N OF 2` footer — real proof this is one continuous invoice, not a
    page-1-only guess. `CURRENT CHARGES:` (page 2 only) must become readable
    by primary-scoped selectors."""
    page1 = _page(1, [["BALANCE", "FORWARD", "3593.91"], ["MD9-M", "1", "OF", "2"]])
    page2 = _page(2, [["CURRENT", "CHARGES:", "3267.54"], ["MD9-M", "2", "OF", "2"]])
    meta, used_last_resort = pageroles.assign((page1, page2), _meta([page1, page2]))
    assert meta[0].role == "primary"
    assert meta[1].role == "primary"
    assert used_last_resort is True  # still a guess, still tagged — just a better-informed one


def test_tier_2_fallback_still_picks_page_1_alone_without_a_footer_sequence() -> None:
    """No regression: when there is no proven continuation sequence, tier-2
    behaves exactly as before — page 1 only."""
    page1 = _page(1, [["BALANCE", "FORWARD", "3593.91"]])
    page2 = _page(2, [["CURRENT", "CHARGES:", "3267.54"]])
    meta, used_last_resort = pageroles.assign((page1, page2), _meta([page1, page2]))
    assert meta[0].role == "primary"
    assert meta[1].role == "supporting"
    assert used_last_resort is True


def test_total_credit_line_qualifies_as_a_totals_signal() -> None:
    """Real Complete Beverage bug: a batched credit-memo page prints 'TOTAL
    CREDIT $2,899.00' rather than any of the other enumerated totals
    phrases. Without recognizing it, the page with the real credit-memo
    header never gets primary status and the whole document goes unclaimed."""
    page1 = _page(1, [["Credit", "Memo"], ["TOTAL", "CREDIT", "$2,899.00"]])
    page2 = _page(2, [["GRAND", "TOTAL"]])  # certificate/BOL page, no real anchor either
    meta, _ = pageroles.assign((page1, page2), _meta([page1, page2]))
    assert meta[0].role == "primary"
