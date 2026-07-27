"""The OCR-A scan line printed along the foot of a remittance stub. Finding
F7: five of the ten corpus documents (Lumen, Comcast, Centracom, Windstream,
EDCO) print a machine-readable line encoding the account/invoice number and
the amount, in the style of a check's MICR line — meant to be read by a
lockbox scanner, not a human. Because it is a single dense run of digits, a
transcription of it is a strong, independent cross-check on whatever a
selector read off the printed, human-formatted fields nearby.

`find` locates that line by looking for a pure-digit "word" (no letters,
punctuation or spaces within the token) at least `_LONG_RUN_MIN` characters
long, then returns every pure-digit word sharing its visual line, joined
with single spaces. The second part matters: on Lumen the line is not one
token but several, printed as separated digit groups
(`251001 000000752233001 00000000000586878247 8 2 00000024809 2`), and the
digits that corroborate the invoice total (`24809`, for $248.09) live in one
of the *shorter* groups — returning only the longest single token would
silently drop them. Filtering to pure-digit words on that line, rather than
returning the whole visual line verbatim, is what keeps an incidental label
next to the scan line (e.g. Centracom's line is immediately followed by
"Due Amount - Please Remit: $33,876.40" at the same page height) out of the
result.

**Hard constraint, quoted from `docs/architecture/selector-grammar.md`: the
scan line may only ever corroborate `total_printed`, `account_number`,
`invoice_number` and `due_date`.** It is transcription ground truth, not a
business-logic oracle — Centracom's scan line encodes 33,876.40, the
misleading headline "Total Amount Due" on the page, not the 13,752.60
("Subtotal Current Charges") that is actually payable once the prior
balance is excluded. `corroborates` has no way to know which field it is
being asked about, so this constraint is enforced by callers, not here —
but nothing outside this module may wire `scanline.corroborates` to
`amount_payable`, `balance_due`, or any other derived or business-computed
field. Doing so would let a scan line "verify" precisely the wrong number.
"""

from __future__ import annotations

import re

from docintel.core.models import PageText

_LONG_RUN_MIN = 18  # digits; long enough that no ordinary field rendering
# (an account number split across cells, a page-number footer, a date) meets
# it by coincidence, but short enough to catch every scan line in the corpus.

_NON_DIGIT_RE = re.compile(r"[^0-9]")

_MIN_CORROBORATION_DIGITS = 3  # below this, a match is too likely to be a
# coincidence (a lone "1" or "12" appears in almost any long digit run) to
# count as corroborating anything.


def find(pages: tuple[PageText, ...]) -> str | None:
    """Return the raw digit run of the remittance stub's scan line, or None.

    Looks at every page in order; on the first visual line carrying a
    pure-digit word of at least `_LONG_RUN_MIN` characters, returns every
    pure-digit word on that line joined with single spaces. Documents with
    no such line (5 of the 10 in the corpus) return None.
    """
    for page in pages:
        for line in page.lines():
            digit_words = [w.text for w in line if w.text.isdigit()]
            if not digit_words:
                continue
            if max(len(w) for w in digit_words) >= _LONG_RUN_MIN:
                return " ".join(digit_words)
    return None


def corroborates(scanline: str, value: object) -> bool:
    """True if `value`'s digits appear as a contiguous run in `scanline`.

    `value` is converted with `str()` and stripped to digits first, so a
    `Decimal("248.09")` corroborates against "24809" and an account number
    already stored as a string works unchanged. Values with fewer than
    `_MIN_CORROBORATION_DIGITS` digits never corroborate — see the module
    docstring for why, and for the one field this must never be called with:
    the scan line encodes what was printed, not what is actually owed.
    """
    value_digits = _NON_DIGIT_RE.sub("", str(value))
    if len(value_digits) < _MIN_CORROBORATION_DIGITS:
        return False
    scanline_digits = _NON_DIGIT_RE.sub("", scanline)
    return value_digits in scanline_digits
