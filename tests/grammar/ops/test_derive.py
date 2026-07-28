"""The F1 machinery. The plan's block comes first, verbatim, then the rest.

Every numbered case here is a real corpus document, not a hypothetical. That is
deliberate: F1 is a bug that looks correct on 7 of 10 documents, so the tests
that catch it have to be the 3 that disagree.
"""

from decimal import Decimal

import pytest

from docintel.core.models import new_context
from docintel.grammar.ops.derive import (
    derive_amount_payable,
    derive_document_identity,
    normalize_credit_sign,
    prefer_current_charges_line,
    resolve_carried_balance,
    subtract_prior_balance_if_present,
)


def _ctx(prior, current, printed, basis, payments=None):
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("prior_balance", Decimal(prior), 1.0)
    ctx.extracted.set("current_charges", Decimal(current), 1.0)
    ctx.extracted.set("total_printed", Decimal(printed), 1.0)
    ctx.extracted.set("prior_balance_basis", basis, 1.0)
    if payments is not None:
        ctx.extracted.set("payments_credits", Decimal(payments), 1.0)
    return ctx


# ==========================================================================
# The plan's block, verbatim
# ==========================================================================


def test_centracom_net_of_payments_yields_the_current_charges():
    """THE test. Wrong here costs $20,123.80."""
    ctx = _ctx("20123.80", "13752.60", "33876.40", "net_of_payments", "-24120.20")
    ctx = resolve_carried_balance(ctx)
    ctx = derive_amount_payable(ctx)
    assert ctx.derived.get("carried_balance") == Decimal("20123.80")
    assert ctx.derived.get("amount_payable") == Decimal("13752.60")
    assert ctx.derived.get("payable_basis") == "current_charges"
    assert ctx.review_flag is False


def test_edco_balance_forward_yields_the_current_charges():
    ctx = _ctx("298.34", "69.62", "367.96", "gross", "0.00")
    ctx = derive_amount_payable(resolve_carried_balance(ctx))
    assert ctx.derived.get("amount_payable") == Decimal("69.62")
    assert ctx.derived.get("payable_basis") == "current_charges"


@pytest.mark.parametrize("prior,payments,current,printed", [
    ("212.87", "-212.87", "221.11", "221.11"),      # Comcast
    ("1231.74", "-1231.74", "1230.14", "1230.14"),  # Windstream
    ("249.84", "-249.84", "248.09", "248.09"),      # Lumen
])
def test_gross_prior_cleared_to_zero_yields_the_printed_total(prior, payments, current, printed):
    """F1b: prior is gross, a signed credit zeroes it, so the printed total IS payable."""
    ctx = _ctx(prior, current, printed, "gross", payments)
    ctx = derive_amount_payable(resolve_carried_balance(ctx))
    assert ctx.derived.get("carried_balance") == Decimal("0.00")
    assert ctx.derived.get("amount_payable") == Decimal(printed)
    assert ctx.derived.get("payable_basis") == "total_printed"


def test_net_basis_must_not_subtract_payments_twice():
    """Double-subtracting fails LOW, which is as wrong as F1 and harder to notice."""
    ctx = _ctx("20123.80", "13752.60", "33876.40", "net_of_payments", "-24120.20")
    ctx = resolve_carried_balance(ctx)
    assert ctx.derived.get("carried_balance") != Decimal("-3996.40")


def test_unexplained_gap_refuses_to_guess():
    """U-Pak: 14789.77 printed, 14740.85 payable, aging all zero. Human required."""
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("total_printed", Decimal("14789.77"), 1.0)
    ctx.extracted.set("please_pay", Decimal("14740.85"), 1.0)
    ctx = derive_amount_payable(ctx)
    assert ctx.derived.get("amount_payable") is None
    assert ctx.review_flag is True
    assert "arith_balance_mismatch" in ctx.modifiers


def test_missing_basis_is_a_review_flag_not_a_default():
    ctx = _ctx("100.00", "50.00", "150.00", basis=None)
    ctx = resolve_carried_balance(ctx)
    assert ctx.review_flag is True


# ==========================================================================
# Beyond the plan's block
# ==========================================================================

# --- resolve_carried_balance ----------------------------------------------


def test_no_prior_balance_needs_no_basis_and_raises_nothing():
    """5 of 10 corpus documents print no prior balance at all. That is normal,
    not missing information, and must not flag."""
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("total_printed", Decimal("699.00"), 1.0)
    ctx = resolve_carried_balance(ctx)
    assert ctx.derived.get("carried_balance") == Decimal("0")
    assert ctx.review_flag is False


