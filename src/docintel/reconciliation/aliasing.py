"""Account/circuit-ID canonicalization, for matching an invoice's printed
identifier against a contract's - genuinely greenfield.

The closest existing thing, `digitaldirection.references._first`, only strips
internal whitespace from an already-extracted value ("8495 44 462 0365242" ->
"8495444620365242"); it does not canonicalize different RENDERINGS of the
same key the way `aliases.py` canonicalizes vendor names ("CKT-12345" and
"Circuit# 12345" printed on two different documents for the same circuit).

Built narrow - informed by the real ID renderings the curated Golub/Windstream
contract set (docs/corpus/contracts/) actually contains ("Quote #: 2110613",
"Quote# 2494434", printed inline as "Quote # 2110613") - not a speculative
general normalizer for every carrier's ID conventions at once.
"""

from __future__ import annotations

import re

_PREFIX = re.compile(
    r"^\s*(circuit|ckt|account|acct|contract|quote)\s*#?:?\s*", re.IGNORECASE
)
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]")


def canonicalize_account_key(raw: str | None) -> str | None:
    """A bare, uppercased alphanumeric key, or None for an absent/empty value.

    Strips a leading label word ("Circuit", "Account", "Quote", ...) and any
    punctuation, so "CKT-12345", "Circuit# 12345", and "circuit 12345" all
    canonicalize to the same key. Returns None rather than an empty string
    when nothing is left - an absent key must never accidentally equal
    another absent key in a caller that treats None as "no match".
    """
    if not raw:
        return None
    stripped = _PREFIX.sub("", raw.strip())
    key = _NON_ALNUM.sub("", stripped).upper()
    return key or None
