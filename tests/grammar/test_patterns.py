"""The pattern vocabulary is closed (selector-grammar.md section 3).

Two classes of test live here and they are not interchangeable:

* Corpus tests use tokens copied out of the 10 sample PDFs. They prove
  corpus-fit and, per the standing rule from C1b, they CANNOT detect
  corpus-overfit.
* Synthetic tests cover notations the corpus does not happen to contain but a
  real invoice plainly could. They are the only defence against a pattern that
  passes all ten documents by accident.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from docintel.core.errors import ValidationError
from docintel.grammar.patterns import NAMED, compile_restricted


# --------------------------------------------------------------------------
# The closed vocabulary itself
# --------------------------------------------------------------------------


def test_all_thirteen_named_patterns_exist() -> None:
    """The pattern vocabulary is closed - selector-grammar.md section 3.1."""
    assert set(NAMED) == {
        "currency", "currency_signed", "integer", "decimal", "date", "date_loose",
        "text", "text_block", "account_number", "phone", "postal_code", "tax_id",
        "digits_run",
    }


def test_every_named_pattern_returns_none_for_empty_input() -> None:
    """No pattern may invent a value out of nothing."""
    for name, fn in NAMED.items():
        assert fn("") is None, f"{name} accepted the empty string"
        assert fn("   ") is None, f"{name} accepted whitespace"


# --------------------------------------------------------------------------
# currency - the F4 sign hazard
# --------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("1,234.56", Decimal("1234.56")),      # Veritiv
    ("-99.80", Decimal("-99.80")),         # Federal Recycling line amount
    ("(249.84)", Decimal("-249.84")),      # Lumen "Payment Received"
    ("$367.96", Decimal("367.96")),        # EDCO headline box
    ("481.20 USD", Decimal("481.20")),
    ("212.87 cr", Decimal("-212.87")),     # Comcast credit-card payment
    ("212.87 CR", Decimal("-212.87")),
])
def test_currency_accepts_every_corpus_notation(raw: str, expected: Decimal) -> None:
    assert NAMED["currency"](raw) == expected


def test_currency_never_takes_absolute_value() -> None:
    """F4: a credit that comes back positive silently inflates the payable."""
    for raw in ("-99.80", "(249.84)", "212.87 cr"):
        value = NAMED["currency"](raw)
        assert value is not None and value < 0, f"{raw} lost its sign"


def test_tax_id_and_currency_are_mutually_exclusive() -> None:
    """H.S.T. # 123142812RT0001  2,325.69 - the anchor hazard from F14."""
    assert NAMED["tax_id"]("123142812RT0001") is not None
    assert NAMED["currency"]("123142812RT0001") is None


@pytest.mark.parametrize("raw", [
    "4670",              # a bare integer is not currency - no decimal part
    "N1G 4N4",           # postal code
    "416-675-3700",      # phone
    "8495 44 462 0365242",
    "1.2.3",
    "abc",
    "$",
])
def test_currency_rejects_non_money(raw: str) -> None:
    assert NAMED["currency"](raw) is None


def test_currency_signed_requires_an_explicit_sign() -> None:
    """Synthetic: separates "a negative was printed" from "we assumed positive"."""
    assert NAMED["currency_signed"]("-99.80") == Decimal("-99.80")
    assert NAMED["currency_signed"]("(249.84)") == Decimal("-249.84")
    assert NAMED["currency_signed"]("212.87 cr") == Decimal("-212.87")
    assert NAMED["currency_signed"]("+99.80") == Decimal("99.80")
    assert NAMED["currency_signed"]("1,234.56") is None


def test_currency_signed_accepts_the_sign_on_either_side_of_the_symbol() -> None:
    """Spectrum/Charter Communications prints its "Payments" line as
    "$-161.95" - the sign after the currency symbol, not before it."""
    assert NAMED["currency_signed"]("$-161.95") == Decimal("-161.95")
    assert NAMED["currency_signed"]("-$161.95") == Decimal("-161.95")
    assert NAMED["currency_signed"]("$161.95") is None  # still requires a sign


# --------------------------------------------------------------------------
# integer / decimal
# --------------------------------------------------------------------------


def test_integer_accepts_grouped_and_bare() -> None:
    assert NAMED["integer"]("4670") == 4670
    assert NAMED["integer"]("1,070") == 1070


@pytest.mark.parametrize("raw", ["2.495", "1,07", "12,34", "", "4 670"])
def test_integer_rejects_non_integers(raw: str) -> None:
    """Synthetic: "1,07" is a mis-OCR'd group, not the number 107."""
    assert NAMED["integer"](raw) is None


def test_decimal_accepts_corpus_quantities() -> None:
    assert NAMED["decimal"]("2.495") == Decimal("2.495")
    assert NAMED["decimal"]("83.7900") == Decimal("83.7900")


