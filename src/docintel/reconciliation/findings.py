"""What a reconciliation pass actually raises, and how it lands in the
review queue.

Three finding kinds, in priority order (an invoice gets at most one):
`contract_precedence_ambiguous` / `no_matching_contract` (nothing to compare
against, or too much) outrank `billed_after_contract_expiry`, which outranks
`rate_mismatch` (a real number to compare, the last thing checked).

Each finding becomes exactly one `enqueue_once` call against the SAME
`SQLiteJobQueue` this session's human-in-the-loop work already built
(`docintel.jobs.store`), with `match_key=invoice_document_id` - this is
exactly why that column exists (Phase 5): two different invoices under the
same carrier, each raising their own finding, must not collide into one job
row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from docintel.reconciliation.match import MatchResult

# Industry-standard default (±2% price variance is the common tolerance-band
# starting point; tighten per-vendor once real billed-vs-contracted figures
# are seen - see docs/PRODUCTION-ROADMAP-CONTRACT-MATCHING.html). Deliberately
# not yet exposed as a pack-level setting: one global constant until a real
# vendor needs a different one, matching this project's own "don't build for
# a hypothetical" discipline.
RATE_TOLERANCE_PCT = 2.0


@dataclass(frozen=True)
class Finding:
    kind: str
    sender_fingerprint: str
    doc_type: str
    invoice_document_id: str
    context: dict[str, Any]


def _rate_fields(record: dict[str, Any]) -> dict[str, Any]:
    return record.get("fields") or {}


def evaluate(result: MatchResult) -> Finding | None:
    """The one finding (if any) this invoice/contract pairing raises."""
    invoice = result.invoice
    fingerprint = invoice.get("sender_fingerprint") or ""
    doc_type = invoice.get("doc_type") or ""
    document_id = invoice.get("document_id") or ""

    if result.ambiguous_contracts:
        return Finding(
            kind="contract_precedence_ambiguous",
            sender_fingerprint=fingerprint,
            doc_type=doc_type,
            invoice_document_id=document_id,
            context={"candidate_count": len(result.ambiguous_contracts)},
        )

    if result.contract is None:
        return Finding(
            kind="no_matching_contract",
            sender_fingerprint=fingerprint,
            doc_type=doc_type,
            invoice_document_id=document_id,
            context={"account_number": _rate_fields(invoice).get("account_number")},
        )

    contract = result.contract
    contract_fields = _rate_fields(contract)
    invoice_fields = _rate_fields(invoice)

    term_end = (contract.get("derived") or {}).get("term_end_date") or contract_fields.get(
        "term_end_date"
    )
    billing_date = invoice_fields.get("bill_date") or invoice_fields.get("service_period")
    if term_end and billing_date and billing_date > term_end:
        return Finding(
            kind="billed_after_contract_expiry",
            sender_fingerprint=fingerprint,
            doc_type=doc_type,
            invoice_document_id=document_id,
            context={"term_end_date": term_end, "bill_date": billing_date},
        )

    contracted_rate = contract_fields.get("contracted_rate")
    billed_rate = invoice_fields.get("current_charges") or invoice_fields.get("total_printed")
    if contracted_rate is not None and billed_rate is not None:
        contracted_rate = float(contracted_rate)
        billed_rate = float(billed_rate)
        if contracted_rate != 0:
            variance_pct = abs(billed_rate - contracted_rate) / contracted_rate * 100
            if variance_pct > RATE_TOLERANCE_PCT:
                return Finding(
                    kind="rate_mismatch",
                    sender_fingerprint=fingerprint,
                    doc_type=doc_type,
                    invoice_document_id=document_id,
                    context={
                        "contracted_rate": contracted_rate,
                        "billed_rate": billed_rate,
                        "variance_pct": round(variance_pct, 2),
                    },
                )

    return None


JOB_KIND = "contract_reconciliation"


def enqueue(finding: Finding, jobs: object) -> bool:
    """Land a finding in the review queue. Returns whether this call created
    the job (see `SQLiteJobQueue.enqueue_once`) - False means it was already
    open from an earlier reconciliation pass over the same invoice.

    Every finding lands under the SAME job kind, `JOB_KIND` -
    `finding.kind` (`no_matching_contract` / `rate_mismatch` /
    `billed_after_contract_expiry` / `contract_precedence_ambiguous`) is the
    specific reason, carried in `context["finding_kind"]`, not the queue's
    own `kind` column. One `/review` group for "needs reconciliation
    attention", the finding kind is what the reviewer reads once they open
    it - matching how this queue's other two kinds each mean one review
    question, not four.
    """
    return bool(
        jobs.enqueue_once(  # type: ignore[attr-defined]
            finding.sender_fingerprint,
            finding.doc_type,
            kind=JOB_KIND,
            context={**finding.context, "finding_kind": finding.kind},
            match_key=finding.invoice_document_id,
        )
    )
