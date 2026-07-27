"""Human annotations that were flattened into the page image before it ever
reached this pipeline. Finding F3: `CONTRA ONLY Everything already on AR
Federal Recycling 1330123.pdf` carries six coloured highlights and comment
boxes whose reference numbers *contradict* the printed ones — someone's
after-the-fact accounting notes, scanned along with the invoice. Critically,
`pdfplumber` reports `annots == 0` for this document: the markup was baked
into the page raster (probably by the scanner or a "print with comments"
step) before the PDF was produced, so there is no PDF annotation *object* to
enumerate or strip. Detection therefore has to work from the rendered page
pixels, never from `page.annots`.

Two pixel signals, both required:

1. A meaningful fraction of the page is covered in *pastel*, moderately
   saturated colour — the wash a translucent highlighter leaves over black
   text, or a solid comment-box fill, as opposed to a print-shop logo or
   masthead, which is usually rendered near-fully saturated ("pure") ink.
   Standard HSV saturation, not raw channel spread, is what separates these
   in practice: Federal Recycling's highlight/comment colours sit in a
   moderate S band (roughly 40-170 of 255) at high value, while every other
   corpus document's colour content — Comcast's and Windstream's brand
   blues, EDCO's dusty-red letterhead tint, U-PAK's stamp ink — is either
   far more saturated (near 240) or occupies a single narrow hue with a much
   smaller pastel-band footprint.
2. That colour is spread across many small, separate regions of the page
   rather than concentrated in one or two large blocks. A logo or masthead
   is normally one contiguous graphic near the top of the page; six
   independent highlighter strokes and comment boxes scattered down the
   page (as in Federal Recycling — see `docs/corpus-analysis.md` F3) light
   up dozens of small cells in a coarse grid over the page, a logo lights up
   a handful.

Both thresholds below were picked by rendering every page of the corpus at
this module's resolution, measuring the pastel-band pixel fraction and grid
hit-count for each, and choosing a cut that leaves Federal Recycling's only
page clearly on one side and every other page (all 39 across the remaining
nine documents, including two other OCR-only pages) clearly on the other,
with better than 2x margin either way. This is a corpus-evidence heuristic,
not a general annotation detector — see F3 for why getting it wrong is
expensive in both directions: a false positive costs a needless human
review, a false negative lets contradicted reference numbers through
silently, which is why `has_flattened_annotations` forces review
unconditionally rather than merely discounting confidence.

**Known blind spot, stated plainly because an undocumented one is a trap: this
detector is entirely saturation-dependent, and therefore CANNOT see a
greyscale scan or a black/grey-pen annotation.** Both pixel signals key off
HSV saturation (`SAT_MIN`-`SAT_MAX`); any page rendered in greyscale, or any
annotation made in black or grey ink on a greyscale-adjacent page, has
S≈0 everywhere and never enters the pastel band no matter how much of the
page it covers or how scattered it is. That is precisely the failure mode
F3 cares about most — a contradicted value passing through with no forced
review, silently. This is not something this task fixes (distinguishing
"annotation ink" from "printed ink" in a greyscale image is a genuine
computer-vision problem, out of scope here); `tests/extract/test_annotations.py`
pins the limitation with a synthetic all-grey annotated page that this
detector is expected — not merely observed — to miss, so a future change
that silently narrows the blind spot further has to touch a test that says
so, and so this gap stays visible instead of being rediscovered by surprise.

Rendering a page is not free, and `detect_flattened` can be called many
times for the same document within one process — the fault-injection matrix
in `tests/test_invariant.py` reprocesses a single corpus document across
dozens of pipeline configurations. This module therefore memoizes on the
same `(abspath, size, mtime, content_hash)` key `normalize.load_document`
uses, and honours the same `DOCINTEL_OCR_CACHE=0` escape hatch — see
`normalize.py` for why the content hash, not just path/size/mtime, is what
makes the key correct.

A naming trap for anyone importing this module: `docintel/extract/__init__.py`
itself has `from __future__ import annotations` at module scope, which binds
the *package's own* `annotations` attribute to a `__future__._Feature`
object. `from docintel.extract import annotations` therefore silently
resolves to that feature flag instead of this submodule — `getattr` finds
the pre-existing package attribute and never triggers the submodule import.
Always import this module as `import docintel.extract.annotations` (with or
without `as annotations`), or `from docintel.extract.annotations import
detect_flattened` directly; both bypass the package `__init__.py` namespace
entirely and resolve correctly.
"""

