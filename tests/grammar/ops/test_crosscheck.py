"""Consistency ops (section 4.3) - scoring only.

The invariant that governs this whole module: **no op here may change a value.**
There is a registry-wide test for it, because "scoring only" is easy to state
and easy to violate by accident.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from docintel.core.models import new_context
from docintel.grammar.ops import crosscheck


def _ctx(**fields):
    ctx = new_context("d", "/docs/_AP Invoice 6060DTSS D.T.S.S. Inc. 699.00000.pdf")
    for name, value in fields.items():
        ctx.extracted.set(name, value, 1.0)
    return ctx


def _with_scanline_asserts(ctx, *field_names: str):
    """Attach a persona whose scanline selector asserts `field_names`.

    `crosscheck_scanline` reads the persona's declared `asserts` rather than
    looping over every corroboratable field - section 1.3 makes that array the
    persona's statement about which fields THIS stub vouches for. Windstream is why:
    its scan line embeds a billing-cycle date matching neither its bill date nor its
    due date, and checking `due_date` anyway flagged a correct extraction.
    """
    from docintel.grammar.schema import parse_persona

    ctx.persona = parse_persona({
        "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
        "rule_version": "v1", "status": "active", "layout_fingerprint": {},
        "field_selectors": [{
            "scanline": True, "region": "remittance-block",
            "asserts": [{"field": n, "as": "digits_only"} for n in field_names],
        }],
    })
    return ctx


# --------------------------------------------------------------------------
# The governing invariant
# --------------------------------------------------------------------------


SCORING_OPS = (
    crosscheck.crosscheck_line_sum,
    crosscheck.crosscheck_total_composition,
    crosscheck.crosscheck_balance_composition,
    crosscheck.crosscheck_scanline,
    crosscheck.crosscheck_duplicate_anchor,
    crosscheck.crosscheck_filename,
)


@pytest.mark.parametrize("op", SCORING_OPS, ids=lambda o: o.__name__)
def test_no_crosscheck_op_changes_an_extracted_value(op) -> None:
    """Section 4.3 is titled "scoring only, never value-changing"."""
    ctx = _ctx(
        total_printed=Decimal("367.96"),
        subtotal=Decimal("298.34"),
        current_charges=Decimal("69.62"),
        tax_amount=Decimal("0.00"),
        invoice_number="6060",
        account_number="077087",
    )
    ctx.row_groups["line_items"] = [{"amount": Decimal("1.00")}]
    ctx.row_groups["charges"] = [{"label": "FUEL", "amount": Decimal("2.00")}]
    ctx.scanline = "25600770871000367962"
    ctx.derived.set("carried_balance", Decimal("298.34"))

    before = dict(ctx.extracted.values)
    op(ctx)
    assert dict(ctx.extracted.values) == before


@pytest.mark.parametrize("op", SCORING_OPS, ids=lambda o: o.__name__)
def test_every_crosscheck_op_is_a_noop_on_an_empty_context(op) -> None:
    ctx = new_context("d", "/x.pdf")
    op(ctx)
    assert dict(ctx.extracted.values) == {}
    assert ctx.boosts == {}


# --------------------------------------------------------------------------
# crosscheck_line_sum
# --------------------------------------------------------------------------


def test_line_sum_boosts_when_it_closes_against_the_subtotal() -> None:
    """Veritiv: line items sum to 4608.45, exactly the printed subtotal."""
    ctx = _ctx(subtotal=Decimal("4608.45"))
    ctx.row_groups["line_items"] = [{"amount": Decimal("4608.45")}]
    ctx = crosscheck.crosscheck_line_sum(ctx)
    assert ctx.boosts.get("subtotal") == 1
    assert "arith_lines_mismatch" not in ctx.modifiers


def test_line_sum_flags_when_it_does_not_close() -> None:
    ctx = _ctx(subtotal=Decimal("4608.45"))
    ctx.row_groups["line_items"] = [{"amount": Decimal("100.00")}]
    ctx = crosscheck.crosscheck_line_sum(ctx)
    assert "arith_lines_mismatch" in ctx.modifiers


def test_line_sum_skips_a_document_with_no_printed_subtotal() -> None:
    """This is what keeps EDCO out of the check, and it matters.

    EDCO's statement table prints its own `CURRENT CHARGES:` summary row inside
    the table body, so its amount columns sum to 805.54 against a printed total
    of 367.96 - faithfully transcribed, not an error. EDCO prints no subtotal, so
    the op skips it rather than flagging a document that is entirely correct.
    """
    ctx = _ctx(total_printed=Decimal("367.96"))
    ctx.row_groups["line_items"] = [
        {"description": "BALANCE FORWARD", "balance": Decimal("298.34")},
        {"description": "CANCEL SERVICE", "charges": Decimal("69.62")},
        {"description": "CURRENT CHARGES:", "charges": Decimal("69.62"),
         "balance": Decimal("367.96")},
    ]
    ctx = crosscheck.crosscheck_line_sum(ctx)
    assert "arith_lines_mismatch" not in ctx.modifiers
    assert ctx.boosts == {}


def test_line_sum_ignores_rate_and_quantity_columns() -> None:
    """Summing unit_price would be meaningless and would fail the check for a
    reason that says nothing about extraction quality."""
    ctx = _ctx(subtotal=Decimal("550.00"))
    ctx.row_groups["line_items"] = [
        {"quantity": 1, "unit_price": Decimal("550.00"), "amount": Decimal("550.00")},
    ]
    ctx = crosscheck.crosscheck_line_sum(ctx)
    assert ctx.boosts.get("subtotal") == 1


# --------------------------------------------------------------------------
# crosscheck_total_composition - two vendors, two compositions
# --------------------------------------------------------------------------


def test_upak_composes_as_subtotal_plus_charges() -> None:
    """Measured: 8119.44 + 6670.33 == 14789.77, with its H.S.T. already inside."""
    ctx = _ctx(
        total_printed=Decimal("14789.77"),
        subtotal=Decimal("8119.44"),
        tax_amount=Decimal("2325.69"),
    )
    ctx.row_groups["charges"] = [
        {"label": "FUEL SURCHARGE", "amount": Decimal("1218.04")},
        {"label": "ENVIRONMENTAL SURCHARGE", "amount": Decimal("2342.42")},
        {"label": "EFW COMPLIANCE CHRG", "amount": Decimal("3109.87")},
    ]
    ctx = crosscheck.crosscheck_total_composition(ctx)
    assert ctx.boosts.get("total_printed") == 1
    assert "arith_total_mismatch" not in ctx.modifiers


def test_veritiv_composes_as_subtotal_plus_tax() -> None:
    """Measured: 4608.45 + 299.55 == 4908.00, with no surcharges at all.

    A single fixed formula cannot serve both this and U-PAK above, which is why
    the op tries every plausible decomposition and boosts if any closes.
    """
    ctx = _ctx(
        total_printed=Decimal("4908.00"),
        subtotal=Decimal("4608.45"),
        tax_amount=Decimal("299.55"),
    )
    ctx = crosscheck.crosscheck_total_composition(ctx)
    assert ctx.boosts.get("total_printed") == 1
    assert "arith_total_mismatch" not in ctx.modifiers


def test_total_composition_flags_when_no_decomposition_closes() -> None:
    ctx = _ctx(
        total_printed=Decimal("9999.99"),
        subtotal=Decimal("100.00"),
        tax_amount=Decimal("10.00"),
    )
    ctx = crosscheck.crosscheck_total_composition(ctx)
    assert "arith_total_mismatch" in ctx.modifiers


def test_total_composition_needs_a_subtotal() -> None:
    ctx = _ctx(total_printed=Decimal("699.00"))
    ctx = crosscheck.crosscheck_total_composition(ctx)
    assert ctx.boosts == {}
    assert "arith_total_mismatch" not in ctx.modifiers


# --------------------------------------------------------------------------
# crosscheck_balance_composition
# --------------------------------------------------------------------------


def test_balance_composition_boosts_on_centracom() -> None:
    ctx = _ctx(total_printed=Decimal("33876.40"), current_charges=Decimal("13752.60"))
    ctx.derived.set("carried_balance", Decimal("20123.80"))
    ctx = crosscheck.crosscheck_balance_composition(ctx)
    assert ctx.boosts.get("total_printed") == 1
    assert ctx.boosts.get("current_charges") == 1
    assert ctx.review_flag is False


def test_balance_composition_uses_the_carried_balance_not_the_raw_prior() -> None:
    """Comcast: the raw prior 212.87 double-counts a payment already made, so
    212.87 + 221.11 = 433.98 against a printed 221.11. Against the carried
    balance of zero the op correctly does not run at all."""
    ctx = _ctx(
        total_printed=Decimal("221.11"),
        prior_balance=Decimal("212.87"),
        current_charges=Decimal("221.11"),
    )
    ctx.derived.set("carried_balance", Decimal("0.00"))
    ctx = crosscheck.crosscheck_balance_composition(ctx)
    assert "arith_balance_mismatch" not in ctx.modifiers
    assert ctx.review_flag is False


def test_balance_composition_flags_and_raises_review_when_it_fails() -> None:
    """The harshest modifier in the enum, because this is the arithmetic that
    decides what gets paid."""
    ctx = _ctx(total_printed=Decimal("999.99"), current_charges=Decimal("69.62"))
    ctx.derived.set("carried_balance", Decimal("298.34"))
    ctx = crosscheck.crosscheck_balance_composition(ctx)
    assert "arith_balance_mismatch" in ctx.modifiers
    assert ctx.review_flag is True


# --------------------------------------------------------------------------
# crosscheck_scanline - F7
# --------------------------------------------------------------------------


def test_the_scanline_corroborates_the_printed_total() -> None:
    """EDCO's stub encodes 367.96 as ...367962."""
    ctx = _with_scanline_asserts(_ctx(total_printed=Decimal("367.96")), "total_printed")
    ctx.scanline = "25600770871000367962"
    ctx = crosscheck.crosscheck_scanline(ctx)
    assert ctx.boosts.get("total_printed") == 1


