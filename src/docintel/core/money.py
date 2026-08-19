"""Money parsing for every notation the corpus actually uses.

Decimal throughout, never float: the F8 arithmetic-closure checks demand exact
equality, and a float tolerance is where bugs hide.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# A money token: optional currency symbol, digit groups, required decimal part.
# The required decimal part is what keeps account numbers and tax IDs out.
#
# The minus sign is accepted on EITHER side of the currency symbol - "-$161.95"
# and "$-161.95" both appear in the wild (the latter on a real Spectrum/Charter
# Communications "Payments" line: "Payments $-161.95"), and a document has no
# reason to pick one ordering over the other consistently.
MONEY_RE = re.compile(
    r"""
    ^\s*
    (?P<open_paren>\()?
    \s*
    (?P<sign>-)?
    \s*
    [$€£]?
    \s*
    (?P<sign_after_symbol>-)?
    \s*
    (?P<num>
        (?:\d{1,3}(?:,\d{3})+ | \d*)     # grouped or bare integer part
        \.\d{1,4}                         # REQUIRED decimal part, 1-4 places
    )
    \s*
    (?P<close_paren>\))?
    \s*
    (?:/[A-Za-z]{1,4})?                   # rate suffix: -40.00/ST
    \s*
    (?:USD|CAD|EUR|GBP)?
    \s*
    (?P<cr>cr|CR)?
    \s*$
    """,
    re.VERBOSE,
)


def parse_money(raw: str) -> Decimal | None:
    """Parse a money token to a signed Decimal, or None if not money-shaped.

    Negative is expressed several different ways across real documents and all
    of them must normalize to a leading minus:
      -99.80        Federal Recycling line amounts
      (249.84)      Lumen "Payment Received"
      212.87 cr     Comcast credit-card payment
      $-161.95      Spectrum/Charter Communications "Payments" line
    """
    if not raw:
        return None
    m = MONEY_RE.match(raw)
    if m is None:
        return None

    num = m.group("num").replace(",", "")
    if num.startswith("."):
        num = "0" + num
    try:
        value = Decimal(num)
    except InvalidOperation:
        return None

    negative = bool(m.group("sign")) or bool(m.group("sign_after_symbol")) or bool(m.group("cr"))
    if m.group("open_paren") and m.group("close_paren"):
        negative = True
    return -value if negative else value


def is_money(raw: str) -> bool:
    return parse_money(raw) is not None
