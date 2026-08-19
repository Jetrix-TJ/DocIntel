"""What a reconciliation pass actually raises, and that it lands in the real
job queue with the `match_key` that makes it single-flight PER INVOICE, not
per vendor - the direct proof the Phase 5 schema fix is used correctly here.
"""

from __future__ import annotations

from docintel.jobs.store import SQLiteJobQueue
from docintel.reconciliation.findings import enqueue, evaluate
from docintel.reconciliation.match import MatchResult


def _invoice(**over):
    base = {
        "document_id": "inv-1",
        "sender_fingerprint": "digitaldirection|windstream",
        "doc_type": "telecom_bill",
        "fields": {"account_number": "2110613", "bill_date": "2022-06-01",
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


def test_no_contract_at_all_raises_no_matching_contract() -> None:
    finding = evaluate(MatchResult(invoice=_invoice(), contract=None))
    assert finding.kind == "no_matching_contract"
    assert finding.invoice_document_id == "inv-1"
    assert finding.context["account_number"] == "2110613"


def test_ambiguous_precedence_outranks_everything_else() -> None:
    a, b = _contract(document_id="a"), _contract(document_id="b")
    result = MatchResult(invoice=_invoice(), contract=None, ambiguous_contracts=(a, b))
    finding = evaluate(result)
    assert finding.kind == "contract_precedence_ambiguous"
    assert finding.context["candidate_count"] == 2


def test_an_exact_rate_match_raises_no_finding() -> None:
    invoice = _invoice(fields={"account_number": "2110613", "bill_date": "2022-06-01",
                                "current_charges": 100.00})
    contract = _contract(fields={"contract_number": "2110613", "effective_date": "2020-09-15",
                                  "contracted_rate": 100.00})
    finding = evaluate(MatchResult(invoice=invoice, contract=contract))
    assert finding is None


def test_a_rate_within_tolerance_raises_no_finding() -> None:
    """1.2% variance, under the 2% default tolerance - a clean match, not
    flagged, matching the industry-standard tolerance-band practice this
    module's own docstring cites."""
    invoice = _invoice(fields={"account_number": "2110613", "bill_date": "2022-06-01",
                                "current_charges": 101.20})
    contract = _contract(fields={"contract_number": "2110613", "effective_date": "2020-09-15",
                                  "contracted_rate": 100.00})
    finding = evaluate(MatchResult(invoice=invoice, contract=contract))
    assert finding is None


def test_a_rate_outside_tolerance_raises_rate_mismatch() -> None:
    invoice = _invoice(fields={"account_number": "2110613", "bill_date": "2022-06-01",
                                "current_charges": 106.00})
    contract = _contract(fields={"contract_number": "2110613", "effective_date": "2020-09-15",
                                  "contracted_rate": 100.00})
    finding = evaluate(MatchResult(invoice=invoice, contract=contract))
    assert finding.kind == "rate_mismatch"
    assert finding.context["contracted_rate"] == 100.00
    assert finding.context["billed_rate"] == 106.00
    assert finding.context["variance_pct"] == 6.0


def test_billing_after_contract_expiry_is_forced_ahead_of_a_rate_check() -> None:
    invoice = _invoice(fields={"account_number": "2110613", "bill_date": "2023-01-01",
                                "current_charges": 100.00})
    contract = _contract(
        fields={"contract_number": "2110613", "effective_date": "2020-09-15",
                 "contracted_rate": 100.00},
        derived={"term_end_date": "2022-12-31"},
    )
    finding = evaluate(MatchResult(invoice=invoice, contract=contract))
    assert finding.kind == "billed_after_contract_expiry"
    assert finding.context["term_end_date"] == "2022-12-31"
    assert finding.context["bill_date"] == "2023-01-01"


def test_billing_within_the_contract_term_is_not_flagged_as_expired() -> None:
    invoice = _invoice(fields={"account_number": "2110613", "bill_date": "2022-06-01",
                                "current_charges": 100.00})
    contract = _contract(
        fields={"contract_number": "2110613", "effective_date": "2020-09-15",
                 "contracted_rate": 100.00},
        derived={"term_end_date": "2025-09-15"},
    )
    finding = evaluate(MatchResult(invoice=invoice, contract=contract))
    assert finding is None


def test_a_missing_contracted_rate_is_not_a_rate_mismatch() -> None:
    """A contract that never states a dollar rate (the real Golub call-paths
    amendment shape - a quantity ramp, no new rate printed) has nothing to
    compare a billed amount against - correctly no finding, not a false
    mismatch against a rate that was never there."""
    invoice = _invoice()
    contract = _contract(fields={"contract_number": "2110613", "effective_date": "2020-09-15"})
    finding = evaluate(MatchResult(invoice=invoice, contract=contract))
    assert finding is None


# ==========================================================================
# `enqueue` - the real job queue, and the match_key proof
# ==========================================================================


def test_enqueue_lands_in_the_real_queue_under_the_shared_job_kind(tmp_path):
    """Every finding lands under the SAME job kind, `contract_reconciliation`
    - the specific reason (`no_matching_contract` here) travels in
    `context["finding_kind"]`, not the queue's own `kind` column - one
    `/review` group for reconciliation, not four."""
    jobs = SQLiteJobQueue(tmp_path / "jobs.sqlite3")
    finding = evaluate(MatchResult(invoice=_invoice(), contract=None))

    created = enqueue(finding, jobs)

    assert created is True
    job = jobs.list_open("contract_reconciliation")[0]
    assert job.match_key == "inv-1"
    assert job.sender_fingerprint == "digitaldirection|windstream"
    assert job.context["finding_kind"] == "no_matching_contract"


def test_two_different_invoices_produce_two_distinct_jobs_not_one(tmp_path):
    """The direct proof the Phase 5 schema fix is being used correctly here -
    without `match_key`, these would collide into one job row and the second
    invoice's finding would silently vanish."""
    jobs = SQLiteJobQueue(tmp_path / "jobs.sqlite3")
    finding_1 = evaluate(MatchResult(invoice=_invoice(document_id="inv-1"), contract=None))
    finding_2 = evaluate(MatchResult(invoice=_invoice(document_id="inv-2"), contract=None))

    assert enqueue(finding_1, jobs) is True
    assert enqueue(finding_2, jobs) is True
    assert len(jobs.list_open("contract_reconciliation")) == 2


def test_the_same_invoice_reconciled_twice_is_single_flight(tmp_path):
    jobs = SQLiteJobQueue(tmp_path / "jobs.sqlite3")
    finding = evaluate(MatchResult(invoice=_invoice(), contract=None))

    first = enqueue(finding, jobs)
    second = enqueue(finding, jobs)

    assert first is True
    assert second is False
    assert len(jobs.list_open("contract_reconciliation")) == 1
