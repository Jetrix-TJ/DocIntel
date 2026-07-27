"""The Stage 8 record: the only interface downstream systems see.

Includes the five deltas from corpus-analysis.md section 6: text_source,
document_identity, identity_basis, page_roles, and reference_list as objects.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from docintel.core.errors import ContractError
from docintel.core.models import JobContext

SCHEMA_VERSION = "1"

REQUIRED_KEYS = frozenset({
    "schema_version", "doc_type", "sender_fingerprint", "fields", "derived",
    "confidence", "reference_list", "extraction_rule_version",
    "confidence_modifiers", "possible_duplicate_of", "disposition",
    "review_flag", "regen_flag", "audit_sample", "text_source", "page_roles",
    "tags", "document_id",
})

_DISPOSITIONS = {"processed", "skipped", "dead_letter"}


def _serialize(value: Any) -> Any:
    """Decimal becomes a string so no consumer can accidentally use a float.

    Tests `Mapping`, not `dict`: ExtractedFields.values is a read-only
    MappingProxyType view (see models.py), which is a Mapping but NOT a dict.
    An isinstance(value, dict) check would silently pass the proxy through
    unserialized and leak Decimal objects into the record.
    """
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    return value


def build_record(ctx: JobContext) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "document_id": ctx.document_id,
        "doc_type": ctx.doc_type,
        "tags": list(ctx.tags),
        "sender_fingerprint": ctx.sender_fingerprint,
        "text_source": ctx.text_source,
        "page_roles": [m.role for m in ctx.page_meta],
        "fields": _serialize(ctx.extracted.values),
        "derived": _serialize(ctx.derived.values),
        "confidence": dict(ctx.confidence),
        "confidence_modifiers": list(ctx.modifiers),
        "reference_list": [
            {"value": r.value, "source_field": r.source_field,
             "page": r.page, "pattern_id": r.pattern_id}
            for r in ctx.reference_list
        ],
        "extraction_rule_version": ctx.extraction_rule_version,
        "extraction_route": ctx.extraction_route,
        "possible_duplicate_of": ctx.possible_duplicate_of,
        "disposition": ctx.disposition,
        "reason": ctx.skip_reason,
        "review_flag": ctx.review_flag,
        "regen_flag": ctx.regen_flag,
        "audit_sample": ctx.audit_sample,
        "lane": ctx.lane,
    }


def validate_record(rec: dict[str, Any]) -> None:
    missing = REQUIRED_KEYS - set(rec)
    if missing:
        raise ContractError(f"record missing required keys: {sorted(missing)}")

    if rec["disposition"] not in _DISPOSITIONS:
        raise ContractError(
            f"disposition must be one of {sorted(_DISPOSITIONS)}, got {rec['disposition']!r}"
        )

    for bucket in ("fields", "derived"):
        for name, value in rec[bucket].items():
            if isinstance(value, float):
                raise ContractError(
                    f"{bucket}.{name} is a float; money must cross the contract as a string"
                )

    for entry in rec["reference_list"]:
        if set(entry) != {"value", "source_field", "page", "pattern_id"}:
            raise ContractError(f"reference_list entry has wrong shape: {entry!r}")
