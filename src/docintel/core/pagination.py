"""Shared "N OF M" pagination-footer detection.

Extracted from `packs/northstar/ladder.py`'s `_is_paginated_continuation`
(pack-local, `JobContext`-shaped) so `extract/pageroles.py` can use the same
proof of "these pages are one continuous document" without a `packs ->
extract` dependency inversion. `core` is the layer both `extract/` and
`packs/` already depend on (see `packs/registry.py`'s own note on this), so
this is the direction that cannot cycle.
"""

from __future__ import annotations

import re

from docintel.core.models import PageText

_PAGE_OF_RE = re.compile(r"\b(\d+)\s+OF\s+(\d+)\b")


def shared_footer_pages(pages: tuple[PageText, ...]) -> frozenset[int] | None:
    """The full 1-indexed page-number set if every page carries a footer
    matching `N OF M` with `M == len(pages)`, and the N's cover 1..len(pages)
    exactly once between them. `None` otherwise — including for a single-page
    document, where "continuation" is not a meaningful claim.
    """
    total_pages = len(pages)
    if total_pages < 2:
        return None
    seen_numbers: set[int] = set()
    for page in pages:
        found = False
        for line in page.lines():
            text = " ".join(w.text for w in line).upper()
            match = _PAGE_OF_RE.search(text)
            if match and int(match.group(2)) == total_pages:
                seen_numbers.add(int(match.group(1)))
                found = True
                break
        if not found:
            return None
    if seen_numbers != set(range(1, total_pages + 1)):
        return None
    return frozenset(seen_numbers)