from __future__ import annotations

import functools
import os

import pdfplumber
from pdfplumber.page import Page
from PIL import Image, ImageChops

from docintel.core.models import PageMeta, PageText
from docintel.extract import ocr_cache

RESOLUTION = 100  # dpi used to rasterize each page for colour analysis

# HSV saturation band (0-255) for a translucent highlighter wash / comment-box
# fill: bright but not fully saturated the way printed brand-colour ink is.
SAT_MIN = 40
SAT_MAX = 170
VALUE_MIN = 140  # bright enough to be a wash, not a shadow or dark ink

FRAC_THRESHOLD = 0.03  # fraction of page pixels that must fall in the band

# Coarse grid used to measure how *spread out* the coloured pixels are.
GRID_COLS = 40
GRID_ROWS = 52
CELL_HIT_THRESHOLD = 24  # average out of 255 in a downsampled cell
MIN_HIT_CELLS = 50  # scattered marks, not one printed logo block

_SAT_LUT = [255 if SAT_MIN <= i <= SAT_MAX else 0 for i in range(256)]
_VALUE_LUT = [255 if i >= VALUE_MIN else 0 for i in range(256)]

_MEMO_CACHE_SIZE = 64
_MemoKey = tuple[str, int, int, str]


def detect_flattened(path: str, pages: tuple[PageText, ...], meta: tuple[PageMeta, ...]) -> bool:
    """True if any page of `path` carries human annotations flattened into
    its raster image.

    Only pages whose `PageMeta.annot_count` is 0 are examined — a page that
    already carries a real PDF annotation layer has objects a different
    mechanism can strip; "flattened" specifically means there is nothing
    left to strip, which is what makes this detector necessary at all.
    `pages` is accepted for interface symmetry with the rest of this
    package's `(path, pages, meta)` signature but is not otherwise needed:
    detection is pixel-based per F3, not text-based.
    """
    del pages  # detection is pixel-based; see module docstring
    annotated_page_numbers = frozenset(m.page_number for m in meta if m.annot_count == 0)
    if not annotated_page_numbers:
        return False

    if not ocr_cache.enabled():
        return _detect_uncached(path, annotated_page_numbers)
    key = _memo_key(path)
    if key is None:
        return _detect_uncached(path, annotated_page_numbers)
    return _detect_cached(key, annotated_page_numbers)


def _memo_key(path: str) -> _MemoKey | None:
    try:
        abspath = os.path.abspath(path)
        stat = os.stat(abspath)
        digest = ocr_cache.content_hash(abspath)
    except OSError:
        return None
    return (abspath, stat.st_size, stat.st_mtime_ns, digest)


@functools.lru_cache(maxsize=_MEMO_CACHE_SIZE)
def _detect_cached(key: _MemoKey, page_numbers: frozenset[int]) -> bool:
    return _detect_uncached(key[0], page_numbers)


def _detect_uncached(path: str, page_numbers: frozenset[int]) -> bool:
    with pdfplumber.open(path) as doc:
        for page in doc.pages:
            if page.page_number in page_numbers and _page_is_annotated(page):
                return True
    return False


def _page_is_annotated(page: Page) -> bool:
    img = page.to_image(resolution=RESOLUTION).original.convert("RGB")
    return _image_is_annotated(img)


def _image_is_annotated(img: Image.Image) -> bool:
    """The pixel-only half of detection, split out from `_page_is_annotated`
    so it can be exercised directly against a synthetic `PIL.Image` in tests
    — in particular the greyscale blind spot pinned in
    `tests/extract/test_annotations.py` (see module docstring), which needs
    no real PDF at all, just an image with S≈0 everywhere.
    """
    total_px = img.size[0] * img.size[1]
    if total_px == 0:
        return False

    hsv = img.convert("HSV")
    _, s_band, v_band = hsv.split()
    mask = ImageChops.multiply(s_band.point(_SAT_LUT), v_band.point(_VALUE_LUT))

    hit_px = mask.histogram()[-1]
    if hit_px / total_px < FRAC_THRESHOLD:
        return False

    grid = mask.resize((GRID_COLS, GRID_ROWS), Image.BOX)
    hit_cells = sum(1 for cell in grid.get_flattened_data() if cell >= CELL_HIT_THRESHOLD)
    return hit_cells >= MIN_HIT_CELLS
