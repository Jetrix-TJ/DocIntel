from decimal import Decimal
import pytest
from docintel.core.money import parse_money, is_money


@pytest.mark.parametrize("raw,expected", [
    # plain
    ("699.00", Decimal("699.00")),
    ("1,177.70", Decimal("1177.70")),
    ("$1,177.70", Decimal("1177.70")),
    ("4,908.00", Decimal("4908.00")),
    ("83.7900", Decimal("83.7900")),        # Veritiv unit price, 4dp
    ("0.027", Decimal("0.027")),            # CBD environmental fee
    ("$.00", Decimal("0.00")),              # Windstream "Amount Previously Due"
    # negatives, three notations
    ("-99.80", Decimal("-99.80")),          # Federal Recycling OCC
    ("-40.500", Decimal("-40.500")),        # U-Pak cardboard weights
    ("(249.84)", Decimal("-249.84")),       # Lumen payment received
    ("212.87 cr", Decimal("-212.87")),      # Comcast credit card payment
    ("$1,231.74 CR", Decimal("-1231.74")),  # Windstream payments/adjustments
    ("$-161.95", Decimal("-161.95")),       # Spectrum/Charter "Payments" line
    ("$-1,140.29", Decimal("-1140.29")),    # same notation, with thousands separator
    # currency suffix
    ("481.20 USD", Decimal("481.20")),
    ("14789.77", Decimal("14789.77")),
    # rate notation - the number only
    ("-40.00/ST", Decimal("-40.00")),
])
def test_parse_money(raw, expected):
    assert parse_money(raw) == expected


@pytest.mark.parametrize("raw", [
    "123142812RT0001",   # U-Pak HST registration number - NOT money (F14)
    "0384043574",        # Centracom account number
    "8495 44 462 0365242",
    "416-675-3700",
    "NO MARKET VALUE",
    "",
    "Total",
])
def test_not_money(raw):
    assert parse_money(raw) is None
    assert is_money(raw) is False


def test_exact_decimal_no_float_drift():
    """The F8 closure checks demand exact equality, so parsing must not go via float."""
    assert parse_money("298.34") + parse_money("69.62") == Decimal("367.96")
    assert parse_money("13752.60") + parse_money("20123.80") == Decimal("33876.40")
    assert parse_money("0.027") * Decimal(4000) == Decimal("108.000")


def test_tax_id_is_not_money_even_though_it_has_digits():
    """H.S.T. # 123142812RT0001   2,325.69 - a naive number grab takes the wrong token."""
    assert parse_money("123142812RT0001") is None
    assert parse_money("2,325.69") == Decimal("2325.69")
