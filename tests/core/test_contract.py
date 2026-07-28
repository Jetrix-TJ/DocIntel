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
    assert rec["reason"] == "corrupt PDF"


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


# Fix Round 1: Tightened validation tests


def test_finding_1_rejects_null_doc_type_on_processed():
    """FINDING 1: processed records require non-empty doc_type."""
    rec = build_record(_ctx())
    rec["doc_type"] = None
    with pytest.raises(ContractError, match="doc_type"):
        validate_record(rec)


def test_finding_1_allows_null_doc_type_on_skipped():
    """FINDING 1: skipped records can have null doc_type."""
    ctx = new_context(document_id="d4", source_path="/tmp/d.pdf")
    ctx.disposition = "skipped"
    ctx.skip_reason = "reason"
    rec = build_record(ctx)
    assert rec["doc_type"] is None
    validate_record(rec)


def test_finding_1_allows_null_doc_type_on_dead_letter():
    """FINDING 1: dead_letter records can have null doc_type."""
    ctx = new_context(document_id="d5", source_path="/tmp/e.pdf")
    ctx.disposition = "dead_letter"
    ctx.skip_reason = "reason"
    rec = build_record(ctx)
    assert rec["doc_type"] is None
    validate_record(rec)


def test_finding_1_rejects_empty_doc_type_on_processed():
    """FINDING 1: processed records reject empty string doc_type."""
    rec = build_record(_ctx())
    rec["doc_type"] = ""
    with pytest.raises(ContractError, match="doc_type"):
        validate_record(rec)


def test_finding_2_rejects_bool_in_confidence():
    """FINDING 2: confidence values cannot be bool."""
    rec = build_record(_ctx())
    rec["confidence"]["total_printed"] = True
    with pytest.raises(ContractError, match="confidence"):
        validate_record(rec)


def test_finding_2_rejects_confidence_below_zero():
    """FINDING 2: confidence values must be >= 0.0."""
    rec = build_record(_ctx())
    rec["confidence"]["total_printed"] = -0.01
    with pytest.raises(ContractError, match="confidence"):
        validate_record(rec)


def test_finding_2_rejects_confidence_above_0_99():
    """FINDING 2: confidence values must be <= 0.99."""
    rec = build_record(_ctx())
    rec["confidence"]["total_printed"] = 1.0
    with pytest.raises(ContractError, match="confidence"):
        validate_record(rec)


def test_finding_2_allows_empty_confidence():
    """FINDING 2: empty confidence dict is legal."""
    rec = build_record(_ctx())
    rec["confidence"] = {}
    validate_record(rec)


def test_finding_2_allows_exactly_0_0():
    """FINDING 2: confidence can be exactly 0.0."""
    rec = build_record(_ctx())
    rec["confidence"]["test"] = 0.0
    validate_record(rec)


def test_finding_2_allows_exactly_0_99():
    """FINDING 2: confidence can be exactly 0.99."""
    rec = build_record(_ctx())
    rec["confidence"]["test"] = 0.99
    validate_record(rec)


def test_finding_3_rejects_non_string_value():
    """FINDING 3: reference_list value must be str."""
    rec = build_record(_ctx())
    rec["reference_list"][0]["value"] = 123
    with pytest.raises(ContractError, match="value"):
        validate_record(rec)


def test_finding_3_rejects_non_string_source_field():
    """FINDING 3: reference_list source_field must be str."""
    rec = build_record(_ctx())
    rec["reference_list"][0]["source_field"] = 123
    with pytest.raises(ContractError, match="source_field"):
        validate_record(rec)


def test_finding_3_rejects_non_string_pattern_id():
    """FINDING 3: reference_list pattern_id must be str."""
    rec = build_record(_ctx())
    rec["reference_list"][0]["pattern_id"] = 123
    with pytest.raises(ContractError, match="pattern_id"):
        validate_record(rec)


