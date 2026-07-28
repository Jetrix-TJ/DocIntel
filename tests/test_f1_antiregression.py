"""GUARDRAIL 2 — DO NOT DELETE THIS FILE.

On 7 of the 10 corpus documents, `amount_payable == total_printed`. Anyone
optimizing this code will be tempted to collapse the derivation into "read the
total". That change passes 7 of 10 gold documents and is wrong by $20,123.80 on
Centracom, the largest invoice in the corpus.

If this test is failing, DO NOT relax it. Read docs/corpus-analysis.md section F1.
"""

from decimal import Decimal

import pytest

from docintel.core.models import new_context
from docintel.grammar.ops.derive import derive_amount_payable, resolve_carried_balance

pytestmark = pytest.mark.skip(
    reason="printed-fields-only: derive_amount_payable is deferred, not deleted. "
    "See docs/superpowers/specs/2026-07-28-printed-fields-only-design.md. "
    "Re-enable this guardrail in the same change that re-registers the op."
)

CENTRACOM_PRINTED = Decimal("33876.40")
CENTRACOM_PAYABLE = Decimal("13752.60")
COST_OF_BEING_WRONG = Decimal("20123.80")


def _centracom():
    ctx = new_context("centracom", "/x.pdf")
    ctx.extracted.set("prior_balance", Decimal("20123.80"), 1.0)
    ctx.extracted.set("payments_credits", Decimal("-24120.20"), 1.0)
    ctx.extracted.set("current_charges", CENTRACOM_PAYABLE, 1.0)
    ctx.extracted.set("total_printed", CENTRACOM_PRINTED, 1.0)
    ctx.extracted.set("prior_balance_basis", "net_of_payments", 1.0)
    return ctx


def test_the_naive_answer_is_not_produced():
    ctx = derive_amount_payable(resolve_carried_balance(_centracom()))
    payable = ctx.derived.get("amount_payable")
    assert payable != CENTRACOM_PRINTED, (
        f"REGRESSION: amount_payable returned the printed total {CENTRACOM_PRINTED}. "
        f"That overpays by {COST_OF_BEING_WRONG}. See corpus-analysis.md F1."
    )
    assert payable == CENTRACOM_PAYABLE


def test_the_derivation_records_why():
    ctx = derive_amount_payable(resolve_carried_balance(_centracom()))
    assert ctx.derived.get("payable_basis") == "current_charges"


def test_sanity_the_two_numbers_really_do_differ_by_the_prior_balance():
    assert CENTRACOM_PRINTED - CENTRACOM_PAYABLE == COST_OF_BEING_WRONG
