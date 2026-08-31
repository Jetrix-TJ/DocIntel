"""Fix round 1: OCR must be cheap to repeat without changing its answer.

The convergence loop runs pytest / replay-gold / validate_gold after every
iteration, and uncached OCR (roughly 1-2s/page) made that unaffordable. This
proves the cache is transparent: whatever `ocr_pages` returns must be
byte-identical whether tesseract actually ran or the answer came off disk.

Fix round 2, finding 4: `test_repeated_calls_return_the_same_pages` (removed
below) had no hit/miss instrumentation, so it would have passed even if the
disk cache never served a hit at all — real OCR is deterministic, so two
fresh runs agree regardless of caching. `test_second_call_is_served_from_the_
disk_cache_not_a_recompute` replaces it: it monkeypatches
`pytesseract.image_to_data` to blow up after the first (real) call, so the
second `ocr_pages` call can only succeed if it is actually served from disk
rather than recomputed.
"""

from __future__ import annotations

import shutil

from docintel.extract import ocr, ocr_cache

DOC = "docs/CONTRA ONLY Everything already on AR Federal Recycling 1330123.pdf"


def test_cached_result_matches_what_ocr_pages_returned():
    fresh = ocr.ocr_pages(DOC, [1])  # real OCR run, or an existing warm cache

    key = ocr_cache.cache_key(DOC, ocr.RESOLUTION, ocr.tesseract_version(), [1])
    cached = ocr_cache.load(key)

    assert cached is not None
    assert cached == fresh
    assert type(cached[0]) is type(fresh[0])


def test_second_call_is_served_from_the_disk_cache_not_a_recompute(tmp_path, monkeypatch):
    copy_path = tmp_path / "federal.pdf"
    shutil.copyfile(DOC, copy_path)

    first = ocr.ocr_pages(str(copy_path), [1])  # real OCR run; populates the cache

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("tesseract ran again; the disk cache should have served this")

    monkeypatch.setattr(ocr.pytesseract, "image_to_data", _boom)

    second = ocr.ocr_pages(str(copy_path), [1])  # must come from disk, not tesseract
    assert second == first


def test_cache_key_changes_when_the_schema_version_changes(monkeypatch):
    """A change to `ocr.py`'s extraction/scaling logic (or to this module's
    own JSON entry shape) can make an existing cache entry's CONTENT wrong to
    reuse even though the underlying file/resolution/tesseract-version never
    changed - exactly what happened when `ocr.ocr_image`'s pixel-to-point
    scale changed and every warm cache entry kept serving pre-fix
    coordinates. `CACHE_SCHEMA_VERSION` must be folded into the key so a
    version bump makes every prior key unreachable."""
    key_before = ocr_cache.cache_key(DOC, ocr.RESOLUTION, ocr.tesseract_version(), [1])

    monkeypatch.setattr(ocr_cache, "CACHE_SCHEMA_VERSION", ocr_cache.CACHE_SCHEMA_VERSION + 1)
    key_after = ocr_cache.cache_key(DOC, ocr.RESOLUTION, ocr.tesseract_version(), [1])

    assert key_before != key_after


def test_an_entry_written_under_an_old_schema_version_is_not_served_after_a_bump(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_cache, "CACHE_DIR", tmp_path)
    copy_path = tmp_path / "federal.pdf"
    shutil.copyfile(DOC, copy_path)

    old_key = ocr_cache.cache_key(str(copy_path), ocr.RESOLUTION, ocr.tesseract_version(), [1])
    ocr_cache.save(old_key, ocr._run_ocr(str(copy_path), [1]))
    assert ocr_cache.load(old_key) is not None, "sanity check: the old entry itself must be readable"

    monkeypatch.setattr(ocr_cache, "CACHE_SCHEMA_VERSION", ocr_cache.CACHE_SCHEMA_VERSION + 1)
    new_key = ocr_cache.cache_key(str(copy_path), ocr.RESOLUTION, ocr.tesseract_version(), [1])

    assert ocr_cache.load(new_key) is None, "a post-bump key must never resolve to a pre-bump entry"
