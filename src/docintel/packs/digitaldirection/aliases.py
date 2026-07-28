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
