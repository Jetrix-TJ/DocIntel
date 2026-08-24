"""Persona -> vision hints: a field list and a prose sentence per field, no
anchor/region regex sent verbatim.

Stage 5b (`s5b_vision.VisionOneShot`) reaches for this whenever a persona is
known but the regex path came back empty, weak, or mostly missing (see
`s5b_vision._collapsed`). Before this module existed, that case still asked
vision for a fixed 4-field list (`vendor_name`, `invoice_number`,
`invoice_date`, `total_printed`) with no hints at all, regardless of what the
persona actually declares - the one case a KNOWN vendor's collapse most needs
the persona's own field list to recover, since a rule set already exists for
it.

**Why prose, not the regex itself.** Deleting every anchor and region from a
Gemini prompt, across 10 documents and 256 assertions, moved 1 value in 102
that had one (`docs/agent-hints/README.md` - an external experiment against
this same codebase, not a claim invented here). What is load-bearing is the
field NAME, its TYPE (handled separately, by `patterns.NAMED` at coercion
time - this module only builds the location prose), and a short description of
where a human would look - not the regex, which would read as an instruction
to a model that cannot run it anyway.
"""

from __future__ import annotations

import re
from typing import Any

from docintel.core.models import DERIVED_ONLY

# Human-readable descriptions of the region vocabulary (grammar/regions.py).
# Anything not listed is omitted rather than guessed at: a vague hint is worse
# than no hint.
_REGION_PROSE: dict[str, str] = {
    "top-left": "top-left of the page",
    "top-right": "top-right of the page",
    "top-center": "top-center of the page",
    "header-block": "in the header, top quarter of page 1",
    "near-anchor": "just below or beside that label",
    "same-row": "on the same line as that label",
    "same-cell": "in the same table cell as that label",
    "label-block": "in the block of lines under that label",
    "totals-block": "in the totals box",
    "remittance-block": "in the remittance/payment-coupon block",
    "first-page": "on the first page",
    "last-page": "on the last page",
    "line_items": "in the line-item table",
    "last-table-row": "in the last row of the table",
    # Not "anywhere in the document" - vision may be shown a page subset, and
    # telling a model to search pages it cannot see invites a fabricated answer.
    "any-page": "no fixed position, scan the page",
}

# Shape hints worth stating. A regex is not sent verbatim - it would read as an
# instruction to a model rather than as a description - but a digit count or a
# named shape is a genuinely useful, purely descriptive fact.
_PATTERN_PROSE: dict[str, str] = {
    "currency": "a money amount",
    "currency_signed": "a signed money amount",
    "date": "a date",
    "date_loose": "a date, loosely formatted",
    "integer": "a whole number",
    "decimal": "a decimal number",
    "text_block": "several lines of text",
    "account_number": "an account number",
    "tax_id": "a tax ID",
    "phone": "a phone number",
    "postal_code": "a postal code",
}

_DIGIT_RUN = re.compile(r"\(?\[0-9\]\{(\d+)\}\)?")


def _shape_prose(pattern: object) -> str | None:
    if not isinstance(pattern, str):
        return None
    if pattern in _PATTERN_PROSE:
        return _PATTERN_PROSE[pattern]
    # A bare digit-count regex such as "([0-9]{10})" is safe to describe.
    m = _DIGIT_RUN.fullmatch(pattern)
    return f"{m.group(1)} digits" if m else None


def _scalar_selectors(persona: Any) -> list[Any]:
    """The persona's field selectors, excluding row groups/scanlines and
    anything `derived_only` - the same filter the F1 derivations already use,
    so a field vision could never legitimately supply is never asked for."""
    out: list[Any] = []
    for sel in getattr(persona, "field_selectors", None) or ():
        name = getattr(sel, "field", None)
        if not name or name in DERIVED_ONLY:
            continue
        out.append(sel)
    return out


def field_names_for_persona(persona: Any) -> list[str]:
    """This vendor's own declared scalar field list, in persona order."""
    return [sel.field for sel in _scalar_selectors(persona)]


