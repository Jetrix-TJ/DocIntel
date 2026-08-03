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

import docintel.core.geometry as geometry
from docintel.core.geometry import line_tolerance
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


def test_a_single_line_falls_back_to_the_default() -> None:
    """No second baseline, so no pitch to measure."""
    assert line_tolerance(_words_at_pitch(14.0, rows=1)) == 3.0


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
