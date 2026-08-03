"""Carrier alias table (`docs/packs/digital-direction.md` section 4) — F5.

**The strongest F5 case in the corpus.** Lumen prints *three* names on one page:
the `LUMEN` logo, "Invoice of Level 3 Communications, LLC, a CenturyLink company",
and "Make check payable to Level 3 Communications, LLC". Without this table that
is three personas, three cold starts, and three independently drifting rule sets
for one carrier.

Windstream compounds it with a **state-specific operating entity**
(`OKLAHOMA WINDSTREAM, LLC`). That is matched as a pattern, not a literal —
enumerating US states would be wrong the first time the carrier incorporates
somewhere new, and every new state would otherwise be a new persona.

**The payee wins over the letterhead.** The payee is the legal entity and survives
rebrands; the logo does not.
"""

from __future__ import annotations

import re

from docintel.packs.registry import normalize_name

LITERAL_ALIASES: dict[str, str] = {
    "lumen": "lumen",
    "level 3 communications": "lumen",
    "level 3 communications llc": "lumen",
    "centurylink": "lumen",
    "windstream": "windstream",
    "kinetic business": "windstream",
    "kinetic business by windstream": "windstream",
    # The carrier's OTHER retail brand (Finding 3). Two real bills are
    # letterheaded `WINDSTREAM ENTERPRISE` and remit to a different PO box than
    # the Kinetic template, and `windstream.json` now reads that name off the
    # page - so it arrives here as a `letterhead` candidate, and rung 2 of
    # `resolve_vendor_alias` is an EXACT dict lookup, not a pattern walk. Without
    # this key the name would fall through to rung 3 and resolve from page text
    # instead, reporting `page_text_alias` for a canonical that in fact came off
    # the printed letterhead. Same canonical either way: one carrier, one
    # persona, whichever brand it bills under (F5).
    "windstream enterprise": "windstream",
    "comcast": "comcast",
    "comcast business": "comcast",
    "centracom": "centracom",
}

PATTERN_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = (
    # `{STATE} WINDSTREAM, LLC` and anything else carrying the brand.
    (re.compile(r"\bwindstream\b"), "windstream"),
    (re.compile(r"\bkinetic business\b"), "windstream"),
    (re.compile(r"\blevel 3 communications\b"), "lumen"),
    (re.compile(r"\bcenturylink\b"), "lumen"),
    (re.compile(r"\blumen\b"), "lumen"),
    (re.compile(r"\bcomcast\b"), "comcast"),
    (re.compile(r"\bcentracom\b"), "centracom"),
)

KNOWN_CARRIERS: frozenset[str] = frozenset(LITERAL_ALIASES.values())

# canonical key -> the name to report.
#
# Two of these CANNOT be read off the page by any pattern, which is why the table
# exists rather than being a shortcut:
#
#   Lumen       the LUMEN letterhead is an IMAGE - the token appears zero times
#               in the text layer. Only `How to reach Lumen:` and the domain do.
#   Windstream  the text layer breaks the brand mid-word: `Kinetic Business by
#               Windstre am`. No literal or pattern match yields the real name.
#
# The alias table still resolves both correctly - Lumen via `\blumen\b`, Windstream
# via `\bkinetic business\b` - so the canonical key is known even when the display
# name is unreadable. That is exactly the gap this table fills.
DISPLAY_NAMES: dict[str, str] = {
    "centracom": "CentraCom",
    "comcast": "Comcast Business",
    "lumen": "Lumen",
    "windstream": "Kinetic Business by Windstream",
}

# Sender-email domain -> canonical key, for the fallback in
# `resolve_carrier_fingerprint` when nothing on the page resolves at all (the
# escape hatch, not the normal path - `canonical()` above already resolves
# Lumen and Windstream from other printed text, so this table exists for the
# case where even that fails). A domain earns a place here only when a real
# corpus document prints that address: `docs/corpus/gold/
# digitaldirection-lumen-5-QXH7QKM7.json` has `vendor_email:
# "Billing@Lumen.com"`, so `lumen.com` is real evidence for Lumen. No other DD
# carrier's gold record carries a printed email address - Windstream, Comcast
# and CentraCom are absent on purpose, not an oversight - so no other domain is
# added. Not derived by munging a carrier's name into a plausible domain: that
# would silently miss the real one when the guess is wrong.
DOMAIN_ALIASES: dict[str, str] = {
    "lumen.com": "lumen",
}


def canonical_from_domain(sender_email: str | None) -> str | None:
    """The canonical carrier key from the sender's email domain, or None.

    Weaker evidence than a printed name: only consulted by
    `resolve_carrier_fingerprint` when `canonical()` found nothing on the page.
    """
    if not sender_email or "@" not in sender_email:
        return None
    domain = sender_email.strip().rsplit("@", 1)[1].lower().rstrip(".")
    return DOMAIN_ALIASES.get(domain)


def canonical(printed: str | None, payee: str | None = None) -> str | None:
    """The canonical carrier key, preferring the remittance payee (F5)."""
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


def count_printed_names(text: str) -> int:
    """How many distinct alias entries this page matches.

    Drives the `multi_brand_sender` tag. Lumen matches three, Windstream two -
    and the tag is what makes the collapse visible on the record rather than a
    silent normalization nobody can audit.
    """
    normalized = normalize_name(text)
    seen: set[str] = set()
    for phrase in LITERAL_ALIASES:
        if phrase in normalized:
            seen.add(phrase)
    return len(seen)


# The managed clients this pack bills FOR, as each carrier prints them.
#
# Digital Direction is a telecom expense manager: its bills are addressed to
# several managed clients, so the bill-to is a per-DOCUMENT fact rather than a
# per-vendor one. That is exactly why three of the four personas used to carry the
# client's name as a selector *pattern* - and why an unseen client returned an
# empty field. Since extraction completeness now escalates a missing required
# field, that literal meant every invoice for a newly onboarded client went to
# manual review.
#
# A roster here instead of a literal there. Two things change:
#
#   * one table serves all four carriers and every billing period, so a client
#     billed by a fifth carrier needs no new rule at all;
#   * onboarding a client is a one-line config change, reviewed as business data,
#     rather than an edit to four extraction rules.
#
# Two renderings of the Clyde entity because two carriers print it two ways -
# Comcast truncates to `Clyde Administration Servi` in a fixed-width field, and
# Centracom prints the parent `CLYDE COMPANIES`. Both are the same client, and
# `resolve_bill_to_alias` returns whichever the document actually shows, because
# each gold label asserts its own document's rendering.
#
# Order does not matter: the resolver tries the longest entry first, so
# `CLYDE COMPANIES` cannot shadow a longer name containing it.
#
# **A client not listed here yields an empty bill_to_name, on purpose.** It is
# escalated to review by `core.coverage` rather than guessed, because putting the
# wrong party on a telecom invoice misroutes a chargeback to a real customer.
MANAGED_CLIENTS: tuple[str, ...] = (
    "Clyde Administration Servi",
    "Clyde Companies",
    "City of Dublin",
    "Choctaw Travel Mart",
)
