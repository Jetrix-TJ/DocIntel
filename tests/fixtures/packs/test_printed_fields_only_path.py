"""One real PDF per pack, all the way to a validated Stage 8 record.

Unit tests confirm the units. Only the whole path shows what the units compose
into - which is how C2b's line_items selector swallowing the totals block got
caught after passing all 42 of its unit tests (standing rule 10).

Conventions are borrowed wholesale from `tests/test_f1_centracom_trap.py`, the
existing whole-path test: the document id and source path are read out of the
gold file rather than retyped, the runner is `build_pipeline(FakeVision())`, and
each record is built once per module.

`FakeVision` rather than a cassette, for the same reason the trap test uses it:
both of these documents extract through `5a_cached` off a native text layer, so
a vision adapter that answers nothing is the strongest available statement that
nothing here depends on a model. If either document ever starts needing vision,
these assertions fail loudly instead of quietly replaying a recording.

A fresh runner per document, matching `scorecard.replay_gold` - a shared runner
carries duplicate-detection state from one document into the next.
"""

from __future__ import annotations

import json
import os

import pytest

from docintel.adapters.vision.fake import FakeVision
from docintel.core.contract import validate_record
from docintel.core.models import DERIVED_ONLY
from docintel.pipeline.stages import build_pipeline

GOLD_DIR = os.path.join("docs", "corpus", "gold")
DOCS_DIR = "docs"

NORTHSTAR_GOLD = "northstar-dtss-6060"
DIGITALDIRECTION_GOLD = "digitaldirection-centracom-0384043574"

# `derive_document_identity` runs unconditionally and stays out of the narrowing:
# `core/contract.py` requires the PRESENCE of both keys, so dropping them would
# break `count(intaken) == count(emitted)`.
CONTRACT_DERIVED_KEYS = {"document_identity", "identity_basis"}

# Names Task 11 re-wired that must not leak past `_leaked()`'s allowlist check,
# but carry no contract-level presence guarantee - `carried_balance` in
# particular is absent (not None, absent) whenever `resolve_carried_balance`
# cannot determine a basis (grammar/ops/derive.py:160-165).
RETAINED_DERIVED = {
    "document_identity", "identity_basis",
    "amount_payable", "payable_basis", "carried_balance",
}


def _run(gold_id: str) -> dict:
    from digitaldirection import PACK as DIGITALDIRECTION_PACK
    from northstar import PACK as NORTHSTAR_PACK

    with open(os.path.join(GOLD_DIR, f"{gold_id}.json")) as fh:
        gold = json.load(fh)
    runner = build_pipeline(FakeVision(), extra_packs=[NORTHSTAR_PACK, DIGITALDIRECTION_PACK])
    return runner.process(
        document_id=gold["gold_id"],
        source_path=os.path.join(DOCS_DIR, gold["source_file"]),
    )


@pytest.fixture(scope="module")
def northstar_record() -> dict:
    return _run(NORTHSTAR_GOLD)


@pytest.fixture(scope="module")
def centracom_record() -> dict:
    return _run(DIGITALDIRECTION_GOLD)


def _leaked(record: dict) -> list[str]:
    names = set(record["fields"]) | set(record.get("derived", {}))
    return sorted(names & (DERIVED_ONLY - RETAINED_DERIVED))


def test_northstar_record_carries_no_derived_field(northstar_record: dict) -> None:
    assert northstar_record["disposition"] == "processed"
    leaked = _leaked(northstar_record)
    assert not leaked, f"derived values reached the record: {leaked}"


def test_centracom_record_carries_no_derived_field(centracom_record: dict) -> None:
    assert centracom_record["disposition"] == "processed"
    leaked = _leaked(centracom_record)
    assert not leaked, f"derived values reached the record: {leaked}"


def test_northstar_record_still_carries_the_identity_contract_keys(
    northstar_record: dict,
) -> None:
    """core/contract.py requires their PRESENCE - None is a valid value, absence
    is not. Dropping them would break count(intaken) == count(emitted).

    Only `document_identity`/`identity_basis` carry this guarantee. The other
    names in `RETAINED_DERIVED` (`amount_payable`, `payable_basis`,
    `carried_balance`) are re-wired as of Task 11 but have no contract-level
    presence requirement - `carried_balance` in particular is genuinely absent
    on the undeterminable-basis path (grammar/ops/derive.py:160-165)."""
    for key in CONTRACT_DERIVED_KEYS:
        assert key in northstar_record["derived"]


