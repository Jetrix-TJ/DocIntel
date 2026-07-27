"""Date parsing ladder.

Never invents a value. Centracom's due date is literally "25TH OF THE MONTH";
passing that through unparsed is correct behaviour, not a failure (F9).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_NUMERIC = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\s*$")
_MONTH_NAME = re.compile(r"^\s*([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\s*$")

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


@dataclass(frozen=True)
class DateResult:
    raw: str
    iso: str | None
    parsed: bool
    ambiguous_two_digit_year: bool


def _ok(raw: str, y: int, m: int, d: int, ambiguous: bool) -> DateResult:
    try:
        iso = date(y, m, d).isoformat()
    except ValueError:
        return DateResult(raw=raw, iso=None, parsed=False, ambiguous_two_digit_year=False)
    return DateResult(raw=raw, iso=iso, parsed=True, ambiguous_two_digit_year=ambiguous)


def parse_date(raw: str) -> DateResult:
    if not raw:
        return DateResult(raw=raw, iso=None, parsed=False, ambiguous_two_digit_year=False)

    m = _NUMERIC.match(raw)
    if m:
        month, day, year_s = int(m.group(1)), int(m.group(2)), m.group(3)
        ambiguous = len(year_s) == 2
        year = 2000 + int(year_s) if ambiguous else int(year_s)
        return _ok(raw, year, month, day, ambiguous)

    m = _MONTH_NAME.match(raw)
    if m:
        month = _MONTHS.get(m.group(1).lower())
        if month is not None:
            return _ok(raw, int(m.group(3)), month, int(m.group(2)), False)

    return DateResult(raw=raw, iso=None, parsed=False, ambiguous_two_digit_year=False)
