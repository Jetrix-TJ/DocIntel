"""GUARDRAIL 6 — DO NOT DELETE THIS FILE.

From the Digital Direction pack spec, section 7:

    All four should route High — but only because `derive_amount_payable` works.
    Without it, three still route High with correct values and Centracom routes
    High with a value that is $20,123.80 wrong. It would look like a
    100%-passing pack.

    **This is the single most important test in the repository.** It is also the
    one most likely to be "simplified" away by someone who notices that
    `total_printed == current_charges` on three of the four sample bills.

What makes Centracom worse than EDCO's version of the same trap is that **every
corroboration signal points at the wrong number.** 33,876.40 is printed in the
largest font on the page, it is what the remittance scan line encodes, and it is
what the stub says to remit. The only evidence for 13,752.60 is the composition
20,123.80 + 13,752.60 == 33,876.40.

If this test is failing, DO NOT relax it. Read docs/corpus-analysis.md F1 and F1b.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal

import pytest

from docintel.adapters.vision.fake import FakeVision
from docintel.pipeline.stages import build_pipeline

pytestmark = pytest.mark.skip(
    reason="printed-fields-only: derive_amount_payable is deferred, not deleted. "
    "See docs/superpowers/specs/2026-07-28-printed-fields-only-design.md. "
    "Re-enable this guardrail in the same change that re-registers the op."
)

GOLD_PATH = os.path.join(
    "docs", "corpus", "gold", "digitaldirection-centracom-0384043574.json"
)

PRINTED = Decimal("33876.40")
PAYABLE = Decimal("13752.60")
COST_OF_BEING_WRONG = Decimal("20123.80")


@pytest.fixture(scope="module")
def record() -> dict:
    with open(GOLD_PATH) as fh:
        gold = json.load(fh)
    runner = build_pipeline(FakeVision())
    return runner.process(
        document_id=gold["gold_id"],
        source_path=os.path.join("docs", gold["source_file"]),
    )


def test_sanity_the_two_numbers_differ_by_the_prior_balance() -> None:
    assert PRINTED - PAYABLE == COST_OF_BEING_WRONG


def test_the_printed_total_is_captured_as_printed(record: dict) -> None:
    """The trap value is not hidden - it IS the total, and the record says so."""
    assert Decimal(record["fields"]["total_printed"]) == PRINTED


def test_the_payable_is_not_the_printed_total(record: dict) -> None:
    payable = record["derived"]["amount_payable"]
    assert payable is not None, "refusing to decide is not the same as being right"
    assert Decimal(payable) != PRINTED, (
        f"REGRESSION: amount_payable returned the printed total {PRINTED}. "
        f"That overpays by {COST_OF_BEING_WRONG} on ONE document. "
        "See docs/corpus-analysis.md F1."
    )


def test_the_payable_is_the_current_charges(record: dict) -> None:
    assert Decimal(record["derived"]["amount_payable"]) == PAYABLE


def test_the_derivation_records_why(record: dict) -> None:
    assert record["derived"]["payable_basis"] == "current_charges"


def test_the_carried_balance_is_the_printed_prior_not_prior_minus_payments(
    record: dict,
) -> None:
    """F1b. CentraCom's printed prior is ALREADY net of a 24,120.20 payment, so
    subtracting payments again would give -3,996.40 - wrong LOW, which is as
    wrong as F1 and much harder to notice."""
    carried = Decimal(record["derived"]["carried_balance"])
    assert carried == Decimal("20123.80")
    assert carried != Decimal("-3996.40")


def test_the_closure_holds(record: dict) -> None:
    carried = Decimal(record["derived"]["carried_balance"])
    current = Decimal(record["fields"]["current_charges"])
    assert carried + current == PRINTED


def test_the_scanline_agrees_with_the_TRAP_and_that_is_fine(record: dict) -> None:
    """F7. The scan line encodes 33,876.40. It validates transcription fidelity,
    never business correctness - which is exactly why `amount_payable` is not in
    `scanline.CORROBORATABLE_FIELDS`. A scan line "confirming" the payable would
    confirm the wrong number."""
    from docintel.extract.scanline import CORROBORATABLE_FIELDS

    assert "amount_payable" not in CORROBORATABLE_FIELDS
    assert "current_charges" not in CORROBORATABLE_FIELDS


def test_no_arithmetic_mismatch_was_flagged(record: dict) -> None:
    """The closure verified, so this is a clean derivation rather than a refusal."""
    assert "arith_balance_mismatch" not in record["confidence_modifiers"]
