"""`ocr.ocr_image`: OCR directly off a raster image, no PDF wrapper involved.

Correctness fixtures follow `test_normalize.py`'s `_scanned_page_jpeg`
convention: a large, legible font on a plain background, since the goal here
is proving the code path and coordinate space, not stress-testing tesseract.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from docintel.extract import ocr

_IMG_W, _IMG_H = 850, 300


def _text_image(path, lines: list[str]) -> None:
    img = Image.new("RGB", (_IMG_W, _IMG_H), color="white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=32)
    for i, line in enumerate(lines):
        draw.text((20, 20 + i * 60), line, font=font, fill="black")
    img.save(path)


def test_ocr_image_reads_legible_text_from_a_single_frame(tmp_path):
    path = tmp_path / "invoice-snippet.png"
    _text_image(path, ["INVOICE NUMBER INV99201", "TOTAL DUE 450.00"])

    pages = ocr.ocr_image(str(path))

    assert len(pages) == 1
    page = pages[0]
    assert page.source == "ocr"
    assert page.page_number == 1
    text = page.text.upper()
    assert "INVOICE" in text
    assert "99201" in text
    assert "450.00" in text


def test_ocr_image_words_stay_in_the_images_native_pixel_space(tmp_path):
    """No `72/RESOLUTION` scaling applies here (unlike `_run_ocr`'s PDF-page
    path) - every word box must fall within the source image's own pixel
    dimensions, confirming the `scale=1.0` path, not some other factor."""
    path = tmp_path / "bounds.png"
    _text_image(path, ["BOUNDS CHECK"])

    pages = ocr.ocr_image(str(path))

    page = pages[0]
    assert page.width == _IMG_W
    assert page.height == _IMG_H
    assert page.words, "expected at least one recognized word"
    for word in page.words:
        assert 0 <= word.x0 <= word.x1 <= _IMG_W + 1
        assert 0 <= word.y0 <= word.y1 <= _IMG_H + 1


def test_ocr_image_reads_every_frame_of_a_multi_frame_tiff_in_order(tmp_path):
    path = tmp_path / "multi.tiff"
    frame_a = Image.new("RGB", (_IMG_W, _IMG_H), "white")
    ImageDraw.Draw(frame_a).text((20, 20), "FRAME ONE MARKER", font=ImageFont.load_default(size=32), fill="black")
    frame_b = Image.new("RGB", (_IMG_W, _IMG_H), "white")
    ImageDraw.Draw(frame_b).text((20, 20), "FRAME TWO MARKER", font=ImageFont.load_default(size=32), fill="black")
    frame_a.save(path, save_all=True, append_images=[frame_b])

    pages = ocr.ocr_image(str(path))

    assert [p.page_number for p in pages] == [1, 2]
    assert "FRAME" in pages[0].text.upper() and "ONE" in pages[0].text.upper()
    assert "FRAME" in pages[1].text.upper() and "TWO" in pages[1].text.upper()


def test_ocr_image_is_cached_on_repeat_calls(tmp_path, monkeypatch):
    path = tmp_path / "cache-me.png"
    _text_image(path, ["CACHE ME"])

    calls = []
    real = ocr.pytesseract.image_to_data

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(ocr.pytesseract, "image_to_data", spy)

    first = ocr.ocr_image(str(path))
    second = ocr.ocr_image(str(path))

    assert first == second
    assert len(calls) == 1, "a cache hit must not re-run tesseract"


def test_ocr_image_cache_is_disabled_by_the_shared_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCINTEL_OCR_CACHE", "0")
    path = tmp_path / "no-cache.png"
    _text_image(path, ["NO CACHE HERE"])

    calls = []
    real = ocr.pytesseract.image_to_data

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(ocr.pytesseract, "image_to_data", spy)

    ocr.ocr_image(str(path))
    ocr.ocr_image(str(path))

    assert len(calls) == 2, "DOCINTEL_OCR_CACHE=0 must bypass the cache on every call"


def test_ocr_image_and_ocr_pages_cache_keys_never_collide(tmp_path):
    """Same bytes, same abspath/size/mtime/content-hash - but `ocr_image`
    keys on `_NATIVE_RESOLUTION`, not `RESOLUTION`, so a PDF-rasterized OCR
    result can never be served in place of a direct-image OCR result or vice
    versa, even for the pathological case of literally the same file."""
    path = tmp_path / "shared.png"
    _text_image(path, ["SHARED BYTES"])

    image_key = ocr.ocr_cache.cache_key(str(path), ocr._NATIVE_RESOLUTION, ocr.tesseract_version(), [])
    pdf_key = ocr.ocr_cache.cache_key(str(path), ocr.RESOLUTION, ocr.tesseract_version(), [1])

    assert image_key != pdf_key
