"""GUARDRAIL 4 — DO NOT DELETE THIS FILE.

Federal Recycling's invoice carries values in flattened annotations: coloured
fills and overlapping text runs with `annots == 0`, so the overlay values are
invisible to the text layer while looking perfectly ordinary to a reader. A
pipeline that fast-lanes it will emit numbers that the document does not show,
confidently, with nothing on the record to say so.

Section 5 of the selector grammar therefore says `flattened_annotations` **forces
review, unconditionally** — and the gold label agrees, expecting the `review`
lane rather than `high` or `medium`.

This test walks the whole chain in one go, because every link in it was built in
a different cluster and each has its own unit tests that all passed while the
chain was broken:

    annotations.detect_flattened   (C1b)  ->  has_flattened_annotations tag
    s6_capture                     (C3)   ->  flattened_annotations modifier
    s7_gate                        (C4)   ->  forced review, `review` lane

If this test is failing, DO NOT relax it. A document whose printed values are
invisible to the text layer must never reach the fast lane.
"""

from __future__ import annotations

import json
import os

import pytest

from docintel.adapters.vision.fake import FakeVision
from docintel.pipeline.hooks import HookRegistry
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_default_stages

GOLD_PATH = os.path.join(
    "docs", "corpus", "gold", "northstar-federal-recycling-1330123.json"
)


@pytest.fixture(scope="module")
def record() -> dict:
    with open(GOLD_PATH) as fh:
        gold = json.load(fh)
    runner = Runner(stages=build_default_stages(FakeVision()), hooks=HookRegistry())
    return runner.process(
        document_id=gold["gold_id"],
        source_path=os.path.join("docs", gold["source_file"]),
    )


def test_the_flattened_annotation_tag_is_detected(record: dict) -> None:
    assert "has_flattened_annotations" in record["tags"], (
        "C1b's detector no longer recognises the flattened annotations; every "
        "link below it is now dead"
    )


def test_the_modifier_is_applied(record: dict) -> None:
    assert "flattened_annotations" in record["confidence_modifiers"]


def test_the_document_is_forced_into_the_review_lane(record: dict) -> None:
    """The whole point. Not `high`, and not `medium` either — `medium` is the
    queue for documents whose *numbers* look shaky, and this document's numbers
    may be perfect. What is wrong is that some of them are not on the page."""
    assert record["lane"] == "review"
    assert record["review_flag"] is True


def test_it_is_never_treated_as_a_clean_document(record: dict) -> None:
    assert record["lane"] != "high"
    assert record["audit_sample"] is False, (
        "an audit sample is a spot-check of documents believed clean; this one "
        "is known not to be"
    )


def test_the_routing_matches_the_gold_label(record: dict) -> None:
    with open(GOLD_PATH) as fh:
        routing = json.load(fh)["expected_routing"]
    assert record["lane"] == routing["lane"]
    assert record["review_flag"] == routing["review_flag"]
    assert record["regen_flag"] == routing["regen_flag"]


def test_a_regen_flag_is_not_raised(record: dict) -> None:
    """The rules are not wrong — the document is unusual. Raising regen here
    would send someone to rewrite a persona that is behaving correctly."""
    assert record["regen_flag"] is False