def test_a_scanline_disagreement_lowers_confidence() -> None:
    ctx = _with_scanline_asserts(_ctx(total_printed=Decimal("999.99")), "total_printed")
    ctx.scanline = "25600770871000367962"
    ctx = crosscheck.crosscheck_scanline(ctx)
    assert "scanline_mismatch" in ctx.modifiers


def test_the_scanline_never_corroborates_a_derived_payable() -> None:
    """Centracom's scan line encodes the MISLEADING headline total (33876.40),
    not the 13752.60 that is actually payable. A scan line "confirming" the
    payable would confirm the wrong number, so amount_payable is not in
    CORROBORATABLE_FIELDS and this op never asks about it."""
    ctx = _with_scanline_asserts(_ctx(total_printed=Decimal("33876.40")), "total_printed")
    ctx.derived.set("amount_payable", Decimal("13752.60"))
    ctx.scanline = "03840384043574000033876408"
    ctx = crosscheck.crosscheck_scanline(ctx)
    assert "amount_payable" not in ctx.boosts
    assert ctx.boosts.get("total_printed") == 1


def test_no_scanline_is_a_noop() -> None:
    ctx = _ctx(total_printed=Decimal("367.96"))
    ctx = crosscheck.crosscheck_scanline(ctx)
    assert ctx.boosts == {}
    assert "scanline_mismatch" not in ctx.modifiers


