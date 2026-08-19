"""`draft_gold_fixture` in isolation - no filesystem, no CLI, just: does one
clean `process()` record turn into a gold JSON that round-trips through
`scorecard.assertions_for()` and `validate_gold.py`'s structural checks, the
same discipline `tests/evals/test_promote.py` already applies to
`build_gold_fixture`.
"""

from __future__ import annotations

import importlib.util
import os
import sys

from docintel.evals.draft_gold import PLACEHOLDER, draft_gold_fixture
from docintel.scorecard import assertions_for


def _load_validate_gold():
    path = os.path.join("docs", "corpus", "validate_gold.py")
    spec = importlib.util.spec_from_file_location("validate_gold", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("validate_gold", module)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _record(**over):
    base = {
        "document_id": "d1",
        "doc_type": "standard_invoice",
        "tags": ["foreign_currency"],
        "sender_fingerprint": "acme|acme_invoicing",
        "text_source": "native",
        "page_roles": ["primary"],
        "fields": {"vendor_name": "Acme Corp", "invoice_number": "123", "total_printed": "640.50"},
        "derived": {"document_identity": "123", "identity_basis": "invoice_number", "amount_payable": "640.50"},
        "review_flag": False,
        "regen_flag": False,
        "lane": "high",
        "reference_list": [{"value": "123", "source_field": "Invoice #", "page": 1, "pattern_id": "invoice_no"}],
        "line_items": [{"description": "widget", "quantity": 1, "unit_price": "640.50", "amount": "640.50"}],
        "charges": [],
        "sub_account": [],
        "scanline": None,
    }
    base.update(over)
    return base


def test_money_fields_are_written_as_bare_floats_not_the_records_own_serialized_strings():
    """`contract.py::_serialize` turns every Decimal into a string ("640.50")
    on the real record - a hand-authored gold fixture always uses a bare JSON
    number instead, and `docs/corpus/validate_gold.py` does a plain `==` for
    at least one check, so a string here would silently break it."""
    fixture = draft_gold_fixture(_record(), gold_id="g1", source_file="g1.pdf")
    assert fixture["fields"]["total_printed"] == 640.50
    assert isinstance(fixture["fields"]["total_printed"], float)
    assert fixture["derived"]["amount_payable"] == 640.50


def test_non_money_fields_are_left_exactly_as_extracted():
    fixture = draft_gold_fixture(_record(), gold_id="g1", source_file="g1.pdf")
    assert fixture["fields"]["vendor_name"] == "Acme Corp"
    assert fixture["fields"]["invoice_number"] == "123"
    assert fixture["derived"]["identity_basis"] == "invoice_number"


def test_fields_absent_from_the_record_are_simply_omitted_not_null():
    fixture = draft_gold_fixture(_record(), gold_id="g1", source_file="g1.pdf")
    assert "due_date" not in fixture["fields"]


def test_classification_is_assembled_from_the_records_flat_keys():
    fixture = draft_gold_fixture(_record(), gold_id="g1", source_file="g1.pdf")
    assert fixture["classification"] == {
        "doc_type": "standard_invoice",
        "tags": ["foreign_currency"],
        "text_source": "native",
        "page_count": 1,
        "page_roles": ["primary"],
    }


def test_pack_is_derived_from_the_sender_fingerprint():
    fixture = draft_gold_fixture(_record(), gold_id="g1", source_file="g1.pdf")
    assert fixture["pack"] == "acme"


def test_expected_routing_is_never_auto_filled_from_the_records_own_decision():
    """The whole point of a gold fixture is an independent answer - copying
    the pipeline's own routing decision back at itself would make this
    assertion trivially, permanently true."""
    fixture = draft_gold_fixture(_record(review_flag=True, regen_flag=False, lane="review"), gold_id="g1", source_file="g1.pdf")
    assert fixture["expected_routing"] == {
        "review_flag": PLACEHOLDER, "regen_flag": PLACEHOLDER, "lane": PLACEHOLDER,
    }


def test_the_records_own_routing_decision_is_kept_for_reference_only():
    fixture = draft_gold_fixture(_record(review_flag=True, regen_flag=False, lane="review"), gold_id="g1", source_file="g1.pdf")
    assert fixture["_draft_pipeline_observed"] == {
        "review_flag": True, "regen_flag": False, "lane": "review",
    }


def test_line_items_and_reference_list_are_copied_verbatim_with_a_completeness_placeholder():
    fixture = draft_gold_fixture(_record(), gold_id="g1", source_file="g1.pdf")
    assert fixture["line_items"] == _record()["line_items"]
    assert fixture["line_items_complete"] is False
    assert fixture["reference_list"] == _record()["reference_list"]
    assert fixture["reference_list_complete"] is False


def test_empty_structured_blocks_are_omitted_rather_than_written_as_empty_lists():
    fixture = draft_gold_fixture(_record(), gold_id="g1", source_file="g1.pdf")
    assert "charges" not in fixture
    assert "sub_account" not in fixture
    assert "scanline" not in fixture


def test_scanline_is_wrapped_in_the_gold_files_own_raw_key_shape():
    fixture = draft_gold_fixture(_record(scanline="123456789"), gold_id="g1", source_file="g1.pdf")
    assert fixture["scanline"] == {"raw": "123456789"}


def test_labelled_by_teaches_and_notes_are_always_placeholders():
    fixture = draft_gold_fixture(_record(), gold_id="g1", source_file="g1.pdf")
    assert fixture["labelled_by"] == PLACEHOLDER
    assert fixture["teaches"] == []
    assert "TODO" in fixture["notes"]


def test_the_gold_fixture_survives_scorecard_assertions_for_without_a_key_error():
    """The direct proof this is real, not just JSON-shaped: the exact function
    `replay-gold` calls on every gold file must not crash on a drafted one."""
    fixture = draft_gold_fixture(_record(), gold_id="g1", source_file="g1.pdf")
    fixture["expected_routing"] = {"review_flag": False, "regen_flag": False, "lane": "high"}
    assertions = assertions_for(fixture)
    assert any(a.name == "fields.vendor_name" for a in assertions)
    assert any(a.name == "doc_type" for a in assertions)


def test_the_gold_fixture_passes_validate_golds_structural_checks_once_filled_in():
    validate_gold = _load_validate_gold()
    fixture = draft_gold_fixture(_record(), gold_id="g1", source_file="g1.pdf")
    fixture["expected_routing"] = {"review_flag": False, "regen_flag": False, "lane": "high"}
    report = validate_gold.Report()
    validate_gold.check(fixture, report)
    assert report.failures == []
