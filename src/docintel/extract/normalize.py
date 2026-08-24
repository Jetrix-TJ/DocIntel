"""Decide per PAGE whether to trust the text layer or run OCR.

F2's measured rule: a page whose character count falls below
`NATIVE_CHAR_THRESHOLD` gets zero characters back from a "successful" parse of
a perfectly clean invoice, so `char_count == 0` and `char_count` too small to
be real text both mean the same thing here — there is nothing to read.

The routing decision is per page — a document-wide average was fitted to a
corpus whose per-DOCUMENT averages are bimodal, so it never met a document
with both native and scanned pages, and silently left the scanned ones
wordless. The bimodality is a property of the averages, not of individual
pages: measured per-page counts at HEAD include three documents with a page
in the 58-160 char range, well above zero but still sparse -

    Comcast    p1 1320  p2   58  p3 1900  p4  144  p5  144  p6 144
    Centracom  p1 1430 ... p9  675  p10   60
    Windstream p1 2180  p2 4246  p3 3461  p4  160

- so treating "0 or 500+, never mixed" as a per-PAGE fact would be wrong.
`text_source` stays a two-valued *document* summary, though: any starved page
makes the whole document `"ocr"`, because a later confidence modifier and two
Northstar ladder checks key off `text_source == "ocr"` exactly (see
`_load_document_uncached` for the full reasoning). Per-page provenance still
travels on `PageText.source` and `Span.source`.

**Where the threshold sits, and why (N2).** Measured with `pdf.read_meta` over
121 real PDFs / 1171 pages — the 10 gold documents plus every second-sample:

    158 pages read exactly 0 characters
      0 pages read anything between 1 and 57
      1 page  reads 58  (Comcast p2)      <- the lowest non-zero count in the pool
      1 page  reads 60  (Centracom p10)
      then 144, 144, 144, 160, 510, 610, 675, 803, 824, 1169, ...

So the two populations are separated by a band, `(0, 58)`, that is **completely
empty across 1171 real pages**. Any threshold in `[1, 58)` therefore leaves
`text_source` unchanged on every one of those 121 documents; the choice is
purely about which failure the remaining margin should buy insurance against.

The old value, 50, put 48 of the band's 57 characters on the scanned side and 8
on the native side. That was not a judgement — it was a round number chosen when
the band was believed to run from 0 to 500+, and the band's upper wall has since
closed in to 58 while the lower wall has not moved off 0 at all. The 8 remaining
characters are the problem, because the pages at the wall are not exotic:

    Comcast p2    `8633 0610 DY RP 09 12102025 NNNNNYNN 01 999457 Page 2 of 6`
    Centracom p10 `Page 10 of 10` + `* * * This page intentionally left blank * * *`

Both are a page footer plus one fixed component, on templates that recur
monthly. Drop Comcast p2's `Page 2 of 6` footer and the page reads 46; render
Centracom p10's notice without its asterisks and it reads 48. Either lands under
50, and the consequence is not local: one starved page marks the whole document
`"ocr"`, taking the `ocr_source` confidence penalty and possibly a lane, on a
document whose text layer was perfectly readable.

`_midpoint(0, 58) == 29` splits the measured band evenly instead:

- **native side, 29 characters.** Comcast p2 may lose half its text layer
  before misrouting. Covers both decompositions above (46 and 48) with 17-19
  characters to spare, against 50's -4 and -2.
- **scanned side, 28 characters.** A raster page carrying a little incidental
  live text is still OCR'd: a page number (`Page 2 of 6`, 11), a Bates stamp
  (`NSR-000142`, 10), a scanner date stamp (~20) all stay below it.

Even splitting is the placement that assumes least, and the two failures are
hard to price against each other: misrouting a native page costs confidence on
a readable document, while keeping a scanned page native loses that page's
content silently (a wordless page assigns role `unknown`, so reference matching
across attachments finds nothing). What the evidence does say is one-sided — the
native-side failure is 8 characters from firing on a live monthly template, and
the scanned-side failure is unattested in 158 scanned pages, every one of which
reads exactly 0, not 3 or 12. That argues for widening the native side, and 29
does, without collapsing a margin whose risk is merely unmeasured rather than
disproven. Going lower would buy native headroom already 17 characters clear of
the worst real decomposition, and pay for it in scanned coverage.

**Two mechanisms considered and rejected**, both recorded because each looked
right until measured:

- *`image_count` as a second dimension* — "a scanned page is ink we cannot
  read, a blank page is nothing to read" is the predicate this constant only
  approximates, and `PageMeta.image_count` is already per page. It does not
  separate them: measured, the scanned pages read `image_count == 1` and so does
  Centracom p10 (an intentionally-blank page with a logo), while Comcast p2 reads
  12 and genuinely native DTSS p1 reads 0. Telling them apart needs image *area*
  coverage, which `PageMeta` does not carry and which would mean widening a
  frozen contract for a signal validatable against only two scanned templates.
- *a per-document relative rule* — the other pages' counts are a distribution
  even though one page's count is not. But it needs an absolute floor anyway for
  the single-page and all-scanned shapes (6 of the 10 gold documents), so the
  floor keeps doing the load-bearing work; and comparing a page against its
  siblings is the same move whose *averaged* form caused the bug in the first
  paragraph above.

**The follow-up this does not do.** The honest fix for the native-side failure
is to stop inferring "the text layer failed" from "there is little text": OCR
the starved page, and if OCR *also* comes back with nothing, the page was
genuinely blank rather than unreadable, so the document should stay `"native"`.
That would make misrouting a blank page cost time instead of confidence and
dissolve the trade above — Centracom p10 and Windstream p4 both say
"intentionally left blank" in so many words. It is deliberately out of scope
here: it makes a `text_source` decision depend on OCR output, which is a routing
semantics change needing its own re-baseline, not a constant recalibration.

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

from docintel.core.errors import PermanentError
from docintel.core.models import PageMeta, PageText
from docintel.extract import ocr, ocr_cache, pdf

def _midpoint(low: int, high: int) -> int:
    """The middle of the empty band between two measured populations.

    A named function rather than a bare literal so the threshold below reads as
    the derivation it is. See the module docstring for why the midpoint is the
    right placement and what each half of the band buys.
    """
    return (low + high) // 2


# The measured populations, from `pdf.read_meta` over 121 real PDFs / 1171 pages
# (the 10 gold documents plus every second-sample). See the module docstring.
SPARSEST_NATIVE_PAGE = 58  # Comcast p2; the lowest non-zero count in the pool
LOWEST_SCANNED_PAGE = 0    # every one of the pool's 158 scanned pages

NATIVE_CHAR_THRESHOLD = _midpoint(LOWEST_SCANNED_PAGE, SPARSEST_NATIVE_PAGE)  # == 29

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
    # corpus whose per-document averages are bimodal (0 chars/page or 500+);
    # a native invoice with three scanned attachment pages averages ~586, took
    # the native path, and left those pages wordless - and a wordless page is
    # role `unknown`, so reference matching across attachments silently found
    # nothing. The bimodality is a property of the averages, not of pages:
    # measured per-page counts put three corpus documents' pages in the 58-160
    # char range (Comcast p2, Centracom p10, Windstream p4) - well clear of zero
    # but far below any document's average, which is why this is a per-page
    # predicate rather than a per-document one. See the module docstring for
    # where the threshold itself sits inside the measured band.
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
        # All-scanned still goes through the same completeness check as the
        # mixed branch below - "one `PageText` per `PageMeta`" is the
        # invariant, and it does not stop applying just because every page on
        # the document happened to be starved.
        ocred = _ocr_and_check_complete(path, starved)
        return tuple(ocred[m.page_number] for m in meta), meta, "ocr"

    native = {p.page_number: p for p in pdf.read_pages(path)}
    ocred = _ocr_and_check_complete(path, starved)
    pages = tuple(
        ocred[m.page_number] if m.page_number in ocred else native[m.page_number]
        for m in meta
    )
    return pages, meta, "ocr"


def _ocr_and_check_complete(path: str, page_numbers: list[int]) -> dict[int, PageText]:
    """OCR the given pages and confirm every one came back, keyed by page number.

    Without this, a short OCR result would let a caller fall back to the
    WORDLESS native page - silent data loss on exactly the page OCR exists to
    rescue. A raise here becomes a dead_letter with a reason, which is
    visible, on both callers (the all-scanned branch and the mixed branch).

    Raises `PermanentError`, not `TransientError`. The one reachable trigger
    is `pdf.read_meta` naming a page that `pdfplumber.pages` does not - a
    deterministic, structural mismatch, not a flaky one: retrying re-issues
    the identical OCR call and gets the identical answer, so `_run_one`
    retrying this `max_retries` times (`pipeline/runner.py`) buys nothing.

    It is worse than merely useless, too: `ocr.ocr_pages` writes whatever it
    returns to the on-disk OCR cache (`ocr_cache.py`, via `ocr.py:51`) BEFORE
    this check runs, so the short result is cached first. Every retry - within
    this process or a fresh one, hours later - reads the same incomplete
    result back from cache rather than re-OCRing, so nothing about calling
    this "transient" ever becomes true. `PermanentError` dead-letters on the
    first attempt (`_run_one` only retries `TransientError`), which is the
    right number of attempts for a failure that cannot resolve itself; the
    document still emits, via `Runner`'s dead-letter path, satisfying
    `count(intaken) == count(emitted)` same as before.
    """
    ocred = {p.page_number: p for p in ocr.ocr_pages(path, page_numbers)}
    missing = [n for n in page_numbers if n not in ocred]
    if missing:
        raise PermanentError(
            f"OCR returned no page for {missing} of {path!r}; "
            "refusing to fall back to a page with no text layer"
        )
    return ocred


def load_image_document(path: str) -> tuple[tuple[PageText, ...], tuple[PageMeta, ...], str]:
    """The image-native counterpart to `load_document`, for the six raster
    suffixes `extract.convert.IMAGE_SUFFIXES` names.

    A raster image never carries a text layer, so there is no native-vs-OCR
    decision to make the way there is for a PDF: `NATIVE_CHAR_THRESHOLD`
    never applies here, every page is definitionally starved, and every page
    always goes through OCR (`ocr.ocr_image`). `PageMeta` is built directly
    rather than read via `pdf.read_meta`, since there is no real PDF to
    introspect — a wrapped copy of this same image would have read back
    `char_count=0, image_count=1, annot_count=0` on every page regardless
    (an image wrapper carries no text layer, is itself the one embedded
    image, and has no PDF annotation object), so this states that directly
    instead of paying for a conversion + `pdfplumber` round trip just to
    learn a fact the format already determines.

    Memoized the same way as `load_document` — `(abspath, st_size,
    st_mtime_ns, content_hash)` — honouring the same `DOCINTEL_OCR_CACHE=0`
    escape hatch.
    """
    if not ocr_cache.enabled():
        return _load_image_document_uncached(path)
    key = _memo_key(path)
    if key is None:
        return _load_image_document_uncached(path)
    return _load_image_document_cached(key)


@functools.lru_cache(maxsize=_MEMO_CACHE_SIZE)
def _load_image_document_cached(
    key: _MemoKey,
) -> tuple[tuple[PageText, ...], tuple[PageMeta, ...], str]:
    return _load_image_document_uncached(key[0])


def _load_image_document_uncached(path: str) -> tuple[tuple[PageText, ...], tuple[PageMeta, ...], str]:
    pages = ocr.ocr_image(path)
    meta = tuple(
        PageMeta(page_number=p.page_number, char_count=0, image_count=1, annot_count=0)
        for p in pages
    )
    return pages, meta, "ocr"
