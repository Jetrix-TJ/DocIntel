"""Invoice <-> contract pairing, and the multi-contract-per-account
resolution the real Golub/Windstream relationship actually requires
(corpus-analysis.md F21) - hand-built record fixtures, matching the pattern
already used throughout tests/grammar/ for the same reason: real PDFs are not
needed to test this logic, and the corpus already contains everything a
synthetic pytest fixture would.
"""

from __future__ import annotations

from docintel.reconciliation.match import find_candidates, resolve


def _invoice(**over):
    base = {
        "document_id": "inv-1",
        "sender_fingerprint": "digitaldirection|windstream",
        "doc_type": "telecom_bill",
        "fields": {"account_number": "2110613", "bill_date": "2021-06-01",
                   "current_charges": 100.00},
    }
    base.update(over)
    return base


def _contract(**over):
    base = {
        "document_id": "contract-1",
        "sender_fingerprint": "digitaldirection|windstream",
        "doc_type": "contract",
        "fields": {"contract_number": "2110613", "effective_date": "2020-09-15",
                   "contracted_rate": 100.00},
    }
    base.update(over)
    return base


def test_no_contracts_at_all_is_zero_candidates() -> None:
    result = resolve(_invoice(), [])
    assert result.contract is None
    assert result.ambiguous_contracts == ()


def test_a_contract_for_a_different_carrier_is_not_a_candidate() -> None:
    other_carrier = _contract(sender_fingerprint="northstar|edco")
    result = resolve(_invoice(), [other_carrier])
    assert result.contract is None


def test_a_single_matching_contract_is_used_unconditionally() -> None:
    contract = _contract()
    result = resolve(_invoice(), [contract])
    assert result.contract is contract
    assert result.ambiguous_contracts == ()


def test_matches_by_account_number_against_a_contract_number() -> None:
    """The real shape: an invoice prints an account number, a base contract
    prints its own quote/contract number, and the two are the same
    identifier rendered two different ways."""
    invoice = _invoice(fields={"account_number": "CKT-2110613", "bill_date": "2021-01-01"})
    contract = _contract(fields={"contract_number": "Quote #: 2110613",
                                  "effective_date": "2020-09-15"})
    candidates = find_candidates(invoice, [contract])
    assert candidates == [contract]


def test_two_layered_contracts_resolve_by_effective_date_bracketing() -> None:
    """The real Golub case: a base agreement plus a later amendment, both on
    file for the same account. An invoice billed AFTER the amendment's
    effective date should resolve to the amendment, not the base."""
    base = _contract(
        document_id="base",
        fields={"contract_number": "2110613", "effective_date": "2020-09-15",
                 "contracted_rate": 100.00},
    )
    amendment = _contract(
        document_id="amendment",
        fields={"supersedes_contract_number": "2110613", "effective_date": "2022-01-01",
                 "contracted_rate": 150.00},
    )
    invoice = _invoice(fields={"account_number": "2110613", "bill_date": "2022-06-01"})
    result = resolve(invoice, [base, amendment])
    assert result.contract is amendment
    assert result.ambiguous_contracts == ()


def test_an_invoice_billed_before_the_amendment_resolves_to_the_base() -> None:
    base = _contract(
        document_id="base",
        fields={"contract_number": "2110613", "effective_date": "2020-09-15"},
    )
    amendment = _contract(
        document_id="amendment",
        fields={"supersedes_contract_number": "2110613", "effective_date": "2022-01-01"},
    )
    invoice = _invoice(fields={"account_number": "2110613", "bill_date": "2021-01-01"})
    result = resolve(invoice, [base, amendment])
    assert result.contract is base


def test_a_later_effective_contract_wins_among_those_that_bracket() -> None:
    """Two contracts both bracket the billing date (the real Golub shape: a
    base agreement plus a later amendment, neither with a stated end date of
    its own) - the more recently effective one governs more specifically,
    so this resolves rather than staying ambiguous."""
    older = _contract(
        document_id="older", fields={"contract_number": "2110613", "effective_date": "2020-01-01"},
    )
    newer = _contract(
        document_id="newer", fields={"contract_number": "2110613", "effective_date": "2020-06-01"},
    )
    invoice = _invoice(fields={"account_number": "2110613", "bill_date": "2021-01-01"})
    result = resolve(invoice, [older, newer])
    assert result.contract is newer
    assert result.ambiguous_contracts == ()


def test_genuinely_tied_effective_dates_refuse_to_guess() -> None:
    """The actual unresolvable case: two contracts both bracket the billing
    date AND share the identical effective date - no signal left to prefer
    one over the other. Refuses to pick either, the same
    escalate-rather-than-guess posture `prior_balance_basis` already
    established for a different ambiguity."""
    contract_a = _contract(
        document_id="a", fields={"contract_number": "2110613", "effective_date": "2020-06-01"},
    )
    contract_b = _contract(
        document_id="b", fields={"contract_number": "2110613", "effective_date": "2020-06-01"},
    )
    invoice = _invoice(fields={"account_number": "2110613", "bill_date": "2021-01-01"})
    result = resolve(invoice, [contract_a, contract_b])
    assert result.contract is None
    assert len(result.ambiguous_contracts) == 2
    assert contract_a in result.ambiguous_contracts
    assert contract_b in result.ambiguous_contracts


def test_ambiguous_when_the_invoice_has_no_billing_date_to_bracket_with() -> None:
    contract_a = _contract(document_id="a", fields={"contract_number": "2110613",
                                                      "effective_date": "2020-01-01"})
    contract_b = _contract(document_id="b", fields={"contract_number": "2110613",
                                                      "effective_date": "2020-06-01"})
    invoice = _invoice(fields={"account_number": "2110613"})  # no bill_date
    result = resolve(invoice, [contract_a, contract_b])
    assert result.contract is None
    assert len(result.ambiguous_contracts) == 2