def test_finding_3_rejects_bool_page():
    """FINDING 3: reference_list page must be int, not bool."""
    rec = build_record(_ctx())
    rec["reference_list"][0]["page"] = True
    with pytest.raises(ContractError, match="page"):
        validate_record(rec)


def test_finding_3_rejects_page_below_1():
    """FINDING 3: reference_list page must be >= 1."""
    rec = build_record(_ctx())
    rec["reference_list"][0]["page"] = 0
    with pytest.raises(ContractError, match="page"):
        validate_record(rec)


def test_finding_3_allows_page_1():
    """FINDING 3: reference_list page=1 validates."""
    rec = build_record(_ctx())
    rec["reference_list"][0]["page"] = 1
    validate_record(rec)


def test_finding_4_rejects_non_bool_review_flag():
    """FINDING 4: review_flag must be bool."""
    rec = build_record(_ctx())
    rec["review_flag"] = 1
    with pytest.raises(ContractError, match="review_flag"):
        validate_record(rec)


def test_finding_4_rejects_non_bool_regen_flag():
    """FINDING 4: regen_flag must be bool."""
    rec = build_record(_ctx())
    rec["regen_flag"] = "true"
    with pytest.raises(ContractError, match="regen_flag"):
        validate_record(rec)


def test_finding_4_rejects_non_bool_audit_sample():
    """FINDING 4: audit_sample must be bool."""
    rec = build_record(_ctx())
    rec["audit_sample"] = None
    with pytest.raises(ContractError, match="audit_sample"):
        validate_record(rec)


def test_finding_5_rejects_empty_document_id():
    """FINDING 5: document_id must be non-empty string."""
    rec = build_record(_ctx())
    rec["document_id"] = ""
    with pytest.raises(ContractError, match="document_id"):
        validate_record(rec)


def test_finding_5_rejects_non_string_document_id():
    """FINDING 5: document_id must be string."""
    rec = build_record(_ctx())
    rec["document_id"] = 123
    with pytest.raises(ContractError, match="document_id"):
        validate_record(rec)


# ==========================================================================
# The four structured keys (C2b). Until these existed the scorecard could not
# assert four whole gold sections, leaving the loop blind to F7, F8, F14 and
# F19 — it could have reached "10/10 green" while extracting no line items.
# ==========================================================================


def _structured_ctx():
    ctx = _ctx()
    ctx.row_groups["line_items"] = [
        {"description": "BALANCE FORWARD", "balance": Decimal("298.34")},
        {"description": "CANCEL SERVICE APR 08", "charges": Decimal("69.62")},
    ]
    ctx.row_groups["charges"] = [
        {"label": "FUEL SURCHARGE", "amount": Decimal("1218.04")},
    ]
    ctx.row_groups["sub_account"] = [
        {"id": "1 - 22335", "name": "SHEARER'S FOODS CANADA R/O"},
    ]
    ctx.scanline = "25600770871000367962"
    return ctx


def test_the_four_structured_keys_are_required():
    assert {"line_items", "charges", "sub_account", "scanline"} <= REQUIRED_KEYS


def test_row_groups_are_emitted_under_their_own_keys():
    rec = build_record(_structured_ctx())
    validate_record(rec)
    assert rec["line_items"][0]["description"] == "BALANCE FORWARD"
    assert rec["charges"] == [{"label": "FUEL SURCHARGE", "amount": "1218.04"}]
    assert rec["sub_account"][0]["id"] == "1 - 22335"


def test_row_group_money_serializes_as_string_not_float():
    """F8's closure checks demand exact equality; a float is where that rots."""
    rec = build_record(_structured_ctx())
    assert rec["line_items"][0]["balance"] == "298.34"
    assert rec["line_items"][1]["charges"] == "69.62"


def test_the_scanline_crosses_as_a_raw_string():
    """Leading zeros carry meaning to a lockbox scanner, so never a number."""
    rec = build_record(_structured_ctx())
    assert rec["scanline"] == "25600770871000367962"


