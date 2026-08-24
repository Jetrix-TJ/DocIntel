"""Full pipeline, end to end, no mocks on packs/personas/business logic.

Every test here builds the real `Runner` through the real, public
`build_pipeline()` entry point - the same one `docintel process` and every
real caller uses - and feeds it a real document. The only stand-in is
`FakeVision`, so a vision-fallback assertion still proves real ROUTING
without needing a live API key.

This file exists to answer one question directly, for a human, in one
place: "does the whole pipeline actually work, end to end, right now?" -
across the four shapes a document can take on its way through: a known
vendor extracted by cached rules, an unknown vendor falling back to vision,
a genuinely broken input, and the entire real gold corpus surviving a run
with zero uncaught exceptions.

Individual mechanisms (claim rules, selector geometry, derivation math,
confidence gating, scoring accuracy) already have their own deep, focused
test suites elsewhere - this file deliberately does not re-prove any of
them in isolation. It proves they compose correctly into one working
system, which is a different claim.
"""

from __future__ import annotations

import glob
import json
import os
from decimal import Decimal

from docintel import build_pipeline
from docintel.adapters.vision.fake import FakeVision
from docintel.core.contract import validate_record

CENTRACOM_PDF = "docs/Centracom_0384043574_01012026_BILL.pdf"
CENTRACOM_GOLD = "docs/corpus/gold/digitaldirection-centracom-0384043574.json"


# ---------------------------------------------------------------------------
# 1. A known vendor: the whole rules-first path, including the one trap that
#    makes this document "the single most important document in the corpus"
#    (the gold fixture's own words) - a naive extractor pays the printed
#    total and overpays by $20,123.80 of prior balance already billed.
# ---------------------------------------------------------------------------


def test_a_known_vendor_document_extracts_and_derives_correctly_end_to_end():
    vision = FakeVision()
    pipeline = build_pipeline(vision=vision)

    record = pipeline.process(document_id="e2e-centracom", source_path=CENTRACOM_PDF)

    validate_record(record)  # the full output-contract check, not a subset

    # -- classification & routing (stages 1-4) ------------------------------
    assert record["disposition"] == "processed"
    assert record["doc_type"] == "telecom_bill"
    assert record["sender_fingerprint"] == "digitaldirection|centracom"
    assert "unclaimed_document" not in record["tags"]

    # -- extraction took the cheap path, never paid for a vision call -------
    assert record["extraction_route"] == "5a_cached"
    assert vision.calls == [], "a persona hit must cost zero vision calls"

    # -- real printed values, not placeholders -------------------------------
    assert record["fields"]["account_number"] == "0384043574"
    assert record["fields"]["prior_balance"] == "20123.80"
    assert record["fields"]["current_charges"] == "13752.60"
    assert record["fields"]["total_printed"] == "33876.40"

    # -- the trap: business logic must derive the PAYABLE, not the printed
    #    total. This is the one number that would have overpaid $20,123.80. --
    assert record["derived"]["amount_payable"] == "13752.60"
    assert record["derived"]["payable_basis"] == "current_charges"
    assert record["derived"]["carried_balance"] == "20123.80"
    assert record["derived"]["vendor_name"] == "CentraCom"
    assert record["derived"]["document_identity"] == "0384043574|2026-01-01"
    assert record["derived"]["identity_basis"] == "account_period"

    # -- confidence gate: a clean, fully-extracted document is auto-approved
    assert record["lane"] == "high"
    assert record["review_flag"] is False
    assert record["regen_flag"] is False

    # -- every real gold-fixture expectation this document is labelled with,
    #    cross-checked directly against the checked-in fixture rather than
    #    a value re-typed into this test (so the two cannot silently drift). -
    gold = json.loads(open(CENTRACOM_GOLD).read())
    # Money by VALUE, not by string - gold holds 13752.6 (JSON drops the
    # trailing zero) while the record serializes Decimal("13752.60") as
    # "13752.60"; both denote the same amount (the same reasoning
    # `scorecard.matches(..., kind="money")` already encodes).
    assert Decimal(record["derived"]["amount_payable"]) == Decimal(str(gold["derived"]["amount_payable"]))
    assert record["derived"]["payable_basis"] == gold["derived"]["payable_basis"]
    assert record["lane"] == gold["expected_routing"]["lane"]
    assert record["review_flag"] == gold["expected_routing"]["review_flag"]
    assert record["regen_flag"] == gold["expected_routing"]["regen_flag"]


def test_the_known_vendor_run_actually_traverses_every_pipeline_stage():
    """`events` is the record's own trace of what ran (`core.contract.
    build_record`) - proof the full 8-stage/11-module sequence executed for
    this real document, not just that the final fields happen to be right."""
    pipeline = build_pipeline(vision=FakeVision())
    record = pipeline.process(document_id="e2e-centracom-stages", source_path=CENTRACOM_PDF)

    stage_markers = ["s1:", "s2:", "s3:", "s4:", "s4b:", "s5a:", "s6:", "s7:", "s8:"]
    for marker in stage_markers:
        assert any(e.startswith(marker) for e in record["events"]), (
            f"stage {marker!r} never logged anything - did it actually run?"
        )


