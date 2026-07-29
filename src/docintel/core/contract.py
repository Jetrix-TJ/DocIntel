"""The Stage 8 record: the only interface downstream systems see.

Includes the five deltas from corpus-analysis.md section 6: text_source,
document_identity, identity_basis, page_roles, and reference_list as objects.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from docintel.core.coverage import Coverage
from docintel.core.errors import ContractError
from docintel.core.models import JobContext

SCHEMA_VERSION = "1"

REQUIRED_KEYS = frozenset({
    "schema_version", "doc_type", "sender_fingerprint", "fields", "derived",
    "confidence", "reference_list", "extraction_rule_version",
    "confidence_modifiers", "possible_duplicate_of", "disposition",
    "review_flag", "regen_flag", "audit_sample", "text_source", "page_roles",
    "tags", "document_id",
    # The four structured keys. Until these existed the scorecard could not
    # assert four whole gold sections, which left the convergence loop blind to
    # F7 (scanline ground truth), F8 (arithmetic closure), F14 (surcharge
    # capture) and F19 (row groups) - it could have reached "10/10 green" while
    # extracting no line items at all.
    "line_items", "charges", "sub_account", "scanline",
    # What the persona declared against what was found. Required rather than
    # optional: a consumer that has to check whether the key exists before it can
    # ask whether extraction finished will read its absence as "fine", which is
    # the exact failure mode `core.coverage` was written to end.
    "extraction_coverage",
})

# Row groups that get their own top-level contract key. A row group the persona
# names anything else stays in `row_groups` and is not emitted: a new top-level
# key is a contract change, so it needs a deliberate edit here rather than
# appearing because someone picked a name.
_PROMOTED_ROW_GROUPS = ("line_items", "charges", "sub_account")

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
    # The two structured results a named pattern can produce. Duck-typed rather
    # than imported: `core` must not depend on `grammar`, and the attribute names
    # are the contract between them.
    #
    # A `DateResult` reaches here whenever a persona uses the `date` pattern
    # without `normalize_date_iso`, which is legal - and an unparsed date keeps
    # its raw text on purpose (F9: Centracom prints "25TH OF THE MONTH").
    # An `AccountNumber` crosses as its PRINTED form; the joinable form is a
    # separate field (`*_normalized`), because they are two different facts (F6).
    if hasattr(value, "iso") and hasattr(value, "raw"):
        return value.iso if value.iso else value.raw
    if hasattr(value, "normalized") and hasattr(value, "raw"):
        return value.raw
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
        # Completeness, beside confidence rather than inside it. A document that
        # never reached Stage 6 has no Coverage object, and the zero value says
        # `complete: false` - "nothing was assessed" must not serialize as "nothing
        # was wrong".
        "extraction_coverage": (
            ctx.coverage.as_record() if ctx.coverage is not None
            else Coverage().as_record()
        ),
        "reference_list": [
            {"value": r.value, "source_field": r.source_field,
             "page": r.page, "pattern_id": r.pattern_id}
            for r in ctx.reference_list
        ],
        # Row groups (F19), each a list of {column: value}. Column names come
        # from the persona, so they differ per sender by design - EDCO's
        # statement table has `charges`/`balance` where Veritiv's has `amount`.
        **{name: _serialize(ctx.row_groups.get(name, [])) for name in _PROMOTED_ROW_GROUPS},
        # The remittance scan line, verbatim (F7). Scoring-only: it never
        # supplies a field value, so it is deliberately NOT inside `fields`.
        "scanline": ctx.scanline,
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

    # FINDING 1: if disposition is "processed", doc_type must be a non-empty string
    if rec["disposition"] == "processed":
        if not isinstance(rec["doc_type"], str) or not rec["doc_type"]:
            raise ContractError(
                f"doc_type must be a non-empty string for processed records, got {rec['doc_type']!r}"
            )

    # Carried over from the Task A5 review, unblocked by C3's derive ops. A
    # processed record MUST carry both identity keys in `derived`.
    #
    # These two exist solely so downstream dedup works for the 3 of 10 corpus
    # documents that print no invoice number (F6). A processed record without
    # them silently starves the duplicate decision - the exact failure the delta
    # was written to prevent.
    #
    # PRESENCE is required, not a non-null value. `derive_document_identity`
    # always sets both, using None to mean "looked and could not build one",
    # which is a materially different statement from "this pipeline never
    # tried" - and it is the only one of the two a reviewer can act on. Demanding
    # a non-null value would also break the count(intaken) == count(emitted)
    # invariant, since a document whose identity cannot be built still has to be
    # emitted and routed to review.
    if rec["disposition"] == "processed":
        missing_identity = [
            key for key in ("document_identity", "identity_basis")
            if key not in rec["derived"]
        ]
        if missing_identity:
            raise ContractError(
                f"processed record is missing {missing_identity} from derived; "
                "downstream dedup needs them for the documents that print no "
                "invoice number (F6). None is a valid value, absence is not"
            )

    # FINDING 5: document_id must be a non-empty string
    if not isinstance(rec["document_id"], str) or not rec["document_id"]:
        raise ContractError(
            f"document_id must be a non-empty string, got {rec['document_id']!r}"
        )

    for bucket in ("fields", "derived"):
        for name, value in rec[bucket].items():
            if isinstance(value, float):
                raise ContractError(
                    f"{bucket}.{name} is a float; money must cross the contract as a string"
                )

    # FINDING 2: confidence values must be int/float (not bool) within [0.0, 0.99]
    for name, value in rec["confidence"].items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ContractError(
                f"confidence.{name} must be int or float, got {type(value).__name__}"
            )
        if not (0.0 <= value <= 0.99):
            raise ContractError(
                f"confidence.{name} must be in [0.0, 0.99], got {value}"
            )

    # FINDING 3: reference_list entries must have correct key set and value types
    for entry in rec["reference_list"]:
        if set(entry) != {"value", "source_field", "page", "pattern_id"}:
            raise ContractError(f"reference_list entry has wrong shape: {entry!r}")

        # Check value types
        if not isinstance(entry["value"], str):
            raise ContractError(
                f"reference_list entry value must be str, got {type(entry['value']).__name__}"
            )
        if not isinstance(entry["source_field"], str):
            raise ContractError(
                f"reference_list entry source_field must be str, got {type(entry['source_field']).__name__}"
            )
        if not isinstance(entry["pattern_id"], str):
            raise ContractError(
                f"reference_list entry pattern_id must be str, got {type(entry['pattern_id']).__name__}"
            )
        # page must be int (not bool) and >= 1
        if type(entry["page"]) is not int or isinstance(entry["page"], bool):
            raise ContractError(
                f"reference_list entry page must be int (not bool), got {type(entry['page']).__name__}"
            )
        if entry["page"] < 1:
            raise ContractError(
                f"reference_list entry page must be >= 1, got {entry['page']}"
            )

    # FINDING 4: review_flag, regen_flag, audit_sample must be genuine bool
    for flag_name in ("review_flag", "regen_flag", "audit_sample"):
        if not isinstance(rec[flag_name], bool):
            raise ContractError(
                f"{flag_name} must be bool, got {type(rec[flag_name]).__name__}"
            )

    # The three row-group keys: a list of flat mappings. Column names are the
    # persona's, so they are not constrained here - but the SHAPE is, and no
    # money may cross as a float, for the same reason `fields` may not: the F8
    # closure checks demand exact equality and float tolerance is where bugs hide.
    for key in _PROMOTED_ROW_GROUPS:
        rows = rec[key]
        if not isinstance(rows, list):
            raise ContractError(f"{key} must be a list, got {type(rows).__name__}")
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ContractError(
                    f"{key}[{i}] must be a mapping, got {type(row).__name__}"
                )
            for column, value in row.items():
                if not isinstance(column, str):
                    raise ContractError(
                        f"{key}[{i}] has a non-string column name: {column!r}"
                    )
                if isinstance(value, float):
                    raise ContractError(
                        f"{key}[{i}].{column} is a float; money must cross the "
                        "contract as a string"
                    )
                if isinstance(value, (list, dict)):
                    raise ContractError(
                        f"{key}[{i}].{column} is nested ({type(value).__name__}); a row "
                        "group is one level deep, and sub_group values are flattened "
                        "onto their row (grammar V8)"
                    )

    # Completeness. Type-checked as strictly as the flags above, because a
    # consumer's auto-approval decision reads `complete` directly: a truthy string
    # or a 0/1 int would each silently invert the meaning of `complete: false`.
    coverage = rec["extraction_coverage"]
    if not isinstance(coverage, dict):
        raise ContractError(
            f"extraction_coverage must be a mapping, got {type(coverage).__name__}"
        )
    expected = {"declared", "populated", "missing_required", "complete"}
    if set(coverage) != expected:
        raise ContractError(
            f"extraction_coverage has wrong shape: {sorted(coverage)}, "
            f"expected {sorted(expected)}"
        )
    if not isinstance(coverage["complete"], bool):
        raise ContractError(
            f"extraction_coverage.complete must be bool, got "
            f"{type(coverage['complete']).__name__}"
        )
    for count in ("declared", "populated"):
        value = coverage[count]
        if type(value) is not int or isinstance(value, bool):
            raise ContractError(
                f"extraction_coverage.{count} must be int (not bool), got "
                f"{type(value).__name__}"
            )
        if value < 0:
            raise ContractError(
                f"extraction_coverage.{count} must be >= 0, got {value}"
            )
    if coverage["populated"] > coverage["declared"]:
        raise ContractError(
            f"extraction_coverage.populated ({coverage['populated']}) exceeds "
            f"declared ({coverage['declared']})"
        )
    if not isinstance(coverage["missing_required"], list):
        raise ContractError(
            "extraction_coverage.missing_required must be a list, got "
            f"{type(coverage['missing_required']).__name__}"
        )
    for name in coverage["missing_required"]:
        if not isinstance(name, str):
            raise ContractError(
                "extraction_coverage.missing_required entries must be str, got "
                f"{type(name).__name__}"
            )
    # `complete` is derived, so a record whose flag disagrees with its own counts
    # was assembled by something other than Coverage.as_record() and cannot be
    # trusted by a consumer routing on it.
    if coverage["complete"] and (
        coverage["missing_required"] or coverage["populated"] != coverage["declared"]
    ):
        raise ContractError(
            f"extraction_coverage claims complete but reports "
            f"{coverage['populated']}/{coverage['declared']} populated and "
            f"missing {coverage['missing_required']}"
        )

    # The scan line is a raw digit run or absent. Never a number: it is a
    # transcription, and its leading zeros carry meaning to a lockbox scanner.
    if rec["scanline"] is not None and not isinstance(rec["scanline"], str):
        raise ContractError(
            f"scanline must be a string or None, got {type(rec['scanline']).__name__}"
        )
