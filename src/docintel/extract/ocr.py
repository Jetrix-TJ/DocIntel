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

OCR is also slow (roughly 1-2s/page) and this function has no idea whether
it is being called for the first time or the tenth, so it defers to
`ocr_cache` on every call: a hit returns the exact `PageText` tuple written
by the last real OCR run for this file, resolution and tesseract version; a
miss runs tesseract and writes the result before returning it. Set
`DOCINTEL_OCR_CACHE=0` to bypass the cache and force a real run.
"""

from __future__ import annotations

from typing import Any

import pdfplumber
import pytesseract

from docintel.core.geometry import line_tolerance
from docintel.core.models import PageText, Word
from docintel.extract import ocr_cache

RESOLUTION = 200  # dpi used to rasterize each page before running tesseract
_SCALE = 72 / RESOLUTION  # points per pixel at RESOLUTION dpi

# Sentinel `resolution` for `ocr_image`'s cache key, distinct from `RESOLUTION`
# above (200, the PDF-rasterization dpi) so a raw-image OCR result can never
# collide with, or be served in place of, a PDF-page OCR result for the same
# underlying bytes.
_NATIVE_RESOLUTION = 0


def tesseract_version() -> str:
    return str(pytesseract.get_tesseract_version())


def ocr_pages(path: str, page_numbers: list[int]) -> tuple[PageText, ...]:
    """OCR just the requested (1-indexed) pages and return them as PageText.

    Transparent cache lookup first: a hit returns byte-identical results to
    the original OCR run, a miss falls through to `_run_ocr` and writes the
    result before returning.
    """
    key = ocr_cache.cache_key(path, RESOLUTION, tesseract_version(), page_numbers)
    cached = ocr_cache.load(key)
    if cached is not None:
        return cached

    pages = _run_ocr(path, page_numbers)
    ocr_cache.save(key, pages)
    return pages


def _run_ocr(path: str, page_numbers: list[int]) -> tuple[PageText, ...]:
    """Word boxes are scaled from RESOLUTION-dpi pixels back to PDF points, and
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
            words_tuple = _words_from_image(image, scale=_SCALE)
            pages.append(
                PageText(
                    page_number=page.page_number,
                    words=words_tuple,
                    width=float(page.width),
                    height=float(page.height),
                    source="ocr",
                    # Computed once here, at construction (B2) — never inside
                    # `lines()`, which is called 21 times across the grammar.
                    line_tolerance=line_tolerance(words_tuple),
                )
            )
    return tuple(pages)


def _words_from_image(image: Any, scale: float) -> tuple[Word, ...]:
    """Run tesseract over one already-rasterized image and return its words,
    scaling pixel boxes by `scale` (points per pixel) as they become `Word`s.

    Shared by `_run_ocr` (PDF pages rasterized at `RESOLUTION` dpi, `scale=
    _SCALE`) and `_run_ocr_image` (a raw image at its own native pixels,
    `scale=1.0`) so the row-parsing/filtering logic — dropping blank text and
    tesseract's -1 "no confidence" sentinel — exists exactly once.
    """
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
        left = data["left"][i] * scale
        top = data["top"][i] * scale
        width = data["width"][i] * scale
        height = data["height"][i] * scale
        words.append(Word(text=text, x0=left, y0=top, x1=left + width, y1=top + height))
    return tuple(words)


def ocr_image(path: str) -> tuple[PageText, ...]:
    """OCR a raster image directly — every frame, in order — with no PDF
    wrapper ever created.

    Word boxes come out in the image's own native pixel space (`scale=1.0`).
    That is the same coordinate space `convert.convert_image_to_pdf` would
    have declared for a wrapper PDF of this same image: Pillow's PDF writer
    maps 1 pixel to 1 point when no `resolution=` kwarg is given (verified
    empirically — a Pillow-saved PDF page's declared width/height in points
    equals the source image's pixel dimensions exactly), so this produces
    `PageText` in the identical coordinate space `_run_ocr` would have, for
    the document a caller would have gotten via convert-then-OCR, just
    without materializing the intermediate PDF or pdfplumber's own 200dpi
    re-rasterization of it.

    Not byte-identical to that old path's OCR *text*, though: today's route
    incidentally upsamples every wrapped image by `RESOLUTION/72` (~2.78x)
    before tesseract ever sees it, since `pdfplumber.to_image(resolution=
    RESOLUTION)` rasterizes off the PDF's declared (1px=1pt) page size
    regardless of the source's real resolution. Measured against a low-
    resolution synthetic sample, running tesseract directly against native
    pixels was not worse than the incidental-upsample path (one word came out
    MORE accurate: "Invoice Number:" vs. the upsampled path's "Invoice
    Number,") — but "not worse in one sample" is not "identical", so this is
    stated as a real, deliberate behavior change, not silently assumed away.

    Same transparent-cache-then-real-OCR contract as `ocr_pages`, keyed with
    `_NATIVE_RESOLUTION` (not `RESOLUTION`) so an image OCR'd this way can
    never collide with, or be served in place of, a PDF-page OCR result for
    the same underlying bytes.
    """
    key = ocr_cache.cache_key(path, _NATIVE_RESOLUTION, tesseract_version(), [])
    cached = ocr_cache.load(key)
    if cached is not None:
        return cached

    pages = _run_ocr_image(path)
    ocr_cache.save(key, pages)
    return pages


def _run_ocr_image(path: str) -> tuple[PageText, ...]:
    from PIL import Image, ImageSequence

    pages: list[PageText] = []
    with Image.open(path) as img:
        for index, frame in enumerate(ImageSequence.Iterator(img)):
            # PDF/most image-analysis paths in this codebase standardize on
            # RGB (see `convert.convert_image_to_pdf`'s identical conversion);
            # tesseract itself accepts any Pillow mode, but keeping this
            # consistent avoids a P/RGBA frame behaving differently here than
            # it would have after being wrapped into a PDF.
            rgb_frame = frame.convert("RGB") if frame.mode not in ("RGB", "L") else frame
            words_tuple = _words_from_image(rgb_frame, scale=1.0)
            pages.append(
                PageText(
                    page_number=index + 1,
                    words=words_tuple,
                    width=float(frame.width),
                    height=float(frame.height),
                    source="ocr",
                    line_tolerance=line_tolerance(words_tuple),
                )
            )
    return tuple(pages)
