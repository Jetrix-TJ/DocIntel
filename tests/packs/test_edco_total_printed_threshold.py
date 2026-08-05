"""Edco's `total_printed` has no printed label on the page it's read from
(confirmed by reading the real second-sample PDFs), so a region-only match is
the strongest evidence this field can ever produce. Held at 0.95 - the same
bar as an anchored field - it can never clear `high`, even when the value is
correct, which it always was in the F1-verified corpus. See the commit this
test ships with for the page-geometry evidence."""

from __future__ import annotations

from docintel.grammar.executor import QUALITY_REGION_ONLY
from docintel.packs.northstar.thresholds import THRESHOLDS


def test_edco_total_printed_threshold_is_reachable_by_a_region_only_match() -> None:
    assert THRESHOLDS["total_printed"] <= QUALITY_REGION_ONLY
