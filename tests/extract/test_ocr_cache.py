"""Fix round 1: OCR must be cheap to repeat without changing its answer.

The convergence loop runs pytest / replay-gold / validate_gold after every
iteration, and uncached OCR (roughly 1-2s/page) made that unaffordable. This
proves the cache is transparent: whatever `ocr_pages` returns must be
byte-identical whether tesseract actually ran or the answer came off disk.
"""

from __future__ import annotations

from docintel.extract import ocr, ocr_cache

DOC = "docs/CONTRA ONLY Everything already on AR Federal Recycling 1330123.pdf"


def test_cached_result_matches_what_ocr_pages_returned():
    fresh = ocr.ocr_pages(DOC, [1])  # real OCR run, or an existing warm cache

    key = ocr_cache.cache_key(DOC, ocr.RESOLUTION, ocr.tesseract_version(), [1])
    cached = ocr_cache.load(key)

    assert cached is not None
    assert cached == fresh
    assert type(cached[0]) is type(fresh[0])


def test_repeated_calls_return_the_same_pages():
    first = ocr.ocr_pages(DOC, [1])
    second = ocr.ocr_pages(DOC, [1])
    assert first == second
