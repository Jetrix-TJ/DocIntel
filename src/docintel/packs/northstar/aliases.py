"""Vendor alias table (`docs/packs/northstar-recycling.md` section 4).

**Why this file exists.** Without it, one carrier becomes several cold-start
personas (F5). Federal Recycling is the live case: the letterhead reads *"Federal
Recycling & Waste Solutions"* while the check remittance reads *"Federal
International Recycling and Waste Solutions, LLC"*. Two names, one vendor, and a
persona keyed on the letterhead would never match the month someone re-scans the
remittance stub.

**The payee wins.** The legal entity on the remittance block survives rebrands;
the logo on the letterhead does not, and the money goes where the payee says.

Matching is on a normalized form (casefolded, punctuation collapsed to spaces),
because the corpus prints the same company as `D.T.S.S. Inc.`, `D T S S INC` and
`DTSS`. Keying on punctuation would need one entry per rendering.
"""

from __future__ import annotations

import re

from docintel.packs.registry import normalize_name

# Normalized printed name -> canonical key. Order is irrelevant; longest match
# is not attempted, because these are whole-name comparisons rather than
# substring searches - see `canonical`.
LITERAL_ALIASES: dict[str, str] = {
    "d t s s": "dtss",
    "d t s s inc": "dtss",
    "dtss": "dtss",
    "veritiv operating company": "veritiv",
    "veritiv": "veritiv",
    "complete beverage destruction": "complete_beverage_destruction",
    "cbd usa": "complete_beverage_destruction",
    "federal recycling waste solutions": "federal_recycling",
    "federal recycling and waste solutions": "federal_recycling",
    "federal international recycling and waste solutions": "federal_recycling",
    "federal international recycling and waste solutions llc": "federal_recycling",
    "u pak disposals": "upak",
    "u pak disposals 1989 ltd": "upak",
    "u pak": "upak",
    "edco waste recycling service": "edco",
    "edco waste and recycling service": "edco",
    "edco disposal": "edco",
    "edco disposal corporation": "edco",
    "edco": "edco",
}

# Patterns for vendors that print a per-entity name. A literal table cannot cover
# these: Windstream alone bills as OKLAHOMA WINDSTREAM, TEXAS WINDSTREAM and
# several more, and enumerating US states is exactly the kind of list that is
# wrong the first time a vendor incorporates somewhere new.
PATTERN_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bu\s?pak\b"), "upak"),
    (re.compile(r"\bfederal (international )?recycling\b"), "federal_recycling"),
    (re.compile(r"\bcomplete beverage\b"), "complete_beverage_destruction"),
    (re.compile(r"\bveritiv\b"), "veritiv"),
    (re.compile(r"\bedco\b"), "edco"),
    (re.compile(r"\bd\s?t\s?s\s?s\b"), "dtss"),
)


def canonical(printed: str | None, payee: str | None = None) -> str | None:
    """The canonical vendor key, preferring the remittance payee (F5).

    Returns None rather than a guess when neither name is recognized. A cold
    start is the correct outcome for a genuinely new vendor - inventing a key
    from the letterhead would create a persona nobody can find again.
    """
    for candidate in (payee, printed):
        if not candidate:
            continue
        resolved = _lookup(candidate)
        if resolved is not None:
            return resolved
    return None


def _lookup(printed: str) -> str | None:
    normalized = normalize_name(printed)
    if not normalized:
        return None
    literal = LITERAL_ALIASES.get(normalized)
    if literal is not None:
        return literal
    for pattern, key in PATTERN_ALIASES:
        if pattern.search(normalized):
            return key
    return None


# The canonical key each shipped persona is filed under, so the fingerprint a
# persona declares and the one Stage 4 computes cannot drift apart.
KNOWN_VENDORS: frozenset[str] = frozenset(LITERAL_ALIASES.values())

# canonical key -> the name to report. The *output* of the alias table, and the
# only part of vendor identity that is genuinely table data rather than something
# printed: a vendor with three printed renderings has one name, and picking which
# rendering to report is a decision, not a transcription.
#
# Used only when no selector extracted a `vendor_name`. Printed evidence wins
# where it exists (F5's principle), so a persona that CAN read the letterhead
# should - and Veritiv's is the case that cannot, because its name shares a
# flattened line with the invoice header block.
DISPLAY_NAMES: dict[str, str] = {
    "dtss": "D.T.S.S., Inc.",
    "veritiv": "Veritiv Operating Company",
    "complete_beverage_destruction": "Complete Beverage Destruction, LLC",
    "federal_recycling": "Federal Recycling & Waste Solutions",
    "upak": "U-Pak Disposals (1989) Ltd",
    "edco": "EDCO Waste & Recycling Service",
}

# Sender-email domain -> canonical key, for the fallback in
# `resolve_vendor_fingerprint` when the letterhead cannot be read at all (F5's
# escape hatch, not its normal path). A domain earns a place here only when a
# real corpus document prints that address: `docs/corpus/gold/
# northstar-complete-beverage-32930.json` has `vendor_email: "AR@CBD-USA.COM"`,
# so `cbd-usa.com` is real evidence that domain belongs to Complete Beverage
# Destruction. No other Northstar vendor's gold record carries a printed email
# address, so no other domain is added - inventing one to fill out the table
# would be a guess wearing a table's clothes. Deliberately NOT derived by
# munging a vendor's name into a plausible-looking domain: `acmehauling.com`
# only coincidentally resembles Acme Hauling's canonical key, and a munge would
# silently miss the real domain when it does not match the guess.
DOMAIN_ALIASES: dict[str, str] = {
    "cbd-usa.com": "complete_beverage_destruction",
}


def canonical_from_domain(sender_email: str | None) -> str | None:
    """The canonical vendor key from the sender's email domain, or None.

    Weaker evidence than a printed name: only consulted by
    `resolve_vendor_fingerprint` when `canonical()` found nothing on the page.
    """
    if not sender_email or "@" not in sender_email:
        return None
    domain = sender_email.strip().rsplit("@", 1)[1].lower().rstrip(".")
    return DOMAIN_ALIASES.get(domain)


# The AP department this pack buys FOR, as its vendors print it.
#
# Unlike Digital Direction's roster, this is a single party - Northstar is the AP
# department, and every invoice it handles is billed to Northstar. What varies is
# how each VENDOR renders the name, and the corpus alone shows five renderings:
# `Northstar Recycling`, `Northstar Recycling Company LLC`,
# `NorthStar Recycling Company, LLC` and a site-specific
# `Northstar-Bimbo-Market Street`.
#
# That variation is why six personas each carried their vendor's own rendering as
# a literal pattern. One table replaces all six, and a seventh vendor printing any
# rendering already listed needs no new rule.
#
# **This is the pack's guard, and the roster preserves it.** `bill_to_name` is
# required for Northstar precisely so a vendor invoice that arrived in the wrong
# inbox is not silently processed as though it belonged here (see
# `packs/registry.py`). A page mentioning none of these renderings still yields an
# empty required field, which `core.coverage` escalates - the guard now lives in
# one place instead of being copy-pasted per vendor.
BILL_TO_RENDERINGS: tuple[str, ...] = (
    "NorthStar Recycling Company, LLC",
    "Northstar Recycling Company, LLC",
    "Northstar Recycling Company LLC",
    "Northstar Recycling",
    "Northstar-Bimbo-Market Street",
)
