"""Decide once, per document, whether to trust the text layer or run OCR.

F2's measured rule: a document whose average characters-per-page falls below
`NATIVE_CHAR_THRESHOLD` gets zero characters back from a "successful" parse of
a perfectly clean invoice, so `char_count == 0` and `char_count` too small to
be real text both mean the same thing here — there is nothing to read.

The decision is made for the whole document, never per page (a later
confidence modifier keys off the single `text_source` value this returns),
and OCR happens exactly once here — `load_document` is the only caller of
`ocr.ocr_pages` in the pipeline.
"""

from __future__ import annotations

from docintel.core.models import PageMeta, PageText
from docintel.extract import ocr, pdf

NATIVE_CHAR_THRESHOLD = 50  # chars per page below which a document is OCR'd


def load_document(path: str) -> tuple[tuple[PageText, ...], tuple[PageMeta, ...], str]:
    """Load a PDF's pages and metadata, routing to OCR only when needed.

    Returns `(pages, meta, text_source)` where `text_source` is `"native"` or
    `"ocr"`. `meta` always comes from the text layer (page count, image and
    annotation counts are structural facts independent of which path produced
    the words); only `pages` differs between the two routes.
    """
    meta = pdf.read_meta(path)
    total_chars = sum(m.char_count for m in meta)
    avg_chars_per_page = total_chars / len(meta) if meta else 0.0

    if avg_chars_per_page < NATIVE_CHAR_THRESHOLD:
        page_numbers = [m.page_number for m in meta]
        pages = ocr.ocr_pages(path, page_numbers)
        return pages, meta, "ocr"

    pages = pdf.read_pages(path)
    return pages, meta, "native"