# --------------------------------------------------------------------------
# crosscheck_duplicate_anchor - F12
# --------------------------------------------------------------------------


def test_two_agreeing_occurrences_corroborate() -> None:
    ctx = _ctx(total_printed=[Decimal("367.96"), Decimal("367.96")])
    ctx = crosscheck.crosscheck_duplicate_anchor(ctx)
    assert ctx.boosts.get("total_printed") == 1
    assert ctx.review_flag is False


def test_two_disagreeing_occurrences_raise_review_and_pick_nothing() -> None:
    """F12: the body says one thing and the stub another. A silent pick here is
    exactly the failure mode this design refuses."""
    ctx = _ctx(total_printed=[Decimal("367.96"), Decimal("376.96")])
    ctx = crosscheck.crosscheck_duplicate_anchor(ctx)
    assert ctx.review_flag is True
    assert ctx.extracted.get("total_printed") == [Decimal("367.96"), Decimal("376.96")]


def test_a_single_occurrence_is_not_a_duplicate() -> None:
    ctx = _ctx(total_printed=Decimal("367.96"))
    ctx = crosscheck.crosscheck_duplicate_anchor(ctx)
    assert ctx.boosts == {}


# --------------------------------------------------------------------------
# crosscheck_filename - F17
# --------------------------------------------------------------------------


