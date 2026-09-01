"""Persistent disk cache for OCR results.

OCR costs roughly 1-2s per page, and without a cache `load_document` re-runs
tesseract from scratch on every pipeline run. The convergence loop this
project is entering runs `pytest`, `replay-gold`, and `validate_gold` after
every iteration; uncached OCR turns "verify before you claim done" into a
multi-minute wait, and a verification step that expensive is one people learn
to skip. This module makes repeat OCR of the same file, at the same OCR
settings, effectively free — without changing what `ocr.ocr_pages` returns.

Correctness rests entirely on the cache key: absolute path, file size,
`st_mtime_ns`, a **content hash**, the rasterization resolution, the
tesseract binary's version string, and the exact set of page numbers
requested. Path/size/mtime alone are not enough — a file overwritten in
place at the same path, padded to the same byte size, with its mtime
restored (a real `rsync -t` / `cp --preserve=timestamps` / archive-extraction
outcome, not a contrived one) collides on all three and would serve a
different document's OCR result. The content hash (`blake2b`, 16-byte
digest) is what actually makes the key correct; size and mtime stay in the
key too because they're free and make a cache filename self-documenting, but
they are not load-bearing on their own. Entries are JSON, not pickle: a
cache file is inspectable by hand and cannot execute anything on load.

`DOCINTEL_OCR_CACHE=0` bypasses this cache. It is honoured by both `load`
and `save` here *and* by `normalize.load_document`'s in-process memo (see
`normalize.py`) — the env var means "give me a real, uncached answer",
and a bypass that only cleared one of two cache layers would silently do
nothing for a repeat call within one process, which is worse than no
escape hatch at all.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from docintel.core.geometry import line_tolerance
from docintel.core.models import PageText, Word
from docintel.paths import state_root

ENV_DISABLE = "DOCINTEL_OCR_CACHE"
ENV_CACHE_DIR = "DOCINTEL_OCR_CACHE_DIR"
MAX_ENTRIES = 512  # eviction cap: oldest-by-mtime entries are pruned past this

# Bumped whenever a change to `ocr.py`'s extraction/scaling logic - or to
# this module's own JSON entry shape - would make an existing cache entry's
# CONTENT wrong to reuse, even though the file/resolution/tesseract-version
# inputs to `cache_key` below haven't changed. Folded into the key itself
# (not a separate check at load time) so a version bump makes every prior
# key unreachable outright - a stale entry is never even looked up, let
# alone served. Existing files under old keys are not actively deleted; they
# just become permanently unreachable and are eventually swept up by
# `_evict_oldest_past_cap` like any other cold entry.
#
# History:
#   1 - initial cache key shape (path/size/mtime/content-hash/resolution/
#       tesseract-version/page-numbers), no schema version at all.
#   2 - `ocr.ocr_image`'s raw-image pixel-to-point scale changed from 1.0
#       (pixels treated as already-72dpi points) to `_SCALE` (72/RESOLUTION)
#       - a v1 image-OCR cache entry's word coordinates are in the WRONG
#       coordinate space for every downstream region selector.
CACHE_SCHEMA_VERSION = 2


def _cache_dir() -> Path:
    """Where cache entries live: `DOCINTEL_OCR_CACHE_DIR` if set, else
    `state_root() / "ocr-cache"`. Previously a module-level `CACHE_DIR`
    constant with no override at all - this closes that gap while still
    falling back to the same shared root the other two `var/...` writers
    (`jobs.store`, `telemetry`) fall back to.
    """
    override = os.environ.get(ENV_CACHE_DIR)
    return Path(override) if override else state_root() / "ocr-cache"


def enabled() -> bool:
    """DOCINTEL_OCR_CACHE=0 bypasses the cache entirely; default is on."""
    return os.environ.get(ENV_DISABLE, "1") != "0"


def content_hash(path: str) -> str:
    """A short, collision-resistant fingerprint of a file's actual bytes.

    Cheap in practice: hashing the whole 10-document corpus (~7MB) takes
    single-digit milliseconds, which is what makes it affordable to fold
    into every cache key rather than trusting size+mtime alone.
    """
    with open(path, "rb") as fh:
        data = fh.read()
    return hashlib.blake2b(data, digest_size=16).hexdigest()


def cache_key(
    path: str,
    resolution: int,
    tesseract_version: str,
    page_numbers: list[int],
) -> str:
    """Hash the inputs that make a cached OCR result valid to reuse.

    Includes path, size, mtime, a content hash, resolution, tesseract
    version, the requested page range, and `CACHE_SCHEMA_VERSION` — see the
    module docstring for why the content hash is the load-bearing part, why
    `page_numbers` is folded in beyond the brief's original five components
    (so a cache entry can never be served for a page range it does not
    actually cover), and `CACHE_SCHEMA_VERSION`'s own comment for why a
    logic change needs a key component none of the other six can provide.
    """
    abs_path = os.path.abspath(path)
    stat = os.stat(abs_path)
    digest = content_hash(abs_path)
    payload = "|".join(
        [
            abs_path,
            str(stat.st_size),
            str(stat.st_mtime_ns),
            digest,
            str(resolution),
            tesseract_version,
            ",".join(str(n) for n in sorted(page_numbers)),
            str(CACHE_SCHEMA_VERSION),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_path(key: str) -> Path:
    return _cache_dir() / f"{key}.json"


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
        pages = []
        for p in raw:
            words = tuple(Word(text=w[0], x0=w[1], y0=w[2], x1=w[3], y1=w[4]) for w in p["words"])
            pages.append(
                PageText(
                    page_number=p["page_number"],
                    words=words,
                    width=p["width"],
                    height=p["height"],
                    source="ocr",
                    # Not persisted in the cache entry itself (see `save`), so
                    # this recomputes it from the cached words — once, here at
                    # load, matching what a fresh `ocr.py` run over the same
                    # words would produce. Without this a cache hit would keep
                    # today's global 3.0 forever, silently diverging from a
                    # cache miss on the exact same page.
                    line_tolerance=line_tolerance(words),
                )
            )
        return tuple(pages)
    except Exception:
        return None


def save(key: str, pages: tuple[PageText, ...]) -> None:
    """Persist `pages` under `key`. Best-effort: a write failure is silent.

    Written atomically (temp file + rename) so a crash mid-write can never
    leave behind a truncated entry for `load` to trip over. After a
    successful write, prunes the cache back down to `MAX_ENTRIES` so it
    cannot grow without bound over a long-running process or many pipeline
    runs; eviction failures are swallowed the same way a write failure is —
    an optimization must never break the OCR run that triggered it.
    """
    if not enabled():
        return
    try:
        _cache_dir().mkdir(parents=True, exist_ok=True)
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
    _evict_oldest_past_cap()


def _evict_oldest_past_cap() -> None:
    try:
        entries = sorted(_cache_dir().glob("*.json"), key=lambda p: p.stat().st_mtime)
        excess = len(entries) - MAX_ENTRIES
        for stale in entries[:excess]:
            try:
                stale.unlink()
            except OSError:
                pass
    except OSError:
        pass
