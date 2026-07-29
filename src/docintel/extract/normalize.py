"""Decide per PAGE whether to trust the text layer or run OCR.

F2's measured rule: a page whose character count falls below
`NATIVE_CHAR_THRESHOLD` gets zero characters back from a "successful" parse of
a perfectly clean invoice, so `char_count == 0` and `char_count` too small to
be real text both mean the same thing here — there is nothing to read.

The routing decision is per page — a document-wide average was fitted to a
corpus that is bimodal at the document level (every document averages 0
chars/page or 500+, never mixed), so it never met a document with both native
and scanned pages, and silently left the scanned ones wordless. `text_source`
stays a two-valued *document* summary, though: any starved page makes the
whole document `"ocr"`, because a later confidence modifier and two Northstar
ladder checks key off `text_source == "ocr"` exactly (see
`_load_document_uncached` for the full reasoning). Per-page provenance still
travels on `PageText.source` and `Span.source`.

OCR happens exactly once **per (path, size, mtime, content) combination** —
see the in-process memo below. `ocr.ocr_pages` also carries its own
disk-backed cache (`ocr_cache.py`) so a fresh OCR run stays rare even across
separate process invocations, e.g. `pytest` followed by `docintel
replay-gold`.

Why the memo exists: `load_document` is called once per document per
pipeline *run*, but nothing stops the same document from being run through
the pipeline hundreds of times within one process — which is exactly what
`tests/test_invariant.py`'s fault-injection matrix does (48 tests, each
re-processing the same 10-document corpus). Without a memo that is 400+
re-parses of the same native 6-page PDF, dwarfing everything else in the test
suite's wall-clock time. `_load_document_cached` fixes that by keying on
`(abspath, st_size, st_mtime_ns, content_hash)`.

Why the content hash is in the key, not just size and mtime: a file
overwritten in place at the same path, padded to the same byte size, with
its mtime restored — `rsync -t`, `cp --preserve=timestamps`, archive
extraction that preserves original timestamps — collides on path/size/mtime
alone and would serve a stale, wrong-document result. `ocr_cache.content_hash`
(blake2b, 16-byte digest) is cheap (single-digit milliseconds even over the
whole corpus) and is what actually makes the key correct.

`DOCINTEL_OCR_CACHE=0` bypasses *this* memo as well as the disk OCR cache in
`ocr_cache.py` — same env var, both layers, on purpose. A debugging escape
hatch that only clears one of two cache layers would silently do nothing for
a repeat `load_document` call within one process, which is worse than no
escape hatch: someone would trust it and be wrong.
"""

from __future__ import annotations

import functools
import os

from docintel.core.errors import TransientError
from docintel.core.models import PageMeta, PageText
from docintel.extract import ocr, ocr_cache, pdf

NATIVE_CHAR_THRESHOLD = 50  # chars per page below which a document is OCR'd

_MEMO_CACHE_SIZE = 64  # bounded: a long-running process over many documents
# must not grow this without limit; 64 comfortably covers one pipeline run
# over this corpus with room to spare for repeated runs of the same files.

_MemoKey = tuple[str, int, int, str]


def load_document(path: str) -> tuple[tuple[PageText, ...], tuple[PageMeta, ...], str]:
    """Load a PDF's pages and metadata, routing to OCR only when needed.

    Returns `(pages, meta, text_source)` where `text_source` is `"native"` or
    `"ocr"`. `meta` always comes from the text layer (page count, image and
    annotation counts are structural facts independent of which path produced
    the words); only `pages` differs between the two routes.

    Memoized on `(abspath, st_size, st_mtime_ns, content_hash)` so calling
    this twice for the same, unmodified file is free. `DOCINTEL_OCR_CACHE=0`
    skips the memo entirely (see module docstring). If the path can't be
    stat'd or hashed (already gone, permissions, a caller passing something
    odd), the memo is also skipped and the real loader runs — and gets to
    raise whatever error is appropriate, rather than a cache silently
    swallowing it.
    """
    if not ocr_cache.enabled():
        return _load_document_uncached(path)
    key = _memo_key(path)
    if key is None:
        return _load_document_uncached(path)
    return _load_document_cached(key)


def _memo_key(path: str) -> _MemoKey | None:
    try:
        abspath = os.path.abspath(path)
        stat = os.stat(abspath)
        digest = ocr_cache.content_hash(abspath)
    except OSError:
        return None
    return (abspath, stat.st_size, stat.st_mtime_ns, digest)


@functools.lru_cache(maxsize=_MEMO_CACHE_SIZE)
def _load_document_cached(
    key: _MemoKey,
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
    # Per PAGE, not per document. The document-wide average was fitted to a
    # bimodal corpus (every document is 0 chars/page or 500+); a native invoice
    # with three scanned attachment pages averages ~586, took the native path,
    # and left those pages wordless - and a wordless page is role `unknown`, so
    # reference matching across attachments silently found nothing.
    #
    # `text_source` stays a two-valued document summary: ANY starved page makes
    # the document "ocr". Per-page provenance already travels on
    # `PageText.source` and on `Span.source`. A third value would have skipped
    # the `ocr_source` confidence penalty (s6_capture.py:73), the `ocr_only` tag
    # and `_handwritten_supporting` (ladder.py:176,196), all three of which test
    # `== "ocr"` exactly - inflating confidence on precisely the pages whose text
    # we trust least. Conservative on purpose.
    starved = [m.page_number for m in meta if m.char_count < NATIVE_CHAR_THRESHOLD]
    if not starved:
        return pdf.read_pages(path), meta, "native"
    if len(starved) == len(meta):
        return ocr.ocr_pages(path, starved), meta, "ocr"

    native = {p.page_number: p for p in pdf.read_pages(path)}
    ocred = {p.page_number: p for p in ocr.ocr_pages(path, starved)}
    # ENG REVIEW: without this, a short OCR result falls back to the WORDLESS
    # native page - silent data loss on exactly the page this change exists to
    # rescue. A raise here becomes a dead_letter with a reason, which is visible.
    missing = [n for n in starved if n not in ocred]
    if missing:
        raise TransientError(
            f"OCR returned no page for {missing} of {path!r}; "
            "refusing to fall back to a page with no text layer"
        )
    pages = tuple(ocred.get(m.page_number) or native[m.page_number] for m in meta)
    return pages, meta, "ocr"
