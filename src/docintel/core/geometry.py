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

**The floor, against a page where the pitch is not a pitch (final-review
Finding 1).** Every argument above assumes the measured pitch IS a text
leading. On one corpus page it demonstrably is not: `_AP Invoice 32930 Complete
Beverage Destruction` page 2 is a degraded OCR'd scan whose bootstrap-measured
median pitch is **4.68pt** — below any genuine leading in the corpus — because
the scan fragments enough lines that the fragments become the median. Bootstrapping
from lines rather than raw word y0s (above) reduces that failure mode but does
not eliminate it: it only takes a page where most lines fragment. `0.4 * 4.68 =
1.872` then shatters the page further, 99 lines to 124, splitting real visual
lines apart (`FL S35R3, Seal number(s); 5 GSii GF` becomes two lines). A ceiling
cannot catch this. The derived value needs a floor as well.

`MIN_TOLERANCE = 2.5`, justified against the same corpus, re-measured over all
39 pages of the 10 gold documents:

- **it can never merge two real lines.** The tightest GENUINE inter-line gap
  measured is 3.018pt (`digitaldirection-windstream-041069076` p2 — the low end
  of the 3.02-3.60pt range quoted above, confirmed). 2.5 sits 0.52pt under it,
  so adding a floor does not weaken the ceiling's safety property at all; the
  floor is still further below the tightest genuine gap than today's 3.0 is.
- **it engages only below a pitch no real leading reaches:** at `pitch <
  MIN_TOLERANCE / _PITCH_FRACTION == 6.25`. Exactly ONE of the 39 pages is under
  that line — Complete Beverage p2, at 4.68. The other 38 are unchanged, including
  the only other page the ceiling does not already pin at 3.0 (Lumen p2, pitch
  7.2 -> 2.88, still above the floor).
- **it BOUNDS the damage, it does not repair it.** At 2.5 that page groups to 114
  lines, not the 99 a plain 3.0 gives. Restoring 99 would take a floor of 2.88,
  which is 0.14pt under the 3.018pt genuine gap — the same near-zero margin this
  module exists to remove — and would make the ceiling's entire tightening inert.
  2.5 recovers 10 of the 25 spurious splits and keeps half a point of real
  margin, which is the better trade.

Two things to be honest about here. First, the deliberate consequence: below
`pitch == 2.5` the floor EXCEEDS the measured pitch, so such a page is grouped
loosely rather than tightly, and `tolerance < pitch` stops holding. That is the
correct failure direction, not an oversight — a pitch that small is
fragmentation rather than leading, and the page above shows the harm on such a
page comes from over-splitting, not over-merging. Second, the `5.8pt` low end of
the pitch range quoted further up does not reproduce against today's corpus:
re-measuring puts the tightest genuine median pitch at 7.2pt (the 4.68 outlier
aside). That range predates `NATIVE_CHAR_THRESHOLD`'s recentring from 50 to 29,
which moved pages between the native and OCR paths. The fraction's margin
argument only gets *stronger* under the newer numbers, so `_PITCH_FRACTION` is
left exactly as it was and the older figure is left on the record rather than
quietly restated.
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
MIN_TOLERANCE = 2.5  # points; the floor, 0.52pt under the tightest genuine gap
_PITCH_FRACTION = 0.4  # see module docstring for the corpus math behind these


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
    clamped between `MIN_TOLERANCE` and `DEFAULT_TOLERANCE`. Fewer than two
    lines means there is no pitch to measure, so the default applies. The lines
    used to measure the gap are bootstrapped with `DEFAULT_TOLERANCE` itself
    (today's grouping) rather than read off raw distinct `Word.y0` values — see
    the module docstring for why that distinction matters on OCR'd pages.

    Both bounds exist for the same reason from opposite sides: a measured pitch
    is only trustworthy inside the band real text leading occupies. Above the
    band the ceiling keeps a loose page at exactly today's grouping; below it the
    floor stops a degraded scan's fragmentation artifact from being read as a
    pitch and shattering the page. The module docstring has the measurements for
    both numbers.
    """
    lines = group_lines(words, DEFAULT_TOLERANCE)
    pitch = median_pitch(lines)
    if pitch is None:
        return DEFAULT_TOLERANCE
    return max(MIN_TOLERANCE, min(pitch * _PITCH_FRACTION, DEFAULT_TOLERANCE))


def median_pitch(lines: list[list[Word]]) -> float | None:
    """The median gap between consecutive line baselines, or `None` below two lines.

    The RAW pitch — not `line_tolerance`'s scaled-and-capped derivative of it.
    `line_tolerance` multiplies this by `_PITCH_FRACTION` and ceilings it at
    `DEFAULT_TOLERANCE`, which answers "how close counts as the same line" but
    is the wrong number for a caller that wants the actual line spacing itself:
    `grammar.regions` scales its own absolute point constants (`NEAR_ANCHOR_BELOW`
    and friends, B4/Task 8) by the page's real pitch, not by 40% of it. Extracted
    so both measure "the median gap between two line baselines" the same way,
    rather than `regions.py` re-deriving this arithmetic a second time.

    **`line[0].y0` is the LEFTMOST word's y0, not the line's lowest one** —
    `group_lines` x-sorts each line before returning it. So these are not quite
    baselines: within one line the leftmost word can sit a point or two off the
    others, and the "gap" absorbs that. It is why a measured pitch BELOW
    `DEFAULT_TOLERANCE` is reachable at all (the bootstrap's own group heads are
    always more than the tolerance apart, so a true baseline measurement could
    never go under it), and therefore why `line_tolerance` needs a floor and not
    only a ceiling. Left as is deliberately: both `line_tolerance` and
    `grammar.regions` have been measured and tuned against exactly this
    definition, so changing it here silently re-tunes both.
    """
    if len(lines) < 2:
        return None
    baselines = sorted(line[0].y0 for line in lines)
    gaps = [b - a for a, b in zip(baselines, baselines[1:])]
    return statistics.median(gaps) if gaps else None