def test_the_filename_agrees_when_it_carries_the_invoice_number() -> None:
    """The corpus filenames are real evidence - one is literally named
    "current charges can be misleading, paying $69.62"."""
    ctx = _ctx(invoice_number="6060")
    ctx = crosscheck.crosscheck_filename(ctx)
    assert ctx.derived.get("filename_crosscheck") == "agree"
    assert ctx.boosts.get("invoice_number") == 1


def test_the_filename_agrees_on_the_total_when_the_invoice_number_is_absent() -> None:
    ctx = _ctx(total_printed=Decimal("699.00"))
    ctx = crosscheck.crosscheck_filename(ctx)
    assert ctx.derived.get("filename_crosscheck") == "agree"


def test_the_filename_disagrees_when_it_carries_different_digits() -> None:
    ctx = _ctx(invoice_number="999999")
    ctx = crosscheck.crosscheck_filename(ctx)
    assert ctx.derived.get("filename_crosscheck") == "disagree"
    assert "filename_disagree" in ctx.modifiers


def test_a_filename_with_no_digits_is_absent_not_a_disagreement() -> None:
    ctx = new_context("d", "/docs/scan.pdf")
    ctx.extracted.set("invoice_number", "6060", 1.0)
    ctx = crosscheck.crosscheck_filename(ctx)
    assert ctx.derived.get("filename_crosscheck") == "absent"
    assert "filename_disagree" not in ctx.modifiers


def test_a_two_digit_value_is_too_short_to_crosscheck() -> None:
    """Almost any filename containing a date would "confirm" it."""
    ctx = _ctx(invoice_number="60")
    ctx = crosscheck.crosscheck_filename(ctx)
    assert ctx.derived.get("filename_crosscheck") == "absent"


def test_the_filename_is_never_authoritative() -> None:
    """A disagreement lowers confidence by the gentlest modifier in the enum and
    changes no value: a filename is a human note, not a source of truth."""
    ctx = _ctx(invoice_number="999999")
    ctx = crosscheck.crosscheck_filename(ctx)
    assert ctx.extracted.get("invoice_number") == "999999"


def test_the_persona_decides_which_fields_the_scanline_vouches_for() -> None:
    """Windstream's scan line embeds `250719`, a BILLING CYCLE date matching neither
    its bill date (07-22) nor its due date (08-11). Its persona asserts only
    `total_printed` and `account_number`, and checking `due_date` anyway applied
    `scanline_mismatch` to a correctly-extracted field and cost the document its lane.

    Section 1.3's permitted set is still the ceiling, enforced at write time by V7.
    This is the persona choosing from within it.
    """
    ctx = _with_scanline_asserts(
        _ctx(total_printed=Decimal("1230.14"), due_date="2025-08-11"),
        "total_printed",
    )
    ctx.scanline = "7000444000000004106907622507190000012301446"
    ctx = crosscheck.crosscheck_scanline(ctx)
    assert ctx.boosts.get("total_printed") == 1
    assert "scanline_mismatch" not in ctx.modifiers


def test_a_value_with_too_few_digits_is_neither_boosted_nor_flagged() -> None:
    """Centracom's due date is printed `25TH OF THE MONTH` (F9) - two digits, below
    the coincidence floor. `corroborates` returning False there means "cannot tell",
    not "disagrees", and reading it as a mismatch cost the document its lane."""
    ctx = _with_scanline_asserts(_ctx(due_date="25TH OF THE MONTH"), "due_date")
    ctx.scanline = "03840384043574000033876408"
    ctx = crosscheck.crosscheck_scanline(ctx)
    assert "scanline_mismatch" not in ctx.modifiers
    assert ctx.boosts == {}


def test_an_account_number_object_is_matched_on_its_own_digits() -> None:
    """`str()` on an AccountNumber yields the dataclass repr, which DOUBLES its
    digits and matches nothing. Comcast's account IS in its scan line."""
    from docintel.grammar.patterns import NAMED

    ctx = _with_scanline_asserts(
        _ctx(account_number=NAMED["account_number"]("8495 44 462 0365242")),
        "account_number",
    )
    ctx.scanline = "849544462036524200221119"
    ctx = crosscheck.crosscheck_scanline(ctx)
    assert ctx.boosts.get("account_number") == 1
    assert "scanline_mismatch" not in ctx.modifiers
