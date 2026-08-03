"""Line-grouping geometry shared by `core.models.PageText` and `grammar.regions.Span`.

Two findings, one fix (B2/B2b). `PageText.lines()` and `Span.lines()` were the
*same nine-line grouping algorithm*, copy-pasted, each reading its own
module-level `_LINE_TOLERANCE = 3.0`, bound only by a comment. Fixing the
constant alone would have left two implementations free to drift; this module
is the one implementation both now delegate to via `group_lines`.

**The threshold itself (B2).** `3.0` had under 0.6pt of margin on 6 of 10 corpus
documents, whose tightest GENUINE inter-line gap measured 3.02-3.60pt against
the 3.0pt grouping threshold — a document only slightly tighter than that
merges two logical lines and corrupts every row and column read off it.

`line_tolerance` derives the threshold from the page's own line pitch (the
median gap between distinct line baselines) instead of one global constant,
**capped at today's 3.0pt** so no page is EVER grouped more loosely than it is
today — a tight page is merely allowed to go *below* 3.0, which is the entire
fix. A page with fewer than two lines has no pitch to measure and gets the same
3.0 default it always did.

**Why the pitch is measured from bootstrapped LINES, not raw word y0s.**
Tesseract reports a separate box per word, and two words on the *same* visual
line routinely differ by a few tenths of a point (ascender height, a
descender, rounding). Measuring gaps between every distinct `Word.y0` directly
means most of those "gaps" are intra-line jitter, not inter-line pitch: on one
corpus OCR page, raw gaps of 0.36pt between same-line words dragged the naive
median down to 2.88pt, producing a ~1.15pt tolerance that shattered every real
line into fragments (caught by a corpus regression on
`northstar-complete-beverage`'s `vendor_address`, read via `label-block`'s
`text_block`). So `line_tolerance` first groups with `DEFAULT_TOLERANCE` — i.e.
today's grouping — and measures the pitch between the resulting *rows*, not
between individual words.

**The fraction, against the measurement.** Corpus median line pitch ranges
5.8-12.4pt; the tightest genuine (non-merge) gaps measure 3.02-3.60pt.
`_PITCH_FRACTION = 0.4` (40% of a page's own median pitch):

- at the tightest observed pitch, 5.8pt: `0.4 * 5.8 = 2.32`, comfortably under
  the 3.02pt floor — 0.7pt of margin, versus 3.0's bare 0.02pt. This is the fix.
- at the loosest observed pitch, 12.4pt: `0.4 * 12.4 = 4.96`, which the 3.0 cap
  pulls straight back down to exactly today's value — loose pages are
  unaffected, satisfying the "never looser than today" requirement.
- the cap engages at `pitch == 7.5` (where `0.4 * pitch == 3.0`), so every page
  with a pitch below ~7.5pt gets a tighter, safer number and every page at or
  above it keeps 3.0pt exactly, unchanged.

A fraction near 0.5 was rejected: `0.5 * 5.8 = 2.9`, only 0.12pt under the
3.02pt floor — effectively the same near-zero margin this task exists to
remove. 0.4 leaves real headroom without being so small that ordinary
baseline jitter *inside* one visual line starts reading as two.
"""

from __future__ import annotations

import statistics
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Deferred: `core.models` imports this module for `DEFAULT_TOLERANCE` and
    # `group_lines`, so importing `Word` back at module load time would be
    # circular. `from __future__ import annotations` (above) means annotations
    # are never evaluated at runtime, so this is safe for typing only.
    from docintel.core.models import Word

DEFAULT_TOLERANCE = 3.0  # points; today's ceiling, and the <2-line default
_PITCH_FRACTION = 0.4  # see module docstring for the corpus math behind this


def group_lines(words: tuple[Word, ...], tolerance: float) -> list[list[Word]]:
    """Group words into visual lines, each sorted left to right.

    Lifted verbatim from the old `PageText.lines()` / `Span.lines()` — they
    were byte-identical — except the tolerance is a parameter rather than a
    module global, so it can vary per page (B2) without a second copy of the
    algorithm (B2b). Callers compute `tolerance` once, at construction (see
    `extract/pdf.py`, `extract/ocr.py`), and carry it as a field; this function
    never computes it itself.
    """
    out: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.y0, w.x0)):
        if out and abs(out[-1][0].y0 - w.y0) <= tolerance:
            out[-1].append(w)
        else:
            out.append([w])
    for line in out:
        line.sort(key=lambda w: w.x0)
    return out


def line_tolerance(words: tuple[Word, ...]) -> float:
    """The vertical distance within which two words share a line, for this page.

    The median gap between distinct line baselines, times `_PITCH_FRACTION`,
    capped at `DEFAULT_TOLERANCE`. Fewer than two lines means there is no pitch
    to measure, so the default applies. The lines used to measure the gap are
    bootstrapped with `DEFAULT_TOLERANCE` itself (today's grouping) rather than
    read off raw distinct `Word.y0` values — see the module docstring for why
    that distinction matters on OCR'd pages.
    """
    lines = group_lines(words, DEFAULT_TOLERANCE)
    if len(lines) < 2:
        return DEFAULT_TOLERANCE
    baselines = sorted(line[0].y0 for line in lines)
    gaps = [b - a for a, b in zip(baselines, baselines[1:])]
    pitch = statistics.median(gaps)
    return min(pitch * _PITCH_FRACTION, DEFAULT_TOLERANCE)