def test_an_undeterminable_basis_sets_no_carried_balance_at_all():
    """Not zero, not the prior - absent. A default in either direction is the bug:
    guessing gross double-subtracts on Centracom, guessing net carries a paid-off
    balance forward on Comcast."""
    ctx = _ctx("100.00", "50.00", "150.00", basis=None)
    ctx = resolve_carried_balance(ctx)
    assert ctx.derived.get("carried_balance") is None


def test_an_unrecognized_basis_string_is_also_a_flag_not_a_default():
    ctx = _ctx("100.00", "50.00", "150.00", basis="something_new")
    ctx = resolve_carried_balance(ctx)
    assert ctx.derived.get("carried_balance") is None
    assert ctx.review_flag is True


def test_gross_basis_with_no_payments_line_carries_the_prior_in_full():
    """EDCO: BALANCE FORWARD 298.34, no separate payment line printed."""
    ctx = _ctx("298.34", "69.62", "367.96", "gross")
    ctx = resolve_carried_balance(ctx)
    assert ctx.derived.get("carried_balance") == Decimal("298.34")


def test_a_partially_paid_gross_balance_carries_the_remainder():
    """Synthetic: the corpus only shows fully-cleared and untouched priors.

    Arithmetic, spelled out because an inconsistent fixture here would pass for
    the wrong reason: prior 500 gross, a 400 payment inside it, so 100 is still
    carried. Current charges 100. The printed total is therefore 200 - carried
    plus current - not 600.
    """
    ctx = _ctx("500.00", "100.00", "200.00", "gross", "-400.00")
    ctx = derive_amount_payable(resolve_carried_balance(ctx))
    assert ctx.derived.get("carried_balance") == Decimal("100.00")
    assert ctx.derived.get("amount_payable") == Decimal("100.00")
    assert ctx.derived.get("payable_basis") == "current_charges"


# --- derive_amount_payable ------------------------------------------------


def test_closure_is_checked_against_the_carried_balance_not_the_raw_prior():
    """Section 4.2 words this check as prior + current == printed, which predates
    F1b. On Comcast the raw prior double-counts a payment already made:
    212.87 + 221.11 = 433.98, nowhere near the printed 221.11. Against the
    carried balance it closes exactly."""
    ctx = _ctx("212.87", "221.11", "221.11", "gross", "-212.87")
    ctx = derive_amount_payable(resolve_carried_balance(ctx))
    assert ctx.review_flag is False
    assert ctx.derived.get("amount_payable") == Decimal("221.11")


def test_arithmetic_that_does_not_close_refuses():
    ctx = _ctx("100.00", "50.00", "999.99", "net_of_payments")
    ctx = derive_amount_payable(resolve_carried_balance(ctx))
    assert ctx.derived.get("amount_payable") is None
    assert ctx.derived.get("payable_basis") is None
    assert "arith_balance_mismatch" in ctx.modifiers
    assert ctx.review_flag is True


def test_a_one_cent_discrepancy_is_tolerated_as_rounding():
    ctx = _ctx("100.00", "50.00", "150.01", "net_of_payments")
    ctx = derive_amount_payable(resolve_carried_balance(ctx))
    assert ctx.derived.get("amount_payable") == Decimal("50.00")


def test_two_cents_is_not_rounding() -> None:
    """The tolerance is a rounding allowance, not a fudge factor. U-PAK's
    unexplained 48.92 must never be absorbed by it."""
    ctx = _ctx("100.00", "50.00", "150.02", "net_of_payments")
    ctx = derive_amount_payable(resolve_carried_balance(ctx))
    assert ctx.derived.get("amount_payable") is None


def test_a_carried_balance_with_no_current_charges_refuses():
    """The payable cannot be separated from the total, so it is not guessed."""
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("prior_balance", Decimal("298.34"), 1.0)
    ctx.extracted.set("prior_balance_basis", "net_of_payments", 1.0)
    ctx.extracted.set("total_printed", Decimal("367.96"), 1.0)
    ctx = derive_amount_payable(resolve_carried_balance(ctx))
    assert ctx.derived.get("amount_payable") is None
    assert ctx.review_flag is True


def test_a_prior_with_an_undeterminable_basis_refuses_the_payable_too() -> None:
    """The flag from resolve_carried_balance must not be the only consequence -
    a record whose payable silently fell back to the printed total would be the
    F1 bug wearing a review flag."""
    ctx = _ctx("100.00", "50.00", "150.00", basis=None)
    ctx = derive_amount_payable(resolve_carried_balance(ctx))
    assert ctx.derived.get("amount_payable") is None
    assert "arith_balance_mismatch" in ctx.modifiers


def test_please_pay_agreeing_with_the_total_is_not_a_conflict():
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("total_printed", Decimal("699.00"), 1.0)
    ctx.extracted.set("please_pay", Decimal("699.00"), 1.0)
    ctx = derive_amount_payable(ctx)
    assert ctx.derived.get("amount_payable") == Decimal("699.00")
    assert ctx.review_flag is False


