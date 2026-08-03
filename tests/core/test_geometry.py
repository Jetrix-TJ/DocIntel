"""B2/B2b: one line-grouping implementation, one tolerance per page.

`core/models.py` and `grammar/regions.py` used to carry byte-identical
nine-line grouping algorithms, each reading its own module-level
`_LINE_TOLERANCE = 3.0`. This module is the single implementation both
delegate to, and the tolerance is derived from the page's own line pitch
(median gap between distinct baselines) rather than a global constant —
see `core/geometry.py`'s module docstring for the fraction's justification
against the actual corpus measurements.
"""

from __future__ import annotations

import pytest

import docintel.core.geometry as geometry
from docintel.core.geometry import group_lines, line_tolerance, median_pitch
from docintel.core.models import PageText, Word


def _words_at_pitch(pitch: float, rows: int = 5) -> tuple[Word, ...]:
    """`rows` distinct baselines, `pitch` points apart, one word per row."""
    return tuple(
        Word(text=f"row{i}", x0=10.0, y0=100.0 + i * pitch, x1=50.0, y1=100.0 + i * pitch + 10.0)
        for i in range(rows)
    )


def _page_from_rows(rows: list[tuple[float, str]]) -> PageText:
    """A page whose words sit one per row at the given (y0, text) pairs.

    Computes the tolerance the same way a real construction site
    (`extract/pdf.py`, `extract/ocr.py`) does: once, from the page's own
    words, at construction — through the module reference so a monkeypatch
    on `geometry.line_tolerance` is visible here.
    """
    words = tuple(
        Word(text=text, x0=10.0, y0=y0, x1=10.0 + len(text) * 6.0, y1=y0 + 10.0)
        for y0, text in rows
    )
    return PageText(
        page_number=1,
        words=words,
        width=612.0,
        height=792.0,
        source="native",
        line_tolerance=geometry.line_tolerance(words),
    )


def test_tolerance_scales_with_a_tight_page() -> None:
    """A 6pt-leading page must not use the same tolerance as a 20pt one."""
    tight = _words_at_pitch(6.0)
    loose = _words_at_pitch(20.0)
    assert line_tolerance(tight) < line_tolerance(loose)


def test_tolerance_never_reaches_the_pitch_itself() -> None:
    """A tolerance at or above the pitch merges every line into one."""
    for pitch in (6.0, 12.0, 20.0):
        assert line_tolerance(_words_at_pitch(pitch)) < pitch


def test_no_page_is_grouped_more_loosely_than_today() -> None:
    """3.0 is a CEILING, not a floor. A loose page keeps today's behaviour;
    a tight page is allowed below it, which is the entire fix.
    """
    assert line_tolerance(_words_at_pitch(20.0)) == 3.0
    assert line_tolerance(_words_at_pitch(5.8)) < 3.02


def test_an_implausible_bootstrap_pitch_is_floored_not_trusted() -> None:
    """4.68pt is the REAL bootstrap pitch of `_AP Invoice 32930 Complete
    Beverage Destruction` page 2, a degraded OCR'd scan. It is not a text
    leading — it is the median of the scan's own line fragments — and
    `0.4 * 4.68 = 1.872` shatters that page from 99 lines to 124, splitting
    real visual lines apart. The ceiling cannot catch this; the floor does.
    """
    assert line_tolerance(_words_at_pitch(4.68)) == geometry.MIN_TOLERANCE
    assert line_tolerance(_words_at_pitch(4.68)) > 4.68 * geometry._PITCH_FRACTION


def test_ocr_jitter_pitch_cannot_drive_the_tolerance_to_nothing(monkeypatch) -> None:
    """The degenerate end, all the way down.

    `median_pitch` is patched rather than fed synthetic words, because a
    one-word-per-row fixture CANNOT produce a measured pitch below 3.0: every
    bootstrap line's head is more than `DEFAULT_TOLERANCE` from the previous
    one by construction. A real page reaches 4.68 anyway because `median_pitch`
    reads each line's LEFTMOST word's `y0`, which on a fragmented scan is not
    that line's own lowest baseline — so arbitrarily small measured pitches are
    reachable on real input and the clamp has to hold for all of them.
    """
    for pitch in (0.36, 1.0, 2.0, 4.0, 6.24):
        monkeypatch.setattr(geometry, "median_pitch", lambda _lines, p=pitch: p)
        assert line_tolerance(_words_at_pitch(12.0)) == geometry.MIN_TOLERANCE


def test_the_floor_stays_under_the_tightest_genuine_corpus_gap() -> None:
    """The floor is only safe because it can never merge two real lines: the
    tightest GENUINE inter-line gap measured across the corpus is 3.018pt
    (`digitaldirection-windstream-041069076` p2). A floor at or above that
    number would merge it and corrupt every row read off that page.
    """
    assert geometry.MIN_TOLERANCE < 3.018
    assert geometry.MIN_TOLERANCE < geometry.DEFAULT_TOLERANCE


def test_the_floor_engages_only_below_a_pitch_no_real_leading_reaches() -> None:
    """`MIN_TOLERANCE / _PITCH_FRACTION` is where the floor starts to bind. The
    38 corpus pages with a genuine measurable pitch all sit at 7.2pt or above,
    so the floor is inert on every one of them; only the degraded scan is
    below the line.
    """
    engages_at = geometry.MIN_TOLERANCE / geometry._PITCH_FRACTION
    assert engages_at < 7.2, "the floor must not reach a genuine corpus pitch"
    assert line_tolerance(_words_at_pitch(7.2)) == pytest.approx(
        7.2 * geometry._PITCH_FRACTION
    )


def test_a_single_line_falls_back_to_the_default() -> None:
    """No second baseline, so no pitch to measure."""
    assert line_tolerance(_words_at_pitch(14.0, rows=1)) == 3.0


def test_median_pitch_is_the_raw_gap_not_line_tolerances_scaled_derivative() -> None:
    """B4/Task 8: `grammar.regions` needs the actual line spacing to scale its
    own absolute constants, not `line_tolerance`'s 40%-of-pitch-capped-at-3.0
    value. `median_pitch` is the shared measurement both now delegate to."""
    lines = group_lines(_words_at_pitch(20.0), geometry.DEFAULT_TOLERANCE)
    assert median_pitch(lines) == 20.0


def test_median_pitch_is_none_below_two_lines() -> None:
    lines = group_lines(_words_at_pitch(14.0, rows=1), geometry.DEFAULT_TOLERANCE)
    assert median_pitch(lines) is None


def test_the_tolerance_is_computed_once_not_per_lines_call(monkeypatch) -> None:
    """lines() is called 21 times across the grammar, several inside loops.
    Computing the median inside it would add an O(n log n) pass to each one.
    """
    calls = 0
    real = geometry.line_tolerance

    def counted(words):
        nonlocal calls
        calls += 1
        return real(words)

    monkeypatch.setattr(geometry, "line_tolerance", counted)
    page = _page_from_rows([(100.0, "a"), (114.0, "b"), (128.0, "c")])
    before = calls
    for _ in range(5):
        page.lines()
    assert calls == before, "line_tolerance was recomputed inside lines()"
