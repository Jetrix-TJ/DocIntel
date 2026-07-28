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