# ---------------------------------------------------------------------------
# 2. An unknown vendor: no pack claims it, no persona exists, so the vision
#    fallback must fire and the document must still be flagged for a human -
#    unconditionally, regardless of how confident the one-shot result looks
#    (the P0 fix this session made to `s5c_agent.AgentEscalation`).
# ---------------------------------------------------------------------------


def test_an_unknown_vendor_document_falls_back_to_vision_and_is_flagged_for_review(tmp_path):
    from PIL import Image

    png = tmp_path / "unknown-scan.png"
    Image.new("RGB", (850, 1100), (255, 255, 255)).save(png)

    vision = FakeVision()
    pipeline = build_pipeline(vision=vision)

    record = pipeline.process(
        document_id="e2e-unknown", source_path=str(png), sender_email="ap@unknownvendor.example",
    )

    validate_record(record)

    assert record["disposition"] == "processed"  # never crashes on an unknown vendor
    assert "unclaimed_document" in record["tags"]
    assert record["sender_fingerprint"] == "unknown|unknown"

    # -- vision actually fired, and asked for exactly the 4 default fields --
    assert record["extraction_route"] == "5b_vision"
    assert vision.calls == [["vendor_name", "invoice_number", "invoice_date", "total_printed"]]

    # -- a hard miss must ALWAYS reach a human, confident-looking result or
    #    not - this is the exact guarantee the P0 escalation-gate fix closed.
    assert record["review_flag"] is True

    # -- duplicate detection still has SOMETHING to key on, even with no
    #    invoice number or account+period - the soft_fingerprint fallback
    #    this session's P1 fix added.
    assert record["derived"]["identity_basis"] == "soft_fingerprint"


# ---------------------------------------------------------------------------
# 3. A genuinely broken input: the emit-always guarantee (Runner's whole
#    reason for existing) must hold even when parsing itself throws.
# ---------------------------------------------------------------------------


def test_a_corrupt_pdf_still_emits_a_valid_dead_letter_record(tmp_path):
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"not a real pdf at all, just garbage bytes 0000000")

    pipeline = build_pipeline(vision=FakeVision())
    record = pipeline.process(document_id="e2e-corrupt", source_path=str(corrupt))

    validate_record(record)  # dead-lettered, but still a CONTRACT-VALID record
    assert record["disposition"] == "dead_letter"
    assert record["review_flag"] is True
    assert record["reason"]  # a human gets an actual reason, not a blank


def test_processing_and_emitted_counts_stay_equal_even_after_a_crash():
    """`Runner.stats` is the machine-checkable half of the emit-always
    guarantee: every document intaken must be emitted, dead letter or not."""
    from docintel.pipeline.runner import Runner
    from docintel.pipeline.stages import build_default_stages
    from docintel.pipeline.hooks import HookRegistry

    runner = Runner(stages=build_default_stages(vision=FakeVision()), hooks=HookRegistry())
    runner.process("ok", CENTRACOM_PDF)
    runner.process("missing", "/definitely/does/not/exist.pdf")

    assert runner.stats["intaken"] == runner.stats["emitted"] == 2


# ---------------------------------------------------------------------------
# 4. The whole real corpus, one pass: not an accuracy check (that is
#    `scorecard.replay_gold`'s job, exercised in `tests/test_scorecard.py`) -
#    a structural survival check. Every real document this project ships
#    must produce a valid, contract-compliant record with zero uncaught
#    exceptions, regardless of whether every field comes back correct.
# ---------------------------------------------------------------------------


def test_every_real_gold_source_document_survives_a_full_pipeline_run():
    gold_files = sorted(glob.glob(os.path.join("docs", "corpus", "gold", "*.json")))
    assert len(gold_files) >= 15, "the real gold corpus should not have shrunk"

    pipeline = build_pipeline(vision=FakeVision())
    failures: list[str] = []

    for gold_path in gold_files:
        gold = json.loads(open(gold_path).read())
        source = os.path.join("docs", gold["source_file"])
        if not os.path.isfile(source):
            failures.append(f"{gold['gold_id']}: source file missing at {source}")
            continue
        record = pipeline.process(document_id=gold["gold_id"], source_path=source)
        try:
            validate_record(record)
        except Exception as exc:  # noqa: BLE001 - collecting, not raising per-doc
            failures.append(f"{gold['gold_id']}: record failed contract validation: {exc}")
            continue
        if record["disposition"] not in ("processed", "skipped"):
            failures.append(f"{gold['gold_id']}: disposition={record['disposition']!r}, reason={record['reason']!r}")

    assert not failures, "\n" + "\n".join(failures)