def test_no_total_printed_at_all_refuses():
    ctx = new_context("d", "/x.pdf")
    ctx = derive_amount_payable(ctx)
    assert ctx.derived.get("amount_payable") is None
    assert ctx.review_flag is True


def test_the_four_documents_with_no_prior_balance_take_the_printed_total():
    """Complete Beverage, DTSS, Federal Recycling, Veritiv."""
    for printed in ("1177.70", "699.00", "481.20", "4908.00"):
        ctx = new_context("d", "/x.pdf")
        ctx.extracted.set("total_printed", Decimal(printed), 1.0)
        ctx = derive_amount_payable(resolve_carried_balance(ctx))
        assert ctx.derived.get("amount_payable") == Decimal(printed)
        assert ctx.derived.get("payable_basis") == "total_printed"
        assert ctx.review_flag is False


# --- normalize_credit_sign ------------------------------------------------


def test_an_unsigned_payment_is_forced_negative():
    """The notation the corpus does NOT show, and the reason this op exists: an
    unsigned figure in a Payments column would be ADDED to the prior and double it."""
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("payments_credits", Decimal("1231.74"), 1.0)
    ctx = normalize_credit_sign(ctx)
    assert ctx.extracted.get("payments_credits") == Decimal("-1231.74")


@pytest.mark.parametrize("value", ["-212.87", "-1231.74", "-249.84"])
def test_an_already_negative_payment_is_left_alone(value):
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("payments_credits", Decimal(value), 1.0)
    ctx = normalize_credit_sign(ctx)
    assert ctx.extracted.get("payments_credits") == Decimal(value)


def test_a_zero_payment_stays_zero():
    """EDCO and DTSS both print 0.00; negating it would be noise."""
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("payments_credits", Decimal("0.00"), 1.0)
    ctx = normalize_credit_sign(ctx)
    assert ctx.extracted.get("payments_credits") == Decimal("0.00")


def test_normalize_credit_sign_preserves_match_quality():
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("payments_credits", Decimal("100.00"), 0.85)
    ctx = normalize_credit_sign(ctx)
    assert ctx.extracted.match_quality["payments_credits"] == 0.85


def test_normalizing_the_sign_changes_the_carried_balance():
    """The composition that matters: an unsigned credit left positive would make
    the carried balance 425.74 instead of 0.00, and the payable wrong."""
    ctx = _ctx("212.87", "221.11", "221.11", "gross", "212.87")
    ctx = derive_amount_payable(resolve_carried_balance(normalize_credit_sign(ctx)))
    assert ctx.derived.get("carried_balance") == Decimal("0.00")
    assert ctx.derived.get("amount_payable") == Decimal("221.11")


# --- subtract_prior_balance_if_present ------------------------------------


def test_current_charges_are_computed_when_not_printed():
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("prior_balance", Decimal("298.34"), 1.0)
    ctx.extracted.set("prior_balance_basis", "net_of_payments", 1.0)
    ctx.extracted.set("total_printed", Decimal("367.96"), 1.0)
    ctx = subtract_prior_balance_if_present(resolve_carried_balance(ctx))
    assert ctx.derived.get("current_charges") == Decimal("69.62")


def test_a_printed_current_charges_always_wins_over_a_computed_one():
    """The arithmetic that would compute it is what derive_amount_payable is
    about to check, so computing it would make that check circular."""
    ctx = _ctx("298.34", "69.62", "367.96", "net_of_payments")
    ctx = subtract_prior_balance_if_present(resolve_carried_balance(ctx))
    assert ctx.derived.get("current_charges") is None
    assert ctx.extracted.get("current_charges") == Decimal("69.62")


def test_a_computed_current_charges_feeds_the_payable():
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("prior_balance", Decimal("298.34"), 1.0)
    ctx.extracted.set("prior_balance_basis", "net_of_payments", 1.0)
    ctx.extracted.set("total_printed", Decimal("367.96"), 1.0)
    ctx = resolve_carried_balance(ctx)
    ctx = subtract_prior_balance_if_present(ctx)
    ctx = derive_amount_payable(ctx)
    assert ctx.derived.get("amount_payable") == Decimal("69.62")
    assert ctx.derived.get("payable_basis") == "current_charges"


def test_nothing_is_computed_when_no_balance_is_carried():
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("total_printed", Decimal("699.00"), 1.0)
    ctx = subtract_prior_balance_if_present(resolve_carried_balance(ctx))
    assert ctx.derived.get("current_charges") is None


# --- prefer_current_charges_line ------------------------------------------


def test_the_last_of_several_current_charge_matches_is_kept():
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set(
        "current_charges", [Decimal("69.62"), Decimal("70.00"), Decimal("69.62")], 1.0
    )
    ctx = prefer_current_charges_line(ctx)
    assert ctx.extracted.get("current_charges") == Decimal("69.62")


