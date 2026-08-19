"""Draft a `docs/corpus/gold/*.json` fixture directly from one clean `process()`
run - a fast path with no prerequisite, unlike `docintel.evals.promote`'s
`build_gold_fixture`, which needs an already-escalated `hard_miss` correction.
A brand-new company's first document has no persona at all - it's `no_persona`,
never `hard_miss` - so that path never even applies to the case that needs a
first fixture most.

What gets auto-filled, and what stays a human's job:

- `classification` (doc_type/tags/text_source/page_count/page_roles) and every
  `fields`/`derived` value the record actually produced: OBSERVED facts about
  what the pipeline read off the page. Auto-filled, via the SAME
  `scorecard._field_value` fields-then-derived lookup `assertions_for` itself
  uses, so what's written here is read back identically.
- `line_items`/`charges`/`sub_account`/`reference_list`: copied verbatim from
  the record - richer than `promote-correction`'s snapshot path, which drops
  all four structured blocks entirely (see `evals.promote`'s own docstring).
- `expected_routing` (`review_flag`/`regen_flag`/`lane`) is deliberately NEVER
  auto-filled from the record's own routing decision, even though the full
  pipeline already ran and that decision is sitting right there. A gold
  fixture exists to check whether the pipeline routes correctly; copying its
  own answer back at itself would make that assertion trivially, permanently
  true - exactly the failure a hand-labelled ground truth exists to prevent.
  The record's own decision is kept separately, under
  `_draft_pipeline_observed` (a key `scorecard.py` never reads), so whoever
  fills this in has something to check against rather than starting blind.
- `labelled_by`, `teaches`, `notes`, `reference_list_complete`,
  `line_items_complete`: always a placeholder - see `PLACEHOLDER`.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from docintel.scorecard import CHECKED_DERIVED, CHECKED_FIELDS, MONEY_FIELDS, _field_value

PLACEHOLDER = "TODO-human-must-set"


def _gold_value(name: str, value: Any) -> Any:
    """A money field's value, as a hand-authored gold fixture would type it:
    a bare JSON number, not the string a record's own `Decimal` serializes to
    (`contract.py::_serialize`). `scorecard.py`'s own scoring tolerates either
    form (`Decimal(str(...))` on both sides), but `docs/corpus/validate_gold.py`
    - the separate, dependency-free self-check every existing gold fixture is
    also checked against - does a plain `==` for at least one check, and every
    hand-authored fixture already uses a bare float for these fields, so this
    keeps a drafted fixture indistinguishable from a hand-authored one rather
    than introducing a second, technically-equivalent-but-different convention.
    """
    if name not in MONEY_FIELDS or not isinstance(value, str):
        return value
    try:
        return float(Decimal(value))
    except InvalidOperation:
        return value


def draft_gold_fixture(record: dict[str, Any], gold_id: str, source_file: str) -> dict[str, Any]:
    fields = {name: _gold_value(name, _field_value(record, name)) for name in CHECKED_FIELDS}
    fields = {name: value for name, value in fields.items() if value is not None}

    derived_source = record.get("derived") or {}
    derived = {
        name: _gold_value(name, derived_source[name])
        for name in CHECKED_DERIVED if name in derived_source
    }

    page_roles = record.get("page_roles") or []
    fixture: dict[str, Any] = {
        "gold_id": gold_id,
        "source_file": source_file,
        "pack": (record.get("sender_fingerprint") or "unknown|unknown").split("|", 1)[0],
        "labelled_by": PLACEHOLDER,
        "teaches": [],
        "notes": "TODO: describe what this document teaches, and why it's in the corpus.",
        "classification": {
            "doc_type": record.get("doc_type"),
            "tags": list(record.get("tags") or []),
            "text_source": record.get("text_source"),
            "page_count": len(page_roles),
            "page_roles": page_roles,
        },
        "fields": fields,
        "derived": derived,
        "expected_routing": {
            "review_flag": PLACEHOLDER,
            "regen_flag": PLACEHOLDER,
            "lane": PLACEHOLDER,
        },
        "_draft_pipeline_observed": {
            "review_flag": record.get("review_flag"),
            "regen_flag": record.get("regen_flag"),
            "lane": record.get("lane"),
        },
    }

    line_items = record.get("line_items")
    if line_items:
        fixture["line_items"] = line_items
        fixture["line_items_complete"] = False

    charges = record.get("charges")
    if charges:
        fixture["charges"] = charges

    sub_account = record.get("sub_account")
    if sub_account:
        fixture["sub_account"] = sub_account

    scanline = record.get("scanline")
    if scanline:
        fixture["scanline"] = {"raw": scanline}

    reference_list = record.get("reference_list")
    if reference_list:
        fixture["reference_list"] = reference_list
        fixture["reference_list_complete"] = False

    return fixture
