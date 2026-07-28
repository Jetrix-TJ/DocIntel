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
RETAINED_DERIVED = {"document_identity", "identity_basis"}


def _run(gold_id: str) -> dict:
    with open(os.path.join(GOLD_DIR, f"{gold_id}.json")) as fh:
        gold = json.load(fh)
    runner = build_pipeline(FakeVision())
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
    is not. Dropping them would break count(intaken) == count(emitted)."""
    for key in RETAINED_DERIVED:
        assert key in northstar_record["derived"]


def test_centracom_record_still_carries_the_identity_contract_keys(
    centracom_record: dict,
) -> None:
    for key in RETAINED_DERIVED:
        assert key in centracom_record["derived"]


def test_northstar_total_is_the_printed_figure(northstar_record: dict) -> None:
    """DTSS prints a single total and no prior balance, so printed and payable
    were never in tension here - which makes it the honest place to assert that
    total_printed is transcribed rather than adjusted."""
    assert northstar_record["fields"]["total_printed"] == "699.00"


def test_centracom_emits_the_printed_total_not_the_payable(
    centracom_record: dict,
) -> None:
    """The consequence this design accepts, asserted so it cannot drift silently.

    This test is pinning a DECISION, not a bug. Centracom prints 33,876.40 and is
    payable 13,752.60. Under printed-fields-only the pipeline transcribes the
    printed figure faithfully and says nothing at all about the payable - the
    $20,123.80 gap is downstream's to catch, and extraction refusing to guess at
    it is the intended behaviour.

    If this ever starts returning 13,752.60, derivation has been re-enabled
    without re-enabling GUARDRAIL 2 (`test_f1_antiregression.py`) and GUARDRAIL 6
    (`test_f1_centracom_trap.py`), which are the two tests that keep the
    derivation honest. Both are `skip`ped with that reason as the message; the
    correct fix is to un-skip them in the same change, not to relax this.
    """
    assert centracom_record["fields"]["total_printed"] == "33876.40"
    assert "amount_payable" not in centracom_record.get("derived", {})


def test_both_records_are_schema_valid(
    northstar_record: dict, centracom_record: dict
) -> None:
    validate_record(northstar_record)  # must not raise
    validate_record(centracom_record)
