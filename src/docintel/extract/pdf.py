"""Read words and structural metadata off a PDF's native text layer.

8 of the 10 corpus documents carry a usable text layer, and pdfplumber's word
boxes are already in PDF points — the same coordinate space `ocr.py` must
scale its pixel output into, so that a later selector executor cannot tell
which path produced a given `PageText` (see `core.models.PageText`).
"""

from __future__ import annotations

import pdfplumber

from docintel.core.models import PageMeta, PageText, Word


def read_pages(path: str) -> tuple[PageText, ...]:
    """Extract every page's words from the text layer, in PDF points."""
    pages: list[PageText] = []
    with pdfplumber.open(path) as doc:
        for page in doc.pages:
            words = tuple(
                Word(text=w["text"], x0=w["x0"], y0=w["top"], x1=w["x1"], y1=w["bottom"])
                for w in page.extract_words()
            )
            pages.append(
                PageText(
                    page_number=page.page_number,
                    words=words,
                    width=float(page.width),
                    height=float(page.height),
                    source="native",
                )
            )
    return tuple(pages)


def read_meta(path: str) -> tuple[PageMeta, ...]:
    """Structural facts per page: how much text, how many images/annotations.

    `char_count` is what `normalize.load_document` thresholds on to decide
    whether a document needs OCR at all.
    """
    meta: list[PageMeta] = []
    with pdfplumber.open(path) as doc:
        for page in doc.pages:
            text = page.extract_text() or ""
            meta.append(
                PageMeta(
                    page_number=page.page_number,
                    char_count=len(text),
                    image_count=len(page.images),
                    annot_count=len(page.annots),
                )
            )
    return tuple(meta)
