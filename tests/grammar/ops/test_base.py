"""Value ops (section 4.1).

Two properties are asserted for every op in the registry rather than one at a
time, because both are easy to break in a single-op edit:

* idempotence - a persona may declare `trim` beside a pattern that already
  trimmed, and Stage 6 must not care
* safety on an already-parsed value - `patterns.currency` hands over a signed
  Decimal, so `parens_to_negative` is usually given a value whose parentheses
  are already resolved. Double-negating it would turn Lumen's credit back into
  a charge.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from docintel.grammar.ops.base import VALUE_OPS

SAMPLES: list[Any] = [
    "8495 44 462 0365242", "$1,177.70", "(249.84)", "212.87 cr", "9/15/2025",
    "  padded  ", "EDCO Waste", Decimal("-249.84"), Decimal("367.96"), 4670,
    None, ["a", "b", "a"], "",
]


# --------------------------------------------------------------------------
# Registry-wide properties
# --------------------------------------------------------------------------


def test_the_registry_holds_the_ten_ops_from_section_4_1() -> None:
    assert set(VALUE_OPS) == {
        "strip_internal_whitespace", "strip_currency_symbols", "parens_to_negative",
        "trailing_cr_to_negative", "normalize_date_iso", "uppercase", "lowercase",
        "trim", "collapse_internal_spaces", "dedupe_preserve_order",
    }


@pytest.mark.parametrize("name", sorted(VALUE_OPS))
@pytest.mark.parametrize("value", SAMPLES)
def test_every_op_is_idempotent(name: str, value: Any) -> None:
    op = VALUE_OPS[name]
    once = op(value)
    assert op(once) == once, f"{name} is not idempotent on {value!r}"


@pytest.mark.parametrize("name", sorted(VALUE_OPS))
@pytest.mark.parametrize("value", SAMPLES)
def test_no_op_raises_on_any_plausible_value(name: str, value: Any) -> None:
    """A value op runs on whatever the selector captured, including None."""
    VALUE_OPS[name](value)


@pytest.mark.parametrize("name", sorted(VALUE_OPS))
def test_no_op_turns_a_negative_decimal_positive(name: str) -> None:
    """F4, applied to the op layer: a credit that comes back positive silently
    inflates the payable, and three of these ops are about signs."""
    result = VALUE_OPS[name](Decimal("-249.84"))
    if isinstance(result, Decimal):
        assert result < 0, f"{name} flipped a credit to {result}"


# --------------------------------------------------------------------------
# Individual behaviour
# --------------------------------------------------------------------------


def test_strip_internal_whitespace() -> None:
    """F6: the joinable form of Comcast's account number."""
    assert VALUE_OPS["strip_internal_whitespace"]("8495 44 462 0365242") == "8495444620365242"


def test_collapse_internal_spaces_keeps_one_space() -> None:
    assert VALUE_OPS["collapse_internal_spaces"]("EDCO   Waste  &  Recycling") == (
        "EDCO Waste & Recycling"
    )


@pytest.mark.parametrize("raw,expected", [
    ("$1,177.70", Decimal("1177.70")),
    ("481.20 USD", Decimal("481.20")),
    ("£99.00", Decimal("99.00")),
])
def test_strip_currency_symbols_yields_a_decimal(raw: str, expected: Decimal) -> None:
    assert VALUE_OPS["strip_currency_symbols"](raw) == expected


def test_strip_currency_symbols_leaves_non_money_as_text() -> None:
    """Declared on a money field but legal on any field; must not force a number."""
    assert VALUE_OPS["strip_currency_symbols"]("USD account") == "account"


def test_parens_to_negative() -> None:
    assert VALUE_OPS["parens_to_negative"]("(249.84)") == Decimal("-249.84")


def test_parens_to_negative_passes_an_already_signed_decimal_through() -> None:
    """The common case: patterns.currency resolved the parentheses already.
    Re-negating would turn Lumen's credit back into a charge."""
    assert VALUE_OPS["parens_to_negative"](Decimal("-249.84")) == Decimal("-249.84")


def test_trailing_cr_to_negative() -> None:
    assert VALUE_OPS["trailing_cr_to_negative"]("212.87 cr") == Decimal("-212.87")
    assert VALUE_OPS["trailing_cr_to_negative"]("1,231.74 CR") == Decimal("-1231.74")


def test_trailing_cr_does_not_double_negate_an_already_negative_string() -> None:
    assert VALUE_OPS["trailing_cr_to_negative"]("-212.87 cr") == Decimal("-212.87")


def test_normalize_date_iso() -> None:
    assert VALUE_OPS["normalize_date_iso"]("9/15/2025") == "2025-09-15"
    assert VALUE_OPS["normalize_date_iso"]("Dec 09, 2025") == "2025-12-09"


def test_normalize_date_iso_leaves_an_unparseable_date_untouched() -> None:
    """F9: Centracom prints `25TH OF THE MONTH`. Blanking it would destroy the
    only record of what the document actually said."""
    assert VALUE_OPS["normalize_date_iso"]("25TH OF THE MONTH") == "25TH OF THE MONTH"


def test_normalize_date_iso_accepts_a_date_result() -> None:
    from docintel.grammar.patterns import NAMED

    assert VALUE_OPS["normalize_date_iso"](NAMED["date"]("9/15/2025")) == "2025-09-15"


def test_case_ops_and_trim() -> None:
    assert VALUE_OPS["uppercase"]("edco") == "EDCO"
    assert VALUE_OPS["lowercase"]("EDCO") == "edco"
    assert VALUE_OPS["trim"]("  EDCO  ") == "EDCO"


def test_dedupe_preserves_first_seen_order() -> None:
    """Order is evidence: prefer_current_charges_line relies on it surviving."""
    assert VALUE_OPS["dedupe_preserve_order"](["b", "a", "b", "c", "a"]) == ["b", "a", "c"]


def test_dedupe_leaves_a_non_list_alone() -> None:
    assert VALUE_OPS["dedupe_preserve_order"]("abc") == "abc"


def test_dedupe_works_on_decimals() -> None:
    values = [Decimal("69.62"), Decimal("70.00"), Decimal("69.62")]
    assert VALUE_OPS["dedupe_preserve_order"](values) == [Decimal("69.62"), Decimal("70.00")]
