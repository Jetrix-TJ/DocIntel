"""What a vision model is allowed to say, and what happens to the rest.

**This file is to the vision path what `grammar/validator.py` is to the persona
path: the security boundary.** The persona path's rule is "the agent writes data,
never code", enforced by V1-V13. The vision path needs its own, because a
`VisionResult` is not inert - Stage 5b writes its `fields` into `ExtractedFields`
and its `irregularities` into the document's modifier and tag lists, and Stage 7
routes lanes off those lists. An unfiltered string from a model would therefore be
able to move a document between queues.

Three rules, each closing a specific hole:

1. **Only the fields that were asked for.** A model that returns
   `amount_payable` would hit `ExtractedFields.set`'s derived-only guard (V10) and
   crash the stage; one that returns `notes` would put a key in the emitted record
   that no consumer knows about. `field_names` is the allowlist, and DERIVED_ONLY
   is rejected a second time in case a caller ever passes one.

2. **Only irregularities a camera could actually see.** `VISION_OBSERVABLE` is a
   deliberately tiny subset of the section 5 enum. Handwriting and skew are
   properties of the image, so a vision model is the *best* available witness. The
   arithmetic modifiers (`arith_*`, `scanline_mismatch`, `filename_disagree`) are
   computed by ops that do real comparisons, and letting a model assert them would
   replace arithmetic with an opinion. `flattened_annotations` is excluded for a
   sharper reason: Stage 6 detects it structurally from the PDF's annotation
   count, and it is one of the two FORCING modifiers - so admitting it here would
   hand a model the power to force every document to human review.

   Note what that exclusion buys: **neither surviving name is in
   `s7_gate.FORCING_MODIFIERS`**, so no vision response can route a document to
   the review lane on its own. It can only lower confidence, and the gate decides
   what low confidence means.

3. **Confidence is clamped, not trusted.** JSON Schema cannot express
   `minimum`/`maximum` (the API's supported-keyword subset omits them), so the
   bound is enforced here. `VISION_CEILING` is applied separately from the global
   `CEILING` because a model's self-reported confidence is not evidence the way a
   matched selector's confidence is: a vision-only read must never itself clear an
   auto-approve threshold.

`sanitize` drops rather than raises. A model that returns one bad key alongside
nine good values should give us the nine - the alternative is throwing away a
usable extraction over a field nobody asked for. What it must never do is pass
the bad key through.
"""

from __future__ import annotations

from docintel.adapters.vision.port import VisionResult
from docintel.core.confidence import MODIFIERS
from docintel.core.models import DERIVED_ONLY

# Section 5 modifiers a vision model is a competent witness for. See rule 2.
VISION_OBSERVABLE: frozenset[str] = frozenset({
    "handwriting_detected",
    "high_skew",
})

# Confidence assigned to a value the model returned without one. Matches
# `FakeVision` and `s5b`'s own default: a vision read is a starting point, not a
# strong one.
DEFAULT_CONFIDENCE = 0.50

# A model's self-reported confidence is not evidence the way a matched
# selector's confidence is - a selector confirms it found the label AND the
# shape it expected; a vision model can be confidently wrong about a value it
# invented. Capped below the lowest threshold ANY shipped pack configures
# (0.75-0.95, see selector-grammar.md section 5) so a vision-only read can
# never itself clear the auto-approve bar - it can only ever land a document
# in medium/review, same as any other soft-miss modifier.
VISION_CEILING = 0.70

# The LOWER clamp, and the other half of rule 3.
#
# `s7_gate` routes a document to the `low` lane when a majority share of its
# fields score under `VERY_LOW_FLOOR`, and the `low` lane sets `regen_flag` - a
# request to regenerate this vendor's persona. A model reporting 0.01 on the
# fields it returned would therefore reach both the lane and the rule lifecycle,
# which is exactly the power rule 2 spends `VISION_OBSERVABLE` to deny.
#
# Kept numerically equal to the gate's floor, not lower. Deliberately NOT imported
# from `s7_gate`: an adapter must not depend on a pipeline stage. The link is
# pinned by a test instead (`test_vision_policy.py`), the same way rule 2's names
# are pinned against `MODIFIERS`.
#
# This floor costs the model nothing it should have. `VISION_FLOOR` is below every
# threshold either pack sets (0.75-0.95), so a floored field still falls short of
# its threshold and still sends the document to a human. What the model loses is
# only the claim that the PERSONA is broken - and an illegible image is not
# evidence about a selector.
VISION_FLOOR = 0.50

_CEILING = float(VISION_CEILING)


def _clean_value(value: object) -> str | None:
    """A usable transcription, or None. Whitespace-only is absence, not a value."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _clean_confidence(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return min(_CEILING, max(VISION_FLOOR, float(value)))


def _clean_cell(value: object) -> str:
    """A row cell, coerced to a string. Unlike a scalar field, a missing or
    unreadable CELL is a legitimate row value (an empty invoice column), not
    absence of the field itself - so this returns `""` rather than dropping
    the key, keeping every declared column present on every row."""
    return value.strip() if isinstance(value, str) else ""


def _clean_table(rows: object, columns: list[str]) -> list[dict[str, str]]:
    """Rule 1's allowlist, one level down: only declared columns survive in
    each row, and a row that is not even a mapping is dropped rather than
    raised - the same 'give us the nine good values' discipline `sanitize`
    already applies to fields, applied to rows instead of field names."""
    if not isinstance(rows, list):
        return []
    cleaned: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cleaned.append({col: _clean_cell(row.get(col)) for col in columns})
    return cleaned


def sanitize(
    result: VisionResult,
    field_names: list[str],
    table_requests: dict[str, list[str]] | None = None,
) -> VisionResult:
    """The subset of `result` the pipeline is allowed to act on."""
    allowed = {n for n in field_names if n not in DERIVED_ONLY}

    fields: dict[str, str] = {}
    for name in field_names:
        if name not in allowed:
            continue
        cleaned = _clean_value(result.fields.get(name))
        if cleaned is not None:
            fields[name] = cleaned

    confidence: dict[str, float] = {}
    for name in fields:
        scored = _clean_confidence(result.confidence.get(name))
        confidence[name] = DEFAULT_CONFIDENCE if scored is None else scored

    irregularities = [
        flag
        for flag in dict.fromkeys(result.irregularities)  # de-dupe, keep order
        if isinstance(flag, str) and flag in VISION_OBSERVABLE
    ]

    # Only a table that was actually asked for may pass - same allowlist
    # reasoning as rule 1 for scalar fields, applied to table names.
    row_groups: dict[str, list[dict[str, str]]] = {}
    for table_name, columns in (table_requests or {}).items():
        row_groups[table_name] = _clean_table(result.row_groups.get(table_name), columns)

    return VisionResult(
        fields=fields, confidence=confidence, irregularities=irregularities,
        row_groups=row_groups,
    )


# Sanity check at import time rather than in a test: the whole argument for rule 2
# is that these names are real section 5 modifiers, so a typo here would silently
# make an observation inert (Stage 5b would file it as a tag) instead of applying
# its penalty.
_unknown = VISION_OBSERVABLE - set(MODIFIERS)
if _unknown:  # pragma: no cover - a coding error, not a runtime condition
    raise ValueError(f"VISION_OBSERVABLE names are not section 5 modifiers: {_unknown}")
