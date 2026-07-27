import glob
import json
import os

import pytest

from docintel.extract import pageroles
from docintel.extract.normalize import load_document

GOLD_DIR = os.path.join("docs", "corpus", "gold")


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


def test_complete_beverage_bol_pages_are_supporting_not_primary():
    """The invoice page is primary; the three scanned BOL pages are not, so
    field capture cannot accidentally read a value off a BOL page.
    """
    path = "docs/_AP Invoice 32930 Complete Beverage Destruction 1177.70000.pdf"
    pages, meta, _ = load_document(path)
    roles = [m.role for m in pageroles.assign(pages, meta)]
    assert roles == ["primary", "supporting", "supporting", "supporting"]


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
