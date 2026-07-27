"""Read words off a rendered page image when there is no text layer to read.

20% of the corpus (`docs/corpus-analysis.md` F2) has zero characters in the
PDF text layer despite rendering as crisp, digitally-typeset invoices — the
need for OCR cannot be seen, only measured (see `normalize.py`).

The one rule that makes this module safe to depend on: `pytesseract` reports
word boxes in pixels at whatever resolution the page was rendered, but
`PageText` promises PDF points on every path (F2's whole point). Every box
here is scaled by `72 / RESOLUTION` before it becomes a `Word`, so a
downstream selector executor sees the identical coordinate space regardless
of source.
"""

from __future__ import annotations

import pdfplumber
import pytesseract

from docintel.core.models import PageText, Word

RESOLUTION = 200  # dpi used to rasterize each page before running tesseract
_SCALE = 72 / RESOLUTION  # points per pixel at RESOLUTION dpi


def ocr_pages(path: str, page_numbers: list[int]) -> tuple[PageText, ...]:
    """OCR just the requested (1-indexed) pages and return them as PageText.

    Word boxes are scaled from RESOLUTION-dpi pixels back to PDF points, and
    rows with blank text or tesseract's -1 "no confidence" sentinel are
    dropped rather than turned into zero-width noise words.
    """
    wanted = set(page_numbers)
    pages: list[PageText] = []
    with pdfplumber.open(path) as doc:
        for page in doc.pages:
            if page.page_number not in wanted:
                continue
            image = page.to_image(resolution=RESOLUTION).original
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)

            words: list[Word] = []
            for i, text in enumerate(data["text"]):
                if not text or not text.strip():
                    continue
                try:
                    conf = float(data["conf"][i])
                except (TypeError, ValueError):
                    continue
                if conf == -1:
                    continue
                left = data["left"][i] * _SCALE
                top = data["top"][i] * _SCALE
                width = data["width"][i] * _SCALE
                height = data["height"][i] * _SCALE
                words.append(Word(text=text, x0=left, y0=top, x1=left + width, y1=top + height))

            pages.append(
                PageText(
                    page_number=page.page_number,
                    words=tuple(words),
                    width=float(page.width),
                    height=float(page.height),
                    source="ocr",
                )
            )
    return tuple(pages)