def test_decimal_preserves_trailing_zeros() -> None:
    """83.7900 and 83.79 are different printed precisions; keep what was printed."""
    result = NAMED["decimal"]("83.7900")
    assert str(result) == "83.7900"


def test_decimal_requires_a_decimal_point() -> None:
    assert NAMED["decimal"]("4670") is None


# --------------------------------------------------------------------------
# dates
# --------------------------------------------------------------------------


@pytest.mark.parametrize("raw,iso", [
    ("9/15/2025", "2025-09-15"),
    ("08/14/2025", "2025-08-14"),
    ("Dec 09, 2025", "2025-12-09"),
    ("September 01, 2025", "2025-09-01"),
    ("January 01, 2026", "2026-01-01"),
])
def test_date_normalizes_to_iso(raw: str, iso: str) -> None:
    result = NAMED["date"](raw)
    assert result is not None and result.iso == iso


def test_two_digit_year_parses_but_is_flagged_ambiguous() -> None:
    """03/31/25 - the confidence penalty is applied downstream, not here."""
    result = NAMED["date"]("03/31/25")
    assert result is not None
    assert result.iso == "2025-03-31"
    assert result.ambiguous_two_digit_year is True


def test_date_rejects_what_it_cannot_parse() -> None:
    """A strict `date` selector must miss rather than pass junk through."""
    assert NAMED["date"]("25TH OF THE MONTH") is None
    assert NAMED["date"]("EOM plus 15") is None


def test_date_loose_passes_unparsed_text_through() -> None:
    """F9: Centracom's due date is literally "25TH OF THE MONTH"."""
    result = NAMED["date_loose"]("25TH OF THE MONTH")
    assert result is not None
    assert result.parsed is False
    assert result.iso is None
    assert result.raw == "25TH OF THE MONTH"


def test_date_loose_still_parses_what_it_can() -> None:
    result = NAMED["date_loose"]("MARCH 31, 2025")
    assert result is not None and result.iso == "2025-03-31"


def test_date_rejects_impossible_calendar_dates() -> None:
    """Synthetic: a mis-OCR'd 13 must not become a silent January."""
    assert NAMED["date"]("13/45/2025") is None


# --------------------------------------------------------------------------
# text
# --------------------------------------------------------------------------


def test_text_takes_one_line_only() -> None:
    assert NAMED["text"]("EDCO Waste & Recycling") == "EDCO Waste & Recycling"
    assert NAMED["text"]("first line\nsecond line") == "first line"


def test_text_block_keeps_the_line_structure() -> None:
    """For addresses, where the newlines carry the meaning."""
    raw = "6670 Federal Blvd\nLemon Grove, CA 91945"
    assert NAMED["text_block"](raw) == raw


def test_text_strips_surrounding_whitespace_but_not_internal() -> None:
    assert NAMED["text"]("  A  B  ") == "A  B"


# --------------------------------------------------------------------------
# account_number - F6
# --------------------------------------------------------------------------


def test_account_number_preserves_and_normalizes() -> None:
    result = NAMED["account_number"]("8495 44 462 0365242")
    assert result.raw == "8495 44 462 0365242"
    assert result.normalized == "8495444620365242"


def test_account_number_normalizes_dashes_too() -> None:
    """Synthetic: Windstream-style dashed accounts must reach the same key."""
    result = NAMED["account_number"]("041-069-076")
    assert result is not None
    assert result.raw == "041-069-076"
    assert result.normalized == "041069076"


def test_account_number_keeps_letters() -> None:
    """Lumen's 5-QXH7QKM7 is alphanumeric; stripping letters would collide."""
    result = NAMED["account_number"]("5-QXH7QKM7")
    assert result is not None and result.normalized == "5QXH7QKM7"


def test_account_number_rejects_a_bare_short_run() -> None:
    """Synthetic: without a floor, every stray word becomes an account number."""
    assert NAMED["account_number"]("A") is None
    assert NAMED["account_number"]("-- --") is None


# --------------------------------------------------------------------------
# phone / postal_code / tax_id / digits_run
# --------------------------------------------------------------------------


def test_phones_parse() -> None:
    """The pattern only validates shape - it returns the raw string, stripped,
    never reformatted."""
    assert NAMED["phone"]("416-675-3700") == "416-675-3700"
    assert NAMED["phone"]("918-653-3103") == "918-653-3103"


@pytest.mark.parametrize(
    "raw",
    ["(416) 675-3700", "416.675.3700", "1-416-675-3700"],
)
def test_phone_accepts_common_alternate_notations(raw: str) -> None:
    """Synthetic: the corpus only shows one notation; real vendors use
    several. Returned exactly as printed - `phone` never reformats a number
    into a canonical shape, only validates it looks like one."""
    assert NAMED["phone"](raw) == raw