def test_absent_row_groups_are_empty_lists_not_null():
    """A consumer iterating line_items must never have to null-check first."""
    rec = build_record(_ctx())
    validate_record(rec)
    assert rec["line_items"] == []
    assert rec["charges"] == []
    assert rec["sub_account"] == []
    assert rec["scanline"] is None


def test_an_unpromoted_row_group_is_not_emitted():
    """A new top-level key is a contract change, not something a persona can
    create by picking a name."""
    ctx = _ctx()
    ctx.row_groups["aging_buckets"] = [{"age": "30 DAYS", "amount": Decimal("0.00")}]
    rec = build_record(ctx)
    validate_record(rec)
    assert "aging_buckets" not in rec


def test_validate_rejects_a_float_in_a_row_group():
    rec = build_record(_structured_ctx())
    rec["line_items"][0]["balance"] = 298.34
    with pytest.raises(ContractError, match="float"):
        validate_record(rec)


def test_validate_rejects_a_nested_value_in_a_row_group():
    """A row group is one level deep; sub_group values flatten onto the row (V8)."""
    rec = build_record(_structured_ctx())
    rec["line_items"][0]["nested"] = [{"deeper": 1}]
    with pytest.raises(ContractError, match="nested"):
        validate_record(rec)


def test_validate_rejects_a_non_list_row_group():
    rec = build_record(_structured_ctx())
    rec["charges"] = {"label": "FUEL"}
    with pytest.raises(ContractError, match="must be a list"):
        validate_record(rec)


def test_validate_rejects_a_non_mapping_row():
    rec = build_record(_structured_ctx())
    rec["charges"] = ["FUEL SURCHARGE"]
    with pytest.raises(ContractError, match="must be a mapping"):
        validate_record(rec)


def test_validate_rejects_a_numeric_scanline():
    rec = build_record(_structured_ctx())
    rec["scanline"] = 25600770871000367962
    with pytest.raises(ContractError, match="scanline"):
        validate_record(rec)


# ==========================================================================
# Identity keys (C3). Carried over from the Task A5 review: it could not be
# enforced during Part A because no derive op produced these values yet.
# ==========================================================================


def test_a_processed_record_must_carry_both_identity_keys():
    """They exist solely so downstream dedup works for the 3 of 10 corpus
    documents that print no invoice number (F6). A processed record without them
    silently starves the duplicate decision."""
    rec = build_record(_ctx())
    del rec["derived"]["document_identity"]
    with pytest.raises(ContractError, match="document_identity"):
        validate_record(rec)


def test_a_processed_record_missing_only_identity_basis_is_also_rejected():
    rec = build_record(_ctx())
    del rec["derived"]["identity_basis"]
    with pytest.raises(ContractError, match="identity_basis"):
        validate_record(rec)


def test_a_null_identity_is_valid_because_absence_and_None_differ():
    """None means "we looked and could not build one" — materially different
    from "this pipeline never tried", and the only one of the two a reviewer can
    act on. Requiring a non-null value would also break the
    count(intaken) == count(emitted) invariant, since a document whose identity
    cannot be built still has to be emitted and routed to review."""
    ctx = _ctx()
    ctx.derived.set("document_identity", None)
    ctx.derived.set("identity_basis", None)
    rec = build_record(ctx)
    validate_record(rec)
    assert rec["derived"]["document_identity"] is None


def test_a_skipped_record_needs_no_identity():
    """Nothing was extracted, so there is nothing to dedup against."""
    ctx = new_context(document_id="d1", source_path="/tmp/a.pdf")
    ctx.disposition = "skipped"
    ctx.skip_reason = "not_an_invoice"
    rec = build_record(ctx)
    validate_record(rec)


def test_a_dead_letter_record_needs_no_identity():
    ctx = new_context(document_id="d1", source_path="/tmp/a.pdf")
    ctx.disposition = "dead_letter"
    rec = build_record(ctx)
    validate_record(rec)
