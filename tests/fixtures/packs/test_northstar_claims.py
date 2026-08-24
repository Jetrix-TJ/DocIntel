"""4 of 28 real second-sample Edco invoices print a typo'd bill-to company
name (`NORTHSTART RECYCLING`, `NORTHSTAR RECY`, `NORTHSTRAY RECYCLING`) that
misses every literal in BILL_TO_MARKERS, so NorthstarPack.claims() returns
False and the document is silently tagged `unclaimed_document` - not an
error, just zero fields extracted. Every one of the 4 real documents still
prints its state+zip correctly (`MA 01028`), even the one where the city name
is ALSO garbled. This is the fixture for that: a page with a typo'd company
name and an intact `MA 01028`."""

from __future__ import annotations

from docintel.core.models import JobContext, PageMeta, PageText, Word
from northstar import NorthstarPack

WIDTH = 612.0
HEIGHT = 792.0


def _page_with(*lines: str) -> PageText:
    words: list[Word] = []
    y = 100.0
    for line in lines:
        x = 50.0
        for token in line.split():
            words.append(Word(text=token, x0=x, y0=y, x1=x + 6.0 * len(token), y1=y + 10.0))
            x += 6.0 * len(token) + 4.0
        y += 12.0
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def _ctx(page: PageText) -> JobContext:
    meta = (
        PageMeta(page_number=1, char_count=sum(len(w.text) for w in page.words),
                 image_count=0, annot_count=0, role="primary"),
    )
    return JobContext(document_id="d1", source_path="x.pdf", pages=(page,), page_meta=meta,
                       doc_type="standard_invoice")


def test_claims_a_typo_d_bill_to_name_via_the_intact_zip() -> None:
    page = _page_with("NORTHSTART RECYCLING", "HUNTER INDUSTRY", "PO BOX 188", "EASTE LONGMEADOWN MA 01028")
    assert NorthstarPack().claims(_ctx(page)) is True


def test_claims_a_transposed_typo_via_the_intact_zip() -> None:
    """Real 823282 documents print 'NORTHSTRAY RECYCLING' (transposed typo) and
    176024 has the address garbled ('EASTE LONGMEADOWN'); this fixture combines
    them so every existing marker fails but the new 'ma 01028' matches."""
    page = _page_with("NORTHSTRAY RECYCLING", "HUNTER INDUSTRY", "PO BOX 188", "EASTE LONGMEADOWN MA 01028")
    assert NorthstarPack().claims(_ctx(page)) is True


def test_still_rejects_an_unrelated_vendor() -> None:
    page = _page_with("ACME WIDGETS INC", "100 MAIN ST", "SPRINGFIELD IL 62701")
    assert NorthstarPack().claims(_ctx(page)) is False
