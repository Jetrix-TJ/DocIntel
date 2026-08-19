"""Pair an already-processed invoice record against the contract record(s)
that govern it, for the same carrier.

Multiple contracts per account is the REAL shape, not a hypothetical: the
Golub/Windstream relationship this module was built against has a 2020 base
agreement plus a chain of amendments and renewals layered on top of it
(docs/BUGS-FEATURES-PRODUCTION.md's own open item, corpus-analysis.md F21).
"Latest contract wins" is wrong - an amendment modifies specific terms while
the base agreement remains in force. Resolution is by effective-date
bracketing against the invoice's own billing period; when that's still
ambiguous, this refuses to guess, the same escalate-rather-than-guess posture
`prior_balance_basis` already established for a different ambiguity (see
`docintel.packs.registry.load_basis_overlay`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from docintel.reconciliation.aliasing import canonicalize_account_key


@dataclass(frozen=True)
class MatchResult:
    invoice: dict[str, Any]
    contract: dict[str, Any] | None
    # Non-empty only when precedence among 2+ candidates is genuinely
    # ambiguous - `contract` is then always None (see `resolve`).
    ambiguous_contracts: tuple[dict[str, Any], ...] = field(default_factory=tuple)


# The field names that can carry the identifier this module joins on. An
# invoice usually prints `account_number`/`circuit_id`; a base contract
# usually prints its own `contract_number`; an amendment references the base
# it amends via `supersedes_contract_number`. All four are the SAME kind of
# fact - "which real-world account/agreement does this document concern" -
# just under different names depending on which side of the relationship
# printed it, so the join checks every combination rather than assuming an
# invoice's field name matches its contract's.
_IDENTIFIER_FIELDS: tuple[str, ...] = (
    "account_number", "circuit_id", "contract_number", "supersedes_contract_number",
)


def _identifier_keys(record: dict[str, Any]) -> set[str]:
    """Every canonicalized identifier this record's fields carry, from
    whichever of `_IDENTIFIER_FIELDS` it actually prints."""
    fields = record.get("fields") or {}
    keys = (canonicalize_account_key(fields.get(name)) for name in _IDENTIFIER_FIELDS)
    return {k for k in keys if k is not None}


def find_candidates(invoice: dict[str, Any], contracts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every contract for the SAME carrier that shares at least one
    identifier with the invoice, under any of the field names either side
    might have printed it."""
    fingerprint = invoice.get("sender_fingerprint")
    invoice_keys = _identifier_keys(invoice)
    if not invoice_keys:
        return []
    candidates = []
    for contract in contracts:
        if contract.get("sender_fingerprint") != fingerprint:
            continue
        if invoice_keys & _identifier_keys(contract):
            candidates.append(contract)
    return candidates


def _effective_window(contract: dict[str, Any]) -> tuple[str | None, str | None]:
    fields = contract.get("fields") or {}
    start = fields.get("effective_date") or fields.get("signed_date")
    end = (contract.get("derived") or {}).get("term_end_date") or fields.get("term_end_date")
    return start, end


def _billing_date(invoice: dict[str, Any]) -> str | None:
    fields = invoice.get("fields") or {}
    return fields.get("bill_date") or fields.get("service_period") or fields.get("invoice_date")


def resolve(invoice: dict[str, Any], contracts: list[dict[str, Any]]) -> MatchResult:
    """Which single contract governs this invoice, if any.

    Zero candidates -> `contract=None`, no ambiguity (the caller's
    `no_matching_contract` finding). One candidate -> that one, unconditionally.
    2+ candidates -> resolved by effective-date bracketing against the
    invoice's own billing date; if bracketing still leaves 2+ (or the
    billing date or every candidate's effective date is missing), refuse to
    pick and report the ambiguity instead.
    """
    candidates = find_candidates(invoice, contracts)
    if not candidates:
        return MatchResult(invoice=invoice, contract=None)
    if len(candidates) == 1:
        return MatchResult(invoice=invoice, contract=candidates[0])

    billing_date = _billing_date(invoice)
    if billing_date is not None:
        bracketed = []
        for contract in candidates:
            start, end = _effective_window(contract)
            if start is None:
                continue
            if start <= billing_date and (end is None or billing_date <= end):
                bracketed.append(contract)
        if len(bracketed) == 1:
            return MatchResult(invoice=invoice, contract=bracketed[0])
        if len(bracketed) > 1:
            # More than one contract's window genuinely contains this billing
            # date - the real Golub shape, a base agreement plus a later
            # amendment with no stated end date of its own. Prefer the most
            # RECENTLY EFFECTIVE among the ones that actually bracket - an
            # amendment effective later necessarily governs more specifically
            # than the base it was layered onto - and only refuse when that
            # preference is itself a genuine tie (unresolvable without a
            # human), not a fallback to "latest of all candidates" outright
            # (which would wrongly override a bracket-eliminated one).
            latest = max(start for c in bracketed if (start := _effective_window(c)[0]))
            tied = [c for c in bracketed if _effective_window(c)[0] == latest]
            if len(tied) == 1:
                return MatchResult(invoice=invoice, contract=tied[0])
            return MatchResult(invoice=invoice, contract=None, ambiguous_contracts=tuple(tied))

    return MatchResult(invoice=invoice, contract=None, ambiguous_contracts=tuple(candidates))
