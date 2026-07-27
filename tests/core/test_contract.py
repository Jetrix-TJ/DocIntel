from decimal import Decimal
import pytest
from docintel.core.contract import (
    REQUIRED_KEYS, SCHEMA_VERSION, build_record, validate_record,
)
from docintel.core.errors import ContractError
from docintel.core.models import PageMeta, ReferenceHit, new_context


def _ctx():
    ctx = new_context(document_id="d1", source_path="/tmp/a.pdf")
    ctx.doc_type = "telecom_bill"
    ctx.sender_fingerprint = "centracom|centracom"
    ctx.text_source = "native"
    ctx.extraction_rule_version = "v1"
    ctx.page_meta = (PageMeta(1, 1209, 15, 0, "primary"),)
    ctx.extracted.set("total_printed", Decimal("33876.40"), 0.98)
    ctx.derived.set("amount_payable", Decimal("13752.60"))
    ctx.derived.set("payable_basis", "current_charges")
    ctx.derived.set("document_identity", "0384043574|2026-01-01")
    ctx.derived.set("identity_basis", "account_period")
    ctx.confidence["total_printed"] = 0.98
    ctx.reference_list.append(ReferenceHit("0384043574", "Account Number", 1, "account"))
    return ctx


def test_record_has_every_required_key():
    rec = build_record(_ctx())
    assert REQUIRED_KEYS <= set(rec)
    validate_record(rec)


def test_schema_version_is_stamped():
    assert build_record(_ctx())["schema_version"] == SCHEMA_VERSION


def test_money_serializes_as_string_not_float():
    """Decimal must survive the contract boundary without float drift."""
    rec = build_record(_ctx())
    assert rec["fields"]["total_printed"] == "33876.40"
    assert rec["derived"]["amount_payable"] == "13752.60"


def test_reference_list_entries_are_objects_with_provenance():
    rec = build_record(_ctx())
    assert rec["reference_list"] == [
        {"value": "0384043574", "source_field": "Account Number",
         "page": 1, "pattern_id": "account"}
    ]


def test_text_source_and_page_roles_are_present():
    rec = build_record(_ctx())
    assert rec["text_source"] == "native"
    assert rec["page_roles"] == ["primary"]


def test_skipped_document_still_produces_a_valid_record():
    """Spec Stage 2: never silently drop."""
    ctx = new_context(document_id="d2", source_path="/tmp/b.png")
    ctx.disposition = "skipped"
    ctx.skip_reason = "file type not in allowlist"
    rec = build_record(ctx)
    validate_record(rec)
    assert rec["disposition"] == "skipped"
    assert rec["reason"] == "file type not in allowlist"


def test_dead_letter_still_produces_a_valid_record():
    ctx = new_context(document_id="d3", source_path="/tmp/c.pdf")
    ctx.disposition = "dead_letter"
    ctx.skip_reason = "corrupt PDF"
    rec = build_record(ctx)
    validate_record(rec)
    assert rec["disposition"] == "dead_letter"


def test_validate_rejects_missing_key():
    rec = build_record(_ctx())
    del rec["disposition"]
    with pytest.raises(ContractError, match="disposition"):
        validate_record(rec)


def test_validate_rejects_unknown_disposition():
    rec = build_record(_ctx())
    rec["disposition"] = "maybe"
    with pytest.raises(ContractError, match="disposition"):
        validate_record(rec)


def test_validate_rejects_float_money():
    rec = build_record(_ctx())
    rec["fields"]["total_printed"] = 33876.40
    with pytest.raises(ContractError, match="string"):
        validate_record(rec)