def test_phone_rejects_a_number_with_too_few_digits() -> None:
    assert NAMED["phone"]("416-675") is None


def test_canadian_postal_codes_parse_and_normalize_to_upper_with_one_space() -> None:
    assert NAMED["postal_code"]("N1G 4N4") == "N1G 4N4"
    assert NAMED["postal_code"]("M9W 7E9") == "M9W 7E9"
    # Lowercase, no internal space - the same code, printed differently.
    assert NAMED["postal_code"]("n1g4n4") == "N1G 4N4"


def test_us_zip_codes_parse_unmodified() -> None:
    assert NAMED["postal_code"]("45887") == "45887"
    assert NAMED["postal_code"]("01028-2744") == "01028-2744"


def test_postal_code_rejects_a_seven_digit_run() -> None:
    """F11: an unscoped digit run must not read as a zip code."""
    assert NAMED["postal_code"]("4378107") is None


def test_tax_id_normalizes_case_and_reassembles_the_three_groups() -> None:
    """H.S.T. # 123142812RT0001 - the anchor hazard from F14. Proven with a
    lowercase middle group so a passing assertion cannot be satisfied by a
    pattern that merely echoes its input back unchanged."""
    assert NAMED["tax_id"]("123142812RT0001") == "123142812RT0001"
    assert NAMED["tax_id"]("123142812rt0001") == "123142812RT0001"
    assert NAMED["tax_id"]("123142812 RT 0001") == "123142812RT0001"


def test_tax_id_rejects_a_plain_account_number() -> None:
    """Synthetic: tax_id is narrow on purpose - it guards the H.S.T. anchor."""
    assert NAMED["tax_id"]("8495444620365242") is None


def test_digits_run_needs_at_least_ten_digits() -> None:
    """F7: the scanline. Ten is the floor that keeps invoice numbers out."""
    assert NAMED["digits_run"]("25600770871000367962") == "25600770871000367962"
    assert NAMED["digits_run"]("4378107") is None


def test_digits_run_allows_internal_spaces_and_strips_them() -> None:
    result = NAMED["digits_run"]("8495 44 462 0365242")
    assert result == "8495444620365242"


# --------------------------------------------------------------------------
# Restricted regex - section 3.2
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad,reason", [
    (".*", "unbounded"),
    ("(a)(b)", "capture group"),
    ("x" * 250, "200"),
    (r"(?<=foo)bar", "lookbehind"),
    (r"(a)\1", "backreference"),
])
def test_restricted_regex_rejects_dangerous_patterns(bad: str, reason: str) -> None:
    with pytest.raises(ValidationError, match=reason):
        compile_restricted(bad)


def test_bounded_quantifier_is_allowed() -> None:
    assert compile_restricted(r"NS\s?#\s?(\d{7})") is not None
    assert compile_restricted(r".{0,80}") is not None


@pytest.mark.parametrize("bad", [".+", r"\d*", r"(?:ab)+", r"a{2,}", "[a-z]*"])
def test_every_unbounded_quantifier_form_is_rejected(bad: str) -> None:
    """Synthetic: the plan only names `.*`. `\\d*` is exactly as unbounded."""
    with pytest.raises(ValidationError, match="unbounded"):
        compile_restricted(bad)


@pytest.mark.parametrize("bad", [r"(?>ab)", r"a*+", r"a++"])
def test_atomic_and_possessive_groups_are_rejected(bad: str) -> None:
    """Section 3.2 bans them by name; they also break the linear-time claim."""
    with pytest.raises(ValidationError):
        compile_restricted(bad)


def test_non_capturing_groups_do_not_count_against_the_capture_limit() -> None:
    assert compile_restricted(r"(?:Invoice|INV)\s?#\s?(\d{4,10})") is not None


def test_zero_capture_groups_is_allowed() -> None:
    """A pattern used only to confirm presence needs no capture."""
    assert compile_restricted(r"BALANCE FORWARD") is not None


def test_a_syntactically_invalid_regex_is_a_validation_error() -> None:
    """Never a raw re.error escaping into the persona-write path."""
    with pytest.raises(ValidationError, match="invalid"):
        compile_restricted("(unclosed")


def test_exactly_two_hundred_characters_is_allowed() -> None:
    """Boundary: the limit is "max 200", not "under 200"."""
    assert compile_restricted("a" * 200) is not None


def test_nested_bounded_quantifiers_are_rejected() -> None:
    """Synthetic and important: (a{0,20}){0,20} is bounded at every level and
    still exponential. Bounded-ness alone does not buy linear time, so the
    static check has to reject nesting rather than trust the 50ms budget."""
    with pytest.raises(ValidationError, match="nested"):
        compile_restricted(r"(?:a{0,20}){0,20}")
