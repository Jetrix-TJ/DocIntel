"""Which senders are aggregators, and therefore cannot supply a vendor name.

`pipeline-v2.md:169`: aggregator senders are keyed by the printed vendor name,
never by the shared email domain. Without that rule every invoice routed through
bill.com collapses onto one vendor identity.

No corpus document arrives from an aggregator, so this module is guarded by
`tests/test_aggregator_guard.py` rather than exercised by the gold set. That is
deliberate: an unimplemented branch nothing tests is the failure mode this file
exists to avoid.
"""

from __future__ import annotations

# Deliberately short. A domain earns a place here only when a real document has
# arrived through it, because a false entry costs a vendor name on every
# document from that sender.
AGGREGATOR_DOMAINS: frozenset[str] = frozenset({
    "bill.com",
    "ariba.com",
    "quickbooks.com",
    "intuit.com",
    "coupahost.com",
})


def is_aggregator(sender_email: str) -> bool:
    """Does this sender forward other companies' invoices?

    Matched on the domain and its subdomains, never on a substring: `notbill.com`
    is a different sender from `bill.com`, and `bill.com.example.org` is a
    lookalike rather than a match.
    """
    if not sender_email or "@" not in sender_email:
        return False
    domain = sender_email.strip().rsplit("@", 1)[1].lower().rstrip(".")
    return any(
        domain == known or domain.endswith(f".{known}")
        for known in AGGREGATOR_DOMAINS
    )
