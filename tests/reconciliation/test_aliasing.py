"""Account/circuit-ID canonicalization - genuinely greenfield before this
phase, so this is the first test coverage this exact question has ever had.
"""

from __future__ import annotations

from docintel.reconciliation.aliasing import canonicalize_account_key


def test_none_and_empty_are_none() -> None:
    assert canonicalize_account_key(None) is None
    assert canonicalize_account_key("") is None
    assert canonicalize_account_key("   ") is None


def test_a_bare_number_is_unchanged_but_uppercased() -> None:
    assert canonicalize_account_key("2110613") == "2110613"


def test_a_circuit_prefix_is_stripped() -> None:
    assert canonicalize_account_key("CKT-12345") == "12345"
    assert canonicalize_account_key("Circuit# 12345") == "12345"
    assert canonicalize_account_key("circuit 12345") == "12345"


def test_a_quote_prefix_is_stripped() -> None:
    """The real Golub renderings this module was built against."""
    assert canonicalize_account_key("Quote #: 2110613") == "2110613"
    assert canonicalize_account_key("Quote# 2494434") == "2494434"
    assert canonicalize_account_key("Quote # 2110613") == "2110613"


def test_an_account_prefix_is_stripped() -> None:
    assert canonicalize_account_key("Account: 041069076") == "041069076"
    assert canonicalize_account_key("Acct # 041069076") == "041069076"


def test_different_renderings_of_the_same_key_canonicalize_identically() -> None:
    assert (
        canonicalize_account_key("CKT-12345")
        == canonicalize_account_key("Circuit# 12345")
        == canonicalize_account_key("circuit 12345")
    )


def test_a_hyphenated_account_number_with_no_label_keeps_its_digits() -> None:
    """`5-QXH7QKM7`-shaped Lumen account numbers have no label to strip - the
    hyphen and letters are part of the identifier itself, not punctuation to
    discard."""
    assert canonicalize_account_key("5-QXH7QKM7") == "5QXH7QKM7"
