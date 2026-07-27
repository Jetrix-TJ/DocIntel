import pytest
from docintel.core.dates import parse_date


@pytest.mark.parametrize("raw,iso", [
    ("9/15/2025", "2025-09-15"),            # D.T.S.S.
    ("08/14/2025", "2025-08-14"),           # Veritiv
    ("10/24/2025", "2025-10-24"),           # Complete Beverage
    ("05/31/2025", "2025-05-31"),           # Federal Recycling
    ("Dec 09, 2025", "2025-12-09"),         # Comcast
    ("September 01, 2025", "2025-09-01"),   # Lumen
    ("January 01, 2026", "2026-01-01"),     # Centracom
    ("July 22, 2025", "2025-07-22"),        # Windstream
    ("MARCH 31, 2025", "2025-03-31"),       # U-Pak service dates, all caps
])
def test_parse_date(raw, iso):
    r = parse_date(raw)
    assert r.parsed is True
    assert r.iso == iso
    assert r.ambiguous_two_digit_year is False


def test_two_digit_year_parses_but_is_flagged():
    """U-Pak 03/31/25 and EDCO 04/30/25 - resolvable but must carry a penalty."""
    r = parse_date("03/31/25")
    assert r.iso == "2025-03-31"
    assert r.ambiguous_two_digit_year is True


@pytest.mark.parametrize("raw", [
    "25TH OF THE MONTH",   # Centracom due date - NOT a date (F9)
    "EOM plus 15",         # Federal Recycling payment terms
    "Due on receipt",      # D.T.S.S.
    "Net 30",
    "",
])
def test_unparseable_passes_through_without_inventing_a_day(raw):
    r = parse_date(raw)
    assert r.parsed is False
    assert r.iso is None
    assert r.raw == raw
