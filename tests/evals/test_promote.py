"""`build_gold_fixture`/`corrected_field_diff` in isolation - no filesystem, no
CLI, just: does a `Correction` turn into a gold JSON that round-trips through
`scorecard.assertions_for()` and `validate_gold.py`'s structural checks.
"""

from __future__ import annotations

import importlib.util
import os
import sys

from docintel.evals.corrections import Correction
from docintel.evals.promote import build_gold_fixture, corrected_field_diff
from docintel.scorecard import assertions_for


def _load_validate_gold():
    """`docs/corpus/validate_gold.py` is a standalone script, not a package
    module - import it by path, the same way its own README invokes it."""
    path = os.path.join("docs", "corpus", "validate_gold.py")
    spec = importlib.util.spec_from_file_location("validate_gold", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("validate_gold", module)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _correction(**over):
    base = dict(
        id=1, job_id=1, document_id="doc-1", source_path="/tmp/doc-1.pdf",
        original_record={
            "sender_fingerprint": "newvendor|newvendor",
            "classification": {
                "doc_type": "invoice", "tags": [], "text_source": "native",
                "page_count": 1, "page_roles": ["primary"],
            },
            "fields": {"vendor_name": None, "total_printed": "640.50"},
            "derived": {},
        },
        corrected_fields={"vendor_name": "Acme Corp"},
        status="pending_promotion", corrected_by="alice", corrected_at="2026-08-17T00:00:00",
    )
    base.update(over)
    return Correction(**base)


def test_corrected_fields_are_merged_over_the_snapshot():
    fixture = build_gold_fixture(_correction(), gold_id="g1", source_file="corpus/g1.pdf")
    assert fixture["fields"] == {"vendor_name": "Acme Corp", "total_printed": "640.50"}


def test_classification_is_carried_through_from_the_snapshot():
    fixture = build_gold_fixture(_correction(), gold_id="g1", source_file="corpus/g1.pdf")
    assert fixture["classification"] == {
        "doc_type": "invoice", "tags": [], "text_source": "native",
        "page_count": 1, "page_roles": ["primary"],
    }


def test_pack_is_derived_from_the_sender_fingerprint():
    fixture = build_gold_fixture(_correction(), gold_id="g1", source_file="corpus/g1.pdf")
    assert fixture["pack"] == "newvendor"


def test_expected_routing_reflects_a_hard_miss_escalation_with_lane_left_for_a_human():
    fixture = build_gold_fixture(_correction(), gold_id="g1", source_file="corpus/g1.pdf")
    assert fixture["expected_routing"]["review_flag"] is True
    assert fixture["expected_routing"]["regen_flag"] is False
    assert fixture["expected_routing"]["lane"] is None


def test_corrected_field_diff_only_names_fields_a_human_actually_changed():
    diff = corrected_field_diff(_correction())
    assert diff == {"vendor_name": (None, "Acme Corp")}


def test_the_gold_fixture_survives_scorecard_assertions_for_without_a_key_error():
    """The direct proof this is real, not just JSON-shaped: the exact function
    `replay-gold` calls on every gold file must not crash on a promoted one."""
    fixture = build_gold_fixture(_correction(), gold_id="g1", source_file="corpus/g1.pdf")
    assertions = assertions_for(fixture)
    assert any(a.name == "fields.vendor_name" for a in assertions)
    assert any(a.name == "doc_type" for a in assertions)


def test_the_gold_fixture_passes_validate_golds_structural_checks():
    validate_gold = _load_validate_gold()
    fixture = build_gold_fixture(_correction(), gold_id="g1", source_file="corpus/g1.pdf")
    report = validate_gold.Report()
    validate_gold.check(fixture, report)
    assert report.failures == []
