"""The `contract` doc_type, end to end - real curated Golub/Windstream
contract PDFs (docs/corpus/contracts/), the real pipeline, no mocks.

Confirms the mechanism this phase built: a genuinely different document
family (a signed service agreement/amendment, not a bill) classifies
correctly, resolves to the SAME sender_fingerprint its carrier's invoices
already use, and gets real field coverage from a dedicated persona - not a
hard miss silently routed to vision.
"""

from __future__ import annotations

import json
import os

from docintel.adapters.vision.fake import FakeVision
from docintel.core.contract import validate_record
from docintel.pipeline.stages import build_pipeline

GOLD_DIR = os.path.join("docs", "corpus", "gold")
DOCS_DIR = "docs"


def _run(gold_id: str) -> dict:
    from digitaldirection import PACK as DIGITALDIRECTION_PACK

    with open(os.path.join(GOLD_DIR, f"{gold_id}.json")) as fh:
        gold = json.load(fh)
    runner = build_pipeline(FakeVision(), extra_packs=[DIGITALDIRECTION_PACK])
    return runner.process(
        document_id=gold["gold_id"],
        source_path=os.path.join(DOCS_DIR, gold["source_file"]),
    )


def test_a_signed_contract_classifies_as_contract_not_a_bill():
    """The bug this whole feature exists to fix: of 18 real Windstream-carrier
    documents in an earlier corpus sample, 16 were contracts/amendments/CSRs
    misclassified as bills purely because the carrier's name appears on the
    page (corpus-analysis.md F20)."""
    record = _run("digitaldirection-golub-contract-base-2020")
    assert record["doc_type"] == "contract"
    for billing_type in ("telecom_bill", "credit_memo", "disconnect_notice"):
        assert record["doc_type"] != billing_type


def test_a_contract_resolves_the_same_fingerprint_its_carriers_invoices_use():
    """Fingerprinting depends only on the carrier's name, not doc_type - so a
    contract for a carrier that already has a shipped invoice persona needs no
    fingerprint or hook changes, only a new persona file at the same key."""
    record = _run("digitaldirection-golub-contract-base-2020")
    assert record["sender_fingerprint"] == "digitaldirection|windstream"


def test_a_contract_gets_real_field_coverage_from_its_own_persona():
    """Not just correctly classified - actually extracted, via a real,
    shipped, active persona (not a draft, not a hard-miss vision fallback)."""
    record = _run("digitaldirection-golub-contract-renewal-2022")
    assert record["extraction_route"] == "5a_cached"
    assert record["fields"]["contract_number"] == "2494434"


def test_every_contract_record_still_validates_against_the_contract():
    """The record contract is doc_type-agnostic - a contract document must
    validate exactly like an invoice does, no special-casing required."""
    for gold_id in (
        "digitaldirection-golub-contract-base-2020",
        "digitaldirection-golub-contract-renewal-2022",
        "digitaldirection-golub-contract-amendment-add-services-2021",
        "digitaldirection-golub-contract-amendment-call-paths-2021",
    ):
        validate_record(_run(gold_id))


def test_a_bills_field_set_is_unaffected_by_the_new_contract_persona():
    """Regression guard at the full-pipeline level: adding a contract persona
    to the digitaldirection pack must not change what an ordinary telecom
    bill from the SAME carrier extracts."""
    record = _run("digitaldirection-windstream-041069076")
    assert record["doc_type"] == "telecom_bill"
    assert record["fields"].get("total_printed") is not None
