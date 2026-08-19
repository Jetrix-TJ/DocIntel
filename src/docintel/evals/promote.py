"""Turn one accepted `Correction` into a real `docs/corpus/gold/*.json` fixture.

Pure, file-system-free logic lives here so it's testable without touching
`docs/corpus/`; `docintel promote-correction` (cli.py) does the actual file
I/O (copying the retained PDF, writing the JSON, calling `mark_promoted`).

Promotion is a human-run command, not automatic - see `docintel.evals.
corrections`'s own docstring for why: `scorecard.py` never writes to the
gold set it scores against, and a silent auto-promotion pipeline would let
one reviewer's mistake corrupt that ground truth.
"""

from __future__ import annotations

from typing import Any

from docintel.evals.corrections import Correction


def build_gold_fixture(correction: Correction, gold_id: str, source_file: str) -> dict[str, Any]:
    """Assemble the gold JSON `scorecard.assertions_for`/`validate_gold.py`
    expect. `fields` is the snapshot's extracted values with `corrected_fields`
    merged on top - a correction only ever overrides what a human actually
    typed something different for, never invents fields nobody looked at.

    `expected_routing.lane` is deliberately left `None`: a hard-miss escalation
    (the only source of a `record_snapshot` today) always sets `review_flag`
    and never `regen_flag` (s5c_agent.py), but `lane` isn't decided until
    Stage 7, which hasn't run yet at the moment the snapshot was taken - a
    human must fill this in after checking the real pipeline output, which is
    exactly why this whole command prints a reminder rather than being silent
    about the gap.
    """
    snapshot = correction.original_record
    classification = snapshot.get("classification") or {}
    fields = {**(snapshot.get("fields") or {}), **correction.corrected_fields}
    sender_fingerprint = snapshot.get("sender_fingerprint") or "unknown|unknown"
    return {
        "gold_id": gold_id,
        "source_file": source_file,
        "pack": sender_fingerprint.split("|", 1)[0],
        "labelled_by": correction.corrected_by,
        "teaches": ["correction-flywheel"],
        "classification": {
            "doc_type": classification.get("doc_type"),
            "tags": classification.get("tags", []),
            "text_source": classification.get("text_source", "native"),
            "page_count": classification.get("page_count", 0),
            "page_roles": classification.get("page_roles", []),
        },
        "fields": fields,
        "derived": snapshot.get("derived") or {},
        "expected_routing": {
            "review_flag": True,
            "regen_flag": False,
            "lane": None,
        },
    }


def corrected_field_diff(correction: Correction) -> dict[str, tuple[Any, Any]]:
    """`{field: (original, corrected)}` for exactly the fields a human typed
    a different value for. Everything else in the promoted fixture is only
    as trustworthy as "a reviewer looked at this and didn't object" - not
    independently verified the way an edited field is."""
    original_fields = correction.original_record.get("fields") or {}
    return {
        name: (original_fields.get(name), value)
        for name, value in correction.corrected_fields.items()
    }
