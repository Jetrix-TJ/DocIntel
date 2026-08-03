"""Read words and structural metadata off a PDF's native text layer.

8 of the 10 corpus documents carry a usable text layer, and pdfplumber's word
boxes are already in PDF points — the same coordinate space `ocr.py` must
scale its pixel output into, so that a later selector executor cannot tell
which path produced a given `PageText` (see `core.models.PageText`).
"""

from __future__ import annotations

import re

import pdfplumber

from docintel.core.geometry import line_tolerance
from docintel.core.models import PageMeta, PageText, Word

# Unicode Private Use Area. A codepoint in this range has NO portable meaning -
# it means whatever the producing font says it means, and nothing downstream can
# know that. Comcast's bill is the corpus case: its total arrives as
# `\ue024221.11`, where U+E024 is the font's glyph for `$`. Left in place it
# defeats `parse_money` entirely and the total silently fails to extract, which
# then cascades into a refused `amount_payable` and a forced review.
#
# Stripped here, at the boundary where pdfplumber output enters the system, so
# that no pattern, op or persona has to know about font encodings. Losing the `$`
# costs nothing: the currency comes from the F14 inference ladder, not from the
# symbol.
_PRIVATE_USE = re.compile(r"[\ue000-\uf8ff\U000f0000-\U000ffffd\U00100000-\U0010fffd]")


def _clean(text: str) -> str:
    return _PRIVATE_USE.sub("", text)


def read_pages(path: str) -> tuple[PageText, ...]:
    """Extract every page's words from the text layer, in PDF points."""
    pages: list[PageText] = []
    with pdfplumber.open(path) as doc:
        for page in doc.pages:
            words = tuple(
                Word(text=cleaned, x0=w["x0"], y0=w["top"], x1=w["x1"], y1=w["bottom"])
                for w in page.extract_words()
                # A word that was ENTIRELY private-use glyphs carried no readable
                # text to begin with, so it is dropped rather than kept as "".
                if (cleaned := _clean(w["text"]))
            )
            pages.append(
                PageText(
                    page_number=page.page_number,
                    words=words,
                    width=float(page.width),
                    height=float(page.height),
                    source="native",
                    # Computed once here, at construction (B2) — never inside
                    # `lines()`, which is called 21 times across the grammar.
                    line_tolerance=line_tolerance(words),
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