def test_centracom_record_still_carries_the_identity_contract_keys(
    centracom_record: dict,
) -> None:
    for key in CONTRACT_DERIVED_KEYS:
        assert key in centracom_record["derived"]


def test_northstar_total_is_the_printed_figure(northstar_record: dict) -> None:
    """DTSS prints a single total and no prior balance, so printed and payable
    were never in tension here - which makes it the honest place to assert that
    total_printed is transcribed rather than adjusted."""
    assert northstar_record["fields"]["total_printed"] == "699.00"


def test_centracom_emits_the_derived_payable(centracom_record: dict) -> None:
    """Task 11: the printed total and the derived payable now BOTH appear.

    Centracom prints 33,876.40 and is payable 13,752.60. Before Task 11 the
    pipeline transcribed the printed figure and said nothing about the
    payable; the derivation is now wired, so both are on the record and they
    legitimately disagree - that disagreement is the whole point of F1.

    If this ever starts asserting `"amount_payable" not in centracom_record["derived"]`
    again, derivation was un-wired without reverting GUARDRAIL 2
    (`test_f1_antiregression.py`) and GUARDRAIL 6 (`test_f1_centracom_trap.py`)
    back to skipped - do that together, not this test alone.
    """
    assert centracom_record["fields"]["total_printed"] == "33876.40"
    assert centracom_record["derived"]["amount_payable"] == "13752.60"
    assert centracom_record["derived"]["payable_basis"] == "current_charges"


def test_centracom_prior_balance_tag_matches_gold_exactly(
    centracom_record: dict,
) -> None:
    """The tag the scorecard's superset check structurally cannot police.

    Centracom's gold `tags` assertion is a SUPERSET, and it is already red on
    `no_invoice_number` and `past_due`. A wrong tag appearing among the extras
    therefore moves it FAIL -> FAIL and nothing anywhere notices - which is
    exactly how the pipeline came to ship `prior_balance_cleared` on a document
    with 20,123.80 outstanding.

    So this pins the pair EXACTLY, and against gold rather than a retyped
    literal. An inversion fails here on its own, whatever the other tags do.
    """
    with open(os.path.join(GOLD_DIR, f"{DIGITALDIRECTION_GOLD}.json")) as fh:
        gold = json.load(fh)
    expected = [
        t for t in gold["classification"]["tags"] if t.startswith("prior_balance_")
    ]
    assert expected == ["prior_balance_present"], (
        "gold no longer labels Centracom's prior balance as outstanding; this "
        "test is only meaningful while it does"
    )

    actual = [
        t for t in centracom_record.get("tags", []) if t.startswith("prior_balance_")
    ]
    assert actual == expected, (
        f"Centracom's prior-balance tag is {actual}, gold says {expected}. "
        "20,123.80 is outstanding; claiming it cleared points a downstream "
        "consumer at the opposite of the truth."
    )


def test_both_records_are_schema_valid(
    northstar_record: dict, centracom_record: dict
) -> None:
    validate_record(northstar_record)  # must not raise
    validate_record(centracom_record)


# Standing rule 10: a task that adds a pipeline capability finishes with one
# whole-path test. `_run` above deliberately builds a FRESH runner per call -
# the module docstring gives the exact reason duplicate detection needs the
# opposite, so this test builds its own single runner and pushes the same real
# PDF through it twice under two different document ids.
VERITIV_GOLD = "northstar-veritiv-715-33905296"


def test_the_same_invoice_processed_twice_reports_the_first_document() -> None:
    with open(os.path.join(GOLD_DIR, f"{VERITIV_GOLD}.json")) as fh:
        gold = json.load(fh)
    source_path = os.path.join(DOCS_DIR, gold["source_file"])

    runner = build_pipeline(FakeVision())
    first = runner.process(document_id="first", source_path=source_path)
    second = runner.process(document_id="second", source_path=source_path)

    assert first["possible_duplicate_of"] is None
    assert second["possible_duplicate_of"] == "first"
