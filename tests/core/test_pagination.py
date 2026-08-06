"""`shared_footer_pages`: a page-number set only when every page of the
document carries a matching, self-consistent `N OF M` footer — real evidence
that the pages are one continuous document, not a guess."""

from __future__ import annotations

from docintel.core.models import PageText, Word
from docintel.core.pagination import shared_footer_pages


def _page(number: int, footer: str | None) -> PageText:
    words: list[Word] = []
    if footer:
        for i, tok in enumerate(footer.split()):
            words.append(Word(text=tok, x0=10.0 + 40.0 * i, y0=700.0,
                               x1=45.0 + 40.0 * i, y1=710.0))
    return PageText(page_number=number, words=tuple(words), width=612.0, height=792.0, source="native")


def test_two_pages_with_matching_1_of_2_and_2_of_2_footers() -> None:
    pages = (_page(1, "000000-001 MD9-M 1 OF 2"), _page(2, "000000-001 MD9-M 2 OF 2"))
    assert shared_footer_pages(pages) == frozenset({1, 2})


def test_single_page_document_has_no_footer_sequence() -> None:
    assert shared_footer_pages((_page(1, "1 OF 1"),)) is None


def test_missing_footer_on_one_page_yields_none() -> None:
    pages = (_page(1, "1 OF 2"), _page(2, None))
    assert shared_footer_pages(pages) is None


def test_footer_total_not_matching_page_count_yields_none() -> None:
    """A stapled attachment prints its own, unrelated pagination — must not
    be mistaken for the invoice's own continuation sequence."""
    pages = (_page(1, "1 OF 3"), _page(2, "2 OF 3"))
    assert shared_footer_pages(pages) is None
