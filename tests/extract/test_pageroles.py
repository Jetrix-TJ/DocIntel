import glob
import json
import logging
import os

import pytest

from docintel.core.models import PageMeta, PageText, Word
from docintel.extract import pageroles
from docintel.extract.normalize import load_document

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
    got = [m.role for m in pageroles.assign(pages, meta)]
    assert got == expected_roles


def test_upak_is_primary_on_every_page():
    """F10: the same template repeats, totals resolving only on the last page."""
    path = "docs/CANADIAN WITHOUT NOTES U- PAK 4378107 (1).pdf"
    pages, meta, _ = load_document(path)
    roles = [m.role for m in pageroles.assign(pages, meta)]
    assert roles == ["primary"] * 5


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
        roles = [m.role for m in pageroles.assign(pages, meta)]
    assert roles == ["primary", "supporting", "supporting", "supporting"]
    assert "falling back to page 1, the first page carrying a totals label" in caplog.text


def test_dtss_falls_back_to_the_page_with_a_totals_label(caplog):
    """DTSS's only page has 'Balance Due' but no machine-findable anchor
    label, so this is the other tier-1 fallback case in the corpus."""
    path = "docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf"
    pages, meta, _ = load_document(path)
    with caplog.at_level(logging.WARNING, logger="docintel.extract.pageroles"):
        roles = [m.role for m in pageroles.assign(pages, meta)]
    assert roles == ["primary"]
    assert "falling back to page 1, the first page carrying a totals label" in caplog.text


def test_edco_falls_back_to_page_1_as_a_last_resort(caplog):
    """EDCO's only page has neither a machine-findable anchor label nor a
    totals-block label under the tightened, prose-resistant regexes - its
    account number and total appear only in a scan-line code and a bare
    'Current Charges:' recap line, neither of which qualifies. This is the
    tier-2, last-resort fallback."""
    path = "docs/EDCO 77087APR25 current charges can be misleading, paying $69.62.pdf"
    pages, meta, _ = load_document(path)
    with caplog.at_level(logging.WARNING, logger="docintel.extract.pageroles"):
        roles = [m.role for m in pageroles.assign(pages, meta)]
    assert roles == ["primary"]
    assert "last resort" in caplog.text


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

    assigned = pageroles.assign(pages, meta_before)
    assert assigned is not meta_before
    assert all(a is not m for a, m in zip(assigned, meta_before))
    assert [m.role for m in assigned] == ["primary"]

    _, meta_after, _ = load_document(path)
    assert meta_after is meta_before
    assert all(m.role == "unknown" for m in meta_after)


def test_assign_on_empty_pages_returns_meta_unchanged():
    assert pageroles.assign((), ()) == ()


# ---------------------------------------------------------------------------
# Synthetic tests. These are the point of this round: a rule that only ever
# picks page 1 would pass every corpus-driven test above, because in 9 of
# the 10 real documents the primary page IS page 1. These fixtures put the
# qualifying signals on a page that is NOT page 1, and check the rule
# follows the signals rather than the position.
# ---------------------------------------------------------------------------


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
    roles = [m.role for m in pageroles.assign(pages, meta)]
    assert roles == ["supporting", "primary", "supporting"]


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
        roles = [m.role for m in pageroles.assign(pages, meta)]
    assert roles == ["primary", "supporting"]
    assert "falling back" in caplog.text


def test_single_page_with_anchor_but_no_totals_is_still_primary(caplog):
    """A lone page with an identity anchor but no totals label satisfies
    neither the direct rule nor the tier-1 (totals-only) fallback, so this
    exercises the tier-2 last-resort fallback - and a document must still
    end up with a primary page, or field capture has nowhere to read from.
    """
    pages = (_page(1, [ANCHOR_LINE]),)
    meta = _meta(list(pages))
    with caplog.at_level(logging.WARNING, logger="docintel.extract.pageroles"):
        roles = [m.role for m in pageroles.assign(pages, meta)]
    assert roles == ["primary"]
    assert "last resort" in caplog.text


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
    roles = [m.role for m in pageroles.assign(pages, meta)]
    assert roles == ["primary", "supporting"]


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
    roles = [m.role for m in pageroles.assign(pages, meta)]
    assert roles == ["primary", "unknown"]


def test_blank_first_page_still_becomes_primary_via_last_resort_fallback(caplog):
    """Every page blank: the tier-2 fallback still marks page 1 primary
    (there is no better candidate), even though that page is also, by the
    blank-page rule, otherwise `unknown`-worthy. The explicit fallback
    takes priority over the blank-page default.
    """
    pages = (_blank_page(1), _blank_page(2))
    meta = _meta(list(pages))
    with caplog.at_level(logging.WARNING, logger="docintel.extract.pageroles"):
        roles = [m.role for m in pageroles.assign(pages, meta)]
    assert roles == ["primary", "unknown"]
    assert "last resort" in caplog.text
