"""Decide once, per document, whether to trust the text layer or run OCR.

F2's measured rule: a document whose average characters-per-page falls below
`NATIVE_CHAR_THRESHOLD` gets zero characters back from a "successful" parse of
a perfectly clean invoice, so `char_count == 0` and `char_count` too small to
be real text both mean the same thing here — there is nothing to read.

The decision is made for the whole document, never per page (a later
confidence modifier keys off the single `text_source` value this returns),
and OCR happens exactly once **per (path, size, mtime) combination** — see
the in-process memo below. `ocr.ocr_pages` also carries its own disk-backed
cache (`ocr_cache.py`) so a fresh OCR run stays rare even across separate
process invocations, e.g. `pytest` followed by `docintel replay-gold`.

Why the memo exists: `load_document` is called once per document per
pipeline *run*, but nothing stops the same document from being run through
the pipeline hundreds of times within one process — which is exactly what
`tests/test_invariant.py`'s fault-injection matrix does (48 tests, each
re-processing the same 10-document corpus). Without a memo that is 400+
re-parses of the same native 6-page PDF, dwarfing everything else in the test
suite's wall-clock time. `_load_document_cached` fixes that by keying on
`(abspath, st_size, st_mtime_ns)`: unchanged file -> instant cache hit;
edited file -> new key -> real re-parse, never a stale answer.
"""

from __future__ import annotations

import functools
import os

from docintel.core.models import PageMeta, PageText
from docintel.extract import ocr, pdf

NATIVE_CHAR_THRESHOLD = 50  # chars per page below which a document is OCR'd

_MEMO_CACHE_SIZE = 64  # bounded: a long-running process over many documents
# must not grow this without limit; 64 comfortably covers one pipeline run
# over this corpus with room to spare for repeated runs of the same files.


def load_document(path: str) -> tuple[tuple[PageText, ...], tuple[PageMeta, ...], str]:
    """Load a PDF's pages and metadata, routing to OCR only when needed.

    Returns `(pages, meta, text_source)` where `text_source` is `"native"` or
    `"ocr"`. `meta` always comes from the text layer (page count, image and
    annotation counts are structural facts independent of which path produced
    the words); only `pages` differs between the two routes.

    Memoized on `(abspath, st_size, st_mtime_ns)` so calling this twice for
    the same, unmodified file is free. If the path can't be stat'd (already
    gone, permissions, a caller passing something odd), the memo is skipped
    entirely and the real loader runs — and gets to raise whatever error is
    appropriate, rather than a cache silently swallowing it.
    """
    key = _memo_key(path)
    if key is None:
        return _load_document_uncached(path)
    return _load_document_cached(key)


def _memo_key(path: str) -> tuple[str, int, int] | None:
    try:
        abspath = os.path.abspath(path)
        stat = os.stat(abspath)
    except OSError:
        return None
    return (abspath, stat.st_size, stat.st_mtime_ns)


@functools.lru_cache(maxsize=_MEMO_CACHE_SIZE)
def _load_document_cached(
    key: tuple[str, int, int],
) -> tuple[tuple[PageText, ...], tuple[PageMeta, ...], str]:
    """The memoized body. Safe to hand the same object to many callers:

    `PageText`, `Word` and `PageMeta` are all frozen dataclasses and `pages`
    / `meta` are tuples, so the cached return value is structurally
    immutable. Nothing downstream can mutate it out from under a different
    caller — do not change that without revisiting every place this is
    handed out.
    """
    return _load_document_uncached(key[0])


def _load_document_uncached(path: str) -> tuple[tuple[PageText, ...], tuple[PageMeta, ...], str]:
    meta = pdf.read_meta(path)
    total_chars = sum(m.char_count for m in meta)
    avg_chars_per_page = total_chars / len(meta) if meta else 0.0

    if avg_chars_per_page < NATIVE_CHAR_THRESHOLD:
        page_numbers = [m.page_number for m in meta]
        pages = ocr.ocr_pages(path, page_numbers)
        return pages, meta, "ocr"

    pages = pdf.read_pages(path)
    return pages, meta, "native"