def hints_for_persona(persona: Any) -> dict[str, str]:
    """`{field_name: one descriptive sentence fragment}` - locations only,
    never decisions, and never the vendor's business logic (`adjust` ops stay
    in code, same reasoning as `gemini_persona_hints.build_hints`). A field
    with nothing describable (no anchor, no known region, no describable
    shape) is simply absent, not padded with a vague placeholder - a vague
    hint is worse than none."""
    hints: dict[str, str] = {}
    for sel in _scalar_selectors(persona):
        parts: list[str] = []
        if anchor := getattr(sel, "anchor", None):
            parts.append(f'labelled "{anchor}"')
        if region_prose := _REGION_PROSE.get(getattr(sel, "region", "") or ""):
            parts.append(region_prose)
        if shape := _shape_prose(getattr(sel, "pattern", None)):
            parts.append(shape)
        if parts:
            hints[sel.field] = ", ".join(parts)
    return hints


# -- row-group (table) derivation --------------------------------------------
#
# Same reuse principle as the scalar functions above: a `row_group` selector
# already declares everything a vision table request needs (`table_anchor`
# for identity, `columns` for names + expected per-column shape,
# `column_headers` for labels) - there is no separate, hand-authored "vision
# table config" anywhere in a persona. See the docintel session plan
# ("Gemini Vision Support for Line-Item / Table Extraction") for why a second,
# manually-written spec was rejected: it would duplicate what the selector
# already says, and the two copies could silently drift apart.


def _row_group_selectors(persona: Any) -> list[Any]:
    """The persona's row-group (table) selectors - the mirror of
    `_scalar_selectors`, filtering to selectors that declare a `row_group`
    name rather than a scalar `field`."""
    out: list[Any] = []
    for sel in getattr(persona, "field_selectors", None) or ():
        if getattr(sel, "row_group", None):
            out.append(sel)
    return out


def table_requests_for_persona(persona: Any) -> dict[str, list[str]]:
    """This vendor's own declared table(s), by name, with their column names
    in the persona's declared order."""
    return {sel.row_group: list(sel.columns) for sel in _row_group_selectors(persona)}


def table_hints_for_persona(persona: Any) -> dict[str, dict[str, str]]:
    """`{table_name: {column_name: one descriptive sentence fragment}}` -
    reuses the SAME `_PATTERN_PROSE` shape vocabulary the scalar hints above
    use for a column's declared pattern (`columns[col]`), plus the column's
    own header label (`column_headers[col]`) as the anchor-like description a
    human would look for. A column with nothing describable is simply absent,
    matching `hints_for_persona`'s "no vague placeholder" rule."""
    hints: dict[str, dict[str, str]] = {}
    for sel in _row_group_selectors(persona):
        column_headers = getattr(sel, "column_headers", None) or {}
        table_hints: dict[str, str] = {}
        for col, pattern in (getattr(sel, "columns", None) or {}).items():
            parts: list[str] = []
            if header := column_headers.get(col):
                parts.append(f'labelled "{header}"')
            if shape := _shape_prose(pattern):
                parts.append(shape)
            if parts:
                table_hints[col] = ", ".join(parts)
        hints[sel.row_group] = table_hints
    return hints


# -- pack-level "vision_defaults" vocabulary ---------------------------------
#
# A pack's `vision_defaults` (packs/datapack.py) lets a user declare Gemini-
# only field/table types in plain language ("text", "currency" or "$",
# "decimal", "date"...) for a document that has no persona to derive from at
# all - the 1000-unknown-vendor case. Reuses this same `_PATTERN_PROSE`
# vocabulary rather than inventing a second one, with a small alias layer for
# friendlier spellings.
VISION_TYPE_ALIASES: dict[str, str] = {"$": "currency", "money": "currency", "number": "integer"}
_PLAIN_TYPE = "text"


def recognized_vision_types() -> frozenset[str]:
    """Every type name a pack's `vision_defaults` may use: the shape
    vocabulary above, its friendly aliases, and `"text"` (no describable
    shape - the field/column is simply requested, no hint)."""
    return frozenset({*_PATTERN_PROSE, *VISION_TYPE_ALIASES, _PLAIN_TYPE})


def vision_type_prose(type_name: str) -> str | None:
    """The hint sentence for a `vision_defaults` type name, or `None` for
    `"text"` or an alias that resolves to nothing describable."""
    resolved = VISION_TYPE_ALIASES.get(type_name, type_name)
    return _PATTERN_PROSE.get(resolved)
