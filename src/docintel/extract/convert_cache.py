"""Persistent disk cache for DOCX/XLSX/TIFF-BMP-GIF-to-PDF conversion results.

Mirrors `ocr_cache.py`'s design exactly - see that module's own docstring for
the full rationale this one inherits without repeating: why the content
hash, not just path/size/mtime, is what makes the key correct; why entries
are written atomically; why `DOCINTEL_OCR_CACHE`, not a second env var, is
the right disable knob (a debugging escape hatch that only clears one of
several cache layers is worse than none - someone would trust it and be
wrong). The one structural difference: an OCR result is data (a tuple of
`PageText`), serialized as JSON; a conversion result IS a PDF file, so this
cache stores a path to a copy of that file rather than parsed content.

Without this cache, retrying a dead-lettered document, or reprocessing a
batch (`docintel replay-gold` run twice, a retried webhook), re-invokes
LibreOffice/Pillow from scratch every time on every DOCX/XLSX/TIFF/BMP/GIF -
`ocr_cache.py`'s own motivation (repeat processing of the same file should be
free) applies just as much to the conversion step as it does to OCR.

The disable knob stays shared (`DOCINTEL_OCR_CACHE`, per above), but the
LOCATION knob is this cache's own - `DOCINTEL_CONVERT_CACHE_DIR`, mirroring
`DOCINTEL_OCR_CACHE_DIR`, falling back to `paths.state_root()`. Pointing two
different caches at one directory would be a genuine footgun (a `.json` OCR
entry and a `.pdf` conversion entry sharing an eviction sweep), which is the
opposite of the disable knob's reasoning for being shared.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from docintel.extract.ocr_cache import ENV_DISABLE, content_hash
from docintel.paths import state_root

ENV_CACHE_DIR = "DOCINTEL_CONVERT_CACHE_DIR"
MAX_ENTRIES = 512  # same eviction cap as ocr_cache.py, same rationale


def _cache_dir() -> Path:
    """Where cached PDFs live: `DOCINTEL_CONVERT_CACHE_DIR` if set, else
    `state_root() / "convert-cache"`.

    Previously a module-level `CACHE_DIR = Path("var") / "convert-cache"`
    constant with no override at all - the same gap `ocr_cache` had, closed
    the same way (see `ocr_cache._cache_dir`): resolved per call rather than
    once at import, so `DOCINTEL_STATE_DIR` set after import still takes
    effect, and state stops depending on whichever CWD the process happened
    to start in.
    """
    override = os.environ.get(ENV_CACHE_DIR)
    return Path(override) if override else state_root() / "convert-cache"


def enabled() -> bool:
    """Same env var, same default-on, as `ocr_cache.enabled()`."""
    return os.environ.get(ENV_DISABLE, "1") != "0"


def cache_key(source_path: str, converter_name: str) -> str:
    """Hash the inputs that make a cached conversion valid to reuse.

    `converter_name` ("image" or "office") keeps the two converters' cache
    entries from ever colliding - cheap to rule out structurally even though
    `abspath` alone already would in practice, the same "belt and braces
    costs nothing, is checked once" reasoning `ocr_cache.cache_key` applies
    to `page_numbers`.
    """
    abs_path = os.path.abspath(source_path)
    stat = os.stat(abs_path)
    digest = content_hash(abs_path)
    payload = "|".join([abs_path, str(stat.st_size), str(stat.st_mtime_ns), digest, converter_name])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_path(key: str) -> Path:
    return _cache_dir() / f"{key}.pdf"


def load(key: str) -> str | None:
    """Return the path to a cached PDF for `key`, or None on miss/corruption.

    An optimization, never a new failure mode: a missing, empty, or
    unreadable cache entry falls through to None so the caller re-converts
    instead of handing back a truncated file.
    """
    if not enabled():
        return None
    cache_path = _cache_path(key)
    try:
        if cache_path.stat().st_size == 0:
            return None
        with open(cache_path, "rb"):
            pass
    except OSError:
        return None
    return str(cache_path)


def save(key: str, pdf_path: str) -> str:
    """Copy `pdf_path` into the cache under `key` and return the cache path.

    Best-effort and atomic (temp file + rename), matching `ocr_cache.save`.
    On any failure to write, returns `pdf_path` unchanged - a cache write
    failure must never take away the real, already-produced conversion
    result the caller is holding.
    """
    if not enabled():
        return pdf_path
    try:
        _cache_dir().mkdir(parents=True, exist_ok=True)
        cache_path = _cache_path(key)
        tmp_path = cache_path.with_suffix(f".{os.getpid()}.tmp")
        shutil.copyfile(pdf_path, tmp_path)
        os.replace(tmp_path, cache_path)
    except OSError:
        return pdf_path
    _evict_oldest_past_cap()
    return str(cache_path)


def _evict_oldest_past_cap() -> None:
    try:
        entries = sorted(_cache_dir().glob("*.pdf"), key=lambda p: p.stat().st_mtime)
        excess = len(entries) - MAX_ENTRIES
        for stale in entries[:excess]:
            try:
                stale.unlink()
            except OSError:
                pass
    except OSError:
        pass