def test_a_single_value_is_untouched():
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("current_charges", Decimal("69.62"), 1.0)
    ctx = prefer_current_charges_line(ctx)
    assert ctx.extracted.get("current_charges") == Decimal("69.62")


def test_an_empty_match_list_is_not_collapsed_to_a_crash():
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("current_charges", [], 1.0)
    ctx = prefer_current_charges_line(ctx)
    assert ctx.extracted.get("current_charges") == []


# --- derive_document_identity (F6) ----------------------------------------


def test_an_invoice_number_is_the_preferred_identity():
    """Lumen: gold identity '752233001', basis invoice_number."""
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("invoice_number", "752233001", 1.0)
    ctx.extracted.set("account_number", "5-QXH7QKM7", 1.0)
    ctx = derive_document_identity(ctx)
    assert ctx.derived.get("document_identity") == "752233001"
    assert ctx.derived.get("identity_basis") == "invoice_number"


def test_account_plus_period_is_the_fallback():
    """Centracom prints no invoice number at all. Gold: '0384043574|2026-01-01'."""
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("account_number", "0384043574", 1.0)
    ctx.extracted.set("bill_date", "2026-01-01", 1.0)
    ctx = derive_document_identity(ctx)
    assert ctx.derived.get("document_identity") == "0384043574|2026-01-01"
    assert ctx.derived.get("identity_basis") == "account_period"


def test_the_account_number_in_the_key_is_normalized():
    """F6, and the whole point of the delta. Comcast prints
    '8495 44 462 0365242'; gold identity is '8495444620365242'. A key built from
    the printed form would not join against the same account written unspaced."""
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("account_number", "8495 44 462 0365242", 1.0)
    ctx.extracted.set("bill_date", "2025-12-09", 1.0)
    ctx = derive_document_identity(ctx)
    assert ctx.derived.get("document_identity") == "8495444620365242|2025-12-09"


def test_an_account_number_object_contributes_its_normalized_form():
    from docintel.grammar.patterns import NAMED

    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("account_number", NAMED["account_number"]("8495 44 462 0365242"), 1.0)
    ctx.extracted.set("bill_date", "2025-12-09", 1.0)
    ctx = derive_document_identity(ctx)
    assert ctx.derived.get("document_identity") == "8495444620365242|2025-12-09"


def test_a_vendor_account_number_also_serves():
    """EDCO prints only '25-3A 077087'."""
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("vendor_account_number", "25-3A 077087", 1.0)
    ctx.extracted.set("bill_date", "2025-04-30", 1.0)
    ctx = derive_document_identity(ctx)
    assert ctx.derived.get("document_identity") == "253A077087|2025-04-30"
    assert ctx.derived.get("identity_basis") == "account_period"


def test_a_date_result_contributes_its_iso_form():
    from docintel.grammar.patterns import NAMED

    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("account_number", "0384043574", 1.0)
    ctx.extracted.set("bill_date", NAMED["date"]("January 01, 2026"), 1.0)
    ctx = derive_document_identity(ctx)
    assert ctx.derived.get("document_identity") == "0384043574|2026-01-01"


def test_an_unparsed_date_still_identifies_the_document():
    """Centracom's due date is literally '25TH OF THE MONTH' (F9). It is stable
    across months, so it belongs in the key rather than dropping the rung."""
    from docintel.grammar.patterns import NAMED

    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("account_number", "0384043574", 1.0)
    ctx.extracted.set("bill_date", NAMED["date_loose"]("25TH OF THE MONTH"), 1.0)
    ctx = derive_document_identity(ctx)
    assert ctx.derived.get("document_identity") == "0384043574|25TH OF THE MONTH"


def test_neither_rung_available_records_that_it_looked():
    """Both keys set to None, so a consumer can tell "we could not build one"
    from "this pipeline never tried"."""
    ctx = new_context("d", "/x.pdf")
    ctx = derive_document_identity(ctx)
    assert ctx.derived.get("document_identity") is None
    assert ctx.derived.get("identity_basis") is None
    assert "document_identity" in ctx.derived.values


def test_an_account_without_a_period_is_not_an_identity():
    """A bare account number is not document-unique - every month's bill shares it."""
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("account_number", "0384043574", 1.0)
    ctx = derive_document_identity(ctx)
    assert ctx.derived.get("document_identity") is None


def test_an_empty_invoice_number_falls_through_to_the_account_rung():
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("invoice_number", "   ", 1.0)
    ctx.extracted.set("account_number", "0384043574", 1.0)
    ctx.extracted.set("bill_date", "2026-01-01", 1.0)
    ctx = derive_document_identity(ctx)
    assert ctx.derived.get("identity_basis") == "account_period"
