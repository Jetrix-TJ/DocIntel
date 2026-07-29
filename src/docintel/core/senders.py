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

import re

# Deliberately short, because a false entry costs a vendor name on every document
# from that sender. Nothing here is corpus-backed - no corpus document arrives
# from an aggregator at all - so the bar is the architecture spec instead: the
# first three are the ones `pipeline-v2.md:169` names. The last two are category
# inferences from those (Intuit is QuickBooks' parent, Coupa is the same class of
# procurement platform as Ariba), and are marked as such so nobody reads the
# list as evidence. Drop an inferred entry rather than defend it if it ever
# swallows a real vendor name.
AGGREGATOR_DOMAINS: frozenset[str] = frozenset({
    "bill.com",
    "ariba.com",
    "quickbooks.com",
    "intuit.com",  # inferred, not spec-named
    "coupahost.com",  # inferred, not spec-named
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


def normalize_name(value: str) -> str:
    """Collapse a printed company name to a comparable form.

    Punctuation is dropped rather than kept, because the corpus prints the same
    company as `D.T.S.S. Inc.`, `D T S S INC` and `DTSS` - and an alias table
    keyed on punctuation would need an entry per rendering.

    Lives here rather than in `packs.registry` (which re-exports it for
    existing callers) because `core` must not depend on `packs`: this
    function is needed by `bill_to_matches_roster` below, and `core` is the
    lower layer both pack modules already import from.
    """
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def bill_to_matches_roster(printed: str | None, roster: tuple[str, ...]) -> bool:
    """Whether the printed bill-to is a rendering of a party on the pack's roster.

    True when there is nothing to check: an absent bill-to is `core.coverage`'s
    business (a missing required field), and conflating the two would report one
    problem as the other. An empty roster is also True - a pack that declares no
    parties has made no claim that this document violates.

    Substring in both directions, on normalized names, because renderings differ
    by more than punctuation: a vendor may print `Northstar Recycling` where the
    roster says `Northstar Recycling Company, LLC`, and another may print the
    longer form where the roster holds the short one.
    """
    if not printed or not roster:
        return True
    needle = normalize_name(printed)
    if not needle:
        return True
    return any(
        needle in normalize_name(entry) or normalize_name(entry) in needle
        for entry in roster
    )
