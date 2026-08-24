"""`convert_cache`/`convert.convert_to_pdf_cached`: repeat conversion of the
same file must not re-invoke LibreOffice/Pillow, mirroring `ocr_cache.py`'s
own "second call served from disk, not a recompute" proof (see
`test_ocr_cache.py`).
"""

from __future__ import annotations

import shutil

from PIL import Image

from docintel.extract import convert, convert_cache


def _image(path, size=(120, 90)) -> None:
    Image.new("RGB", size, "white").save(path)


# -- convert_cache primitives -------------------------------------------------


def test_cache_key_differs_by_converter_name(tmp_path):
    path = tmp_path / "same-bytes.png"
    _image(path)
    image_key = convert_cache.cache_key(str(path), "image")
    office_key = convert_cache.cache_key(str(path), "office")
    assert image_key != office_key


def test_cache_key_differs_when_content_changes_even_at_the_same_path(tmp_path):
    path = tmp_path / "changing.png"
    _image(path, size=(120, 90))
    key_a = convert_cache.cache_key(str(path), "image")
    _image(path, size=(200, 200))
    key_b = convert_cache.cache_key(str(path), "image")
    assert key_a != key_b


def test_load_returns_none_on_a_cold_key():
    assert convert_cache.load("no-such-key-was-ever-saved") is None


def test_save_then_load_round_trips_the_file(tmp_path):
    path = tmp_path / "source.pdf"
    Image.new("RGB", (100, 100)).save(path, "PDF")
    key = convert_cache.cache_key(str(path), "office")

    cached_path = convert_cache.save(key, str(path))
    loaded = convert_cache.load(key)

    assert loaded == cached_path
    with open(path, "rb") as fh:
        original_bytes = fh.read()
    with open(loaded, "rb") as fh:
        cached_bytes = fh.read()
    assert cached_bytes == original_bytes


def test_a_corrupted_cache_entry_falls_through_to_none(tmp_path, monkeypatch):
    monkeypatch.setattr(convert_cache, "CACHE_DIR", tmp_path / "convert-cache")
    path = tmp_path / "source.pdf"
    Image.new("RGB", (100, 100)).save(path, "PDF")
    key = convert_cache.cache_key(str(path), "office")
    convert_cache.save(key, str(path))

    # Truncate the cache entry to simulate a crash mid-write that somehow
    # left a zero-byte file behind (the atomic temp+rename should prevent
    # this in practice, but `load` must still refuse to serve garbage).
    cache_path = convert_cache._cache_path(key)  # noqa: SLF001
    cache_path.write_bytes(b"")

    assert convert_cache.load(key) is None


def test_disabling_the_shared_env_var_bypasses_the_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCINTEL_OCR_CACHE", "0")
    path = tmp_path / "source.pdf"
    Image.new("RGB", (100, 100)).save(path, "PDF")
    key = convert_cache.cache_key(str(path), "office")

    result = convert_cache.save(key, str(path))
    assert result == str(path), "save must be a no-op when the cache is disabled"
    assert convert_cache.load(key) is None


# -- convert.convert_to_pdf_cached --------------------------------------------


def test_a_cache_miss_converts_and_a_cache_hit_does_not(tmp_path, monkeypatch):
    monkeypatch.setattr(convert_cache, "CACHE_DIR", tmp_path / "convert-cache")

    png = tmp_path / "invoice.png"
    _image(png)

    calls = []
    real_convert_image = convert.convert_image_to_pdf

    def spy(*args, **kwargs):
        calls.append(args)
        return real_convert_image(*args, **kwargs)

    monkeypatch.setattr(convert, "convert_image_to_pdf", spy)

    first_path, first_temp_dir = convert.convert_to_pdf_cached(str(png), ".png")
    second_path, second_temp_dir = convert.convert_to_pdf_cached(str(png), ".png")

    assert len(calls) == 1, "a cache hit must not re-invoke the real converter"
    assert first_path == second_path
    assert first_temp_dir is not None, "a genuine miss must report a temp dir to clean up"
    assert second_temp_dir is None, "a cache hit must report no new temp dir at all"


def test_a_cache_hits_path_is_never_a_temp_dir_the_caller_should_clean_up(tmp_path, monkeypatch):
    """The hard constraint: a cache-hit path lives under `convert_cache.
    CACHE_DIR`, which the `Runner` never learns about via `ctx.temp_dirs` -
    if a caller mistakenly cleaned up the cache-hit path's directory, every
    cached conversion would be deleted after its first reuse."""
    cache_dir = tmp_path / "convert-cache"
    monkeypatch.setattr(convert_cache, "CACHE_DIR", cache_dir)

    docx_source = tmp_path / "invoice.docx"
    docx_source.write_bytes(b"not a real docx - the converter is faked below")
    rendered = tmp_path / "rendered.pdf"
    Image.new("RGB", (100, 100)).save(rendered, "PDF")
    monkeypatch.setattr(convert, "convert_office_to_pdf", lambda path: str(rendered))

    convert.convert_to_pdf_cached(str(docx_source), ".docx")  # populate the cache
    hit_path, temp_dir = convert.convert_to_pdf_cached(str(docx_source), ".docx")

    assert temp_dir is None
    assert str(cache_dir) in hit_path, "the hit must be served from the cache directory"


def test_the_office_converter_wiring_test_still_only_converts_once(tmp_path, monkeypatch):
    """Guards against a regression where `s2_filter.py` stops routing through
    `convert_to_pdf_cached` at all - if it called `convert_office_to_pdf`
    directly again, this would still pass, so this is a narrower unit check
    that the cache layer specifically sits in front of the real converter."""
    monkeypatch.setattr(convert_cache, "CACHE_DIR", tmp_path / "convert-cache")
    docx = tmp_path / "invoice.docx"
    docx.write_bytes(b"not a real docx")

    calls = []

    def fake_convert(path):
        calls.append(path)
        out = tmp_path / "converted-once.pdf"
        Image.new("RGB", (100, 100)).save(out, "PDF")
        return str(out)

    monkeypatch.setattr(convert, "convert_office_to_pdf", fake_convert)

    convert.convert_to_pdf_cached(str(docx), ".docx")
    convert.convert_to_pdf_cached(str(docx), ".docx")

    assert calls == [str(docx)]
