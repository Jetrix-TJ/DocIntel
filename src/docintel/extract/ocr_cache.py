"""Persistent disk cache for OCR results.

OCR costs roughly 1-2s per page, and without a cache `load_document` re-runs
tesseract from scratch on every pipeline run. The convergence loop this
project is entering runs `pytest`, `replay-gold`, and `validate_gold` after
every iteration; uncached OCR turns "verify before you claim done" into a
multi-minute wait, and a verification step that expensive is one people learn
to skip. This module makes repeat OCR of the same file, at the same OCR
settings, effectively free — without changing what `ocr.ocr_pages` returns.

Correctness rests entirely on the cache key: absolute path, file size,
`st_mtime_ns`, the rasterization resolution, the tesseract binary's version
string, and the exact set of page numbers requested. Any of those changing —
edit the PDF, bump `RESOLUTION`, upgrade tesseract, ask for a different page
range — produces a new key and a fresh OCR run rather than stale or partial
words served from disk. Entries are JSON, not pickle: a cache file is
inspectable by hand and cannot execute anything on load.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from docintel.core.models import PageText, Word

CACHE_DIR = Path("var") / "ocr-cache"
ENV_DISABLE = "DOCINTEL_OCR_CACHE"


def enabled() -> bool:
    """DOCINTEL_OCR_CACHE=0 bypasses the cache entirely; default is on."""
    return os.environ.get(ENV_DISABLE, "1") != "0"


def cache_key(
    path: str,
    resolution: int,
    tesseract_version: str,
    page_numbers: list[int],
) -> str:
    """Hash the inputs that make a cached OCR result valid to reuse.

    `page_numbers` is included alongside the brief's five required
    components (path, size, mtime, resolution, tesseract version) so that a
    cache entry can never be served for a page range it does not actually
    cover — the only caller today (`normalize.load_document`) always
    requests every page, but nothing here should silently return a partial
    document if that ever changes.
    """
    abs_path = os.path.abspath(path)
    stat = os.stat(abs_path)
    payload = "|".join(
        [
            abs_path,
            str(stat.st_size),
            str(stat.st_mtime_ns),
            str(resolution),
            tesseract_version,
            ",".join(str(n) for n in sorted(page_numbers)),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def load(key: str) -> tuple[PageText, ...] | None:
    """Return the cached pages for `key`, or None on miss / any corruption.

    A cache is an optimization, never a new failure mode: any problem
    reading or parsing the entry — missing file, truncated JSON, a field
    that doesn't match the shape we wrote — falls through to None so the
    caller re-runs real OCR instead of crashing or returning partial words.
    """
    if not enabled():
        return None
    cache_path = _cache_path(key)
    try:
        with open(cache_path, encoding="utf-8") as fh:
            raw = json.load(fh)
        return tuple(
            PageText(
                page_number=p["page_number"],
                words=tuple(
                    Word(text=w[0], x0=w[1], y0=w[2], x1=w[3], y1=w[4]) for w in p["words"]
                ),
                width=p["width"],
                height=p["height"],
                source="ocr",
            )
            for p in raw
        )
    except Exception:
        return None


def save(key: str, pages: tuple[PageText, ...]) -> None:
    """Persist `pages` under `key`. Best-effort: a write failure is silent.

    Written atomically (temp file + rename) so a crash mid-write can never
    leave behind a truncated entry for `load` to trip over.
    """
    if not enabled():
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        raw = [
            {
                "page_number": p.page_number,
                "width": p.width,
                "height": p.height,
                "words": [[w.text, w.x0, w.y0, w.x1, w.y1] for w in p.words],
            }
            for p in pages
        ]
        cache_path = _cache_path(key)
        tmp_path = cache_path.with_suffix(f".{os.getpid()}.tmp")
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(raw, fh)
        os.replace(tmp_path, cache_path)
    except OSError:
        pass
