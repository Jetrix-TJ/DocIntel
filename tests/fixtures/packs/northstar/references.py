"""Reference patterns (pack spec section 3) — the match key back to Northstar's
system of record, which the corpus buries under at least five different labels (F11).

Every hit carries provenance: the value, which field or column it came from, the
page, and which pattern matched. That is the whole point — a bare list of
seven-digit numbers is indistinguishable from a list of zip+4 fragments, and a
downstream matcher cannot tell whether `2436687` came from a printed Reference
column or from a human's margin note.

**`ref_column` is a bare seven-digit pattern** and is therefore only legal scoped
to a column (grammar V6). Unscoped it matches phone fragments, zip+4 and account
numbers. It reads from the extracted `line_items` row group's `reference` column
rather than from page text, which is what makes the scope real rather than stated.

**Annotation hazard (F3).** Federal Recycling's flattened boxes carry `2436818`,
`2436820`, `2436821`, `2469435`, `2469427` — human corrections that OCR cannot
distinguish from print. When the overlay detector has fired, every hit found in
page text on that document is tagged `annotation_overlay` rather than being
silently merged with printed references.
"""

from __future__ import annotations

import re

from docintel.core.models import JobContext, ReferenceHit

# (pattern_id, compiled pattern, source_field label). Ordered; all are captured.
TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("ns_hash", re.compile(r"NS\s?#\s?(\d{7})"), "NS #"),
    ("northstar_hash", re.compile(r"Northstar#\s*(\d{7})", re.I), "Northstar#"),
    ("work_order", re.compile(r"WORK\s*ORDER#:\s*(\d{7})", re.I), "WORK ORDER#"),
    ("seal", re.compile(r"SEAL#\s*(\d{7})", re.I), "SEAL#"),
    ("bol", re.compile(r"BOL#\s*([\d-]{8,12})", re.I), "BOL#"),
    ("sales_order", re.compile(r"SALES\s+ORDER\s+NO\.?\s*(\d{8})", re.I), "SALES ORDER NO."),
)

# The column a bare seven-digit reference may be read from, and nothing else.
REF_COLUMN = "reference"
REF_COLUMN_PATTERN = re.compile(r"^(\d{7})$")

ANNOTATION_SOURCE = "annotation_overlay"


def collect(ctx: JobContext) -> JobContext:
    """Append every reference hit, with provenance, deduplicated.

    Runs across *every* page, not only primary ones: a supporting Bill of Lading
    is exactly where a seal or BOL number gets corroborated (F10), and a
    reference is not a field value so section 7 does not restrict it.
    """
    annotated = "has_flattened_annotations" in ctx.tags
    seen = {(h.value, h.pattern_id) for h in ctx.reference_list}

    for page in ctx.pages:
        text = page.text
        for pattern_id, pattern, source_field in TEXT_PATTERNS:
            for value in pattern.findall(text):
                key = (value, pattern_id)
                if key in seen:
                    continue
                seen.add(key)
                ctx.reference_list.append(
                    ReferenceHit(
                        value=value,
                        source_field=ANNOTATION_SOURCE if annotated else source_field,
                        page=page.page_number,
                        pattern_id=pattern_id,
                    )
                )

    _collect_ref_column(ctx, seen, annotated)
    return ctx


def _collect_ref_column(
    ctx: JobContext, seen: set[tuple[str, str]], annotated: bool
) -> None:
    """The bare seven-digit pattern, scoped to the `reference` column only (V6)."""
    rows = ctx.row_groups.get("line_items") or []
    page = ctx.pages[0].page_number if ctx.pages else 1
    for row in rows:
        raw = row.get(REF_COLUMN)
        if raw is None:
            continue
        match = REF_COLUMN_PATTERN.match(str(raw).strip())
        if match is None:
            continue
        value = match.group(1)
        key = (value, "ref_column")
        if key in seen:
            continue
        seen.add(key)
        ctx.reference_list.append(
            ReferenceHit(
                value=value,
                source_field=ANNOTATION_SOURCE if annotated else "Reference",
                page=page,
                pattern_id="ref_column",
            )
        )
