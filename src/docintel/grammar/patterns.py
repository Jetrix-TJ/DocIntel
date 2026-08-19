"""The closed pattern vocabulary (`selector-grammar.md` sections 3.1 and 3.2).

A selector's `pattern` is either one of the thirteen names in `NAMED` or a raw
regex that survives `compile_restricted`. There is no third option, and that is
the point: `compile_restricted` is the security boundary for the one place the
grammar lets an agent supply something regex-shaped.

Two design notes worth keeping:

* Every named pattern returns `None` rather than raising when the input does not
  match. A pattern that does not match is a *field miss*, which the confidence
  machinery already knows how to price. Raising would turn a routine miss into a
  pipeline error.
* `currency` deliberately requires a decimal part. That single restriction is
  what keeps a tax-registration number (`999999999XX0000`-shaped) and a bare
  quantity (`1234`) from reading as money next to a `Total` anchor - the F14
  anchor hazard.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from docintel.core.dates import DateResult, parse_date
from docintel.core.errors import ValidationError
from docintel.core.money import parse_money

# --------------------------------------------------------------------------
# Named patterns
# --------------------------------------------------------------------------

# The sign is accepted on either side of a currency symbol - "-$161.95" and
# "$-161.95" both appear in the wild (the latter on Spectrum/Charter
# Communications invoices), same reasoning as `core.money.MONEY_RE`'s own
# `sign_after_symbol` group, which this pre-check must agree with: it must
# accept everything `parse_money` would actually resolve to a signed value,
# or a genuinely signed figure gets rejected here before `parse_money` is
# ever called.
_SIGNED_MONEY = re.compile(r"^\s*[$€£]?\s*(?:[-+]|\()|(?:\)|cr|CR)\s*$")
_INTEGER = re.compile(r"^\s*(\d{1,3}(?:,\d{3})+|\d+)\s*$")
_DECIMAL = re.compile(r"^\s*-?\s*(\d{1,3}(?:,\d{3})+|\d*)\.(\d+)\s*$")
_PHONE = re.compile(
    r"^\s*(?:1[-.\s])?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}\s*$"
)
_ZIP = re.compile(r"^\s*(\d{5})(?:-(\d{4}))?\s*$")
_CA_POSTAL = re.compile(r"^\s*([A-Za-z]\d[A-Za-z])\s*(\d[A-Za-z]\d)\s*$")
# Canadian Business Number: 9 digits, a 2-letter programme code, a 4-digit
# reference. Narrow on purpose - see test_tax_id_rejects_a_plain_account_number.
_TAX_ID = re.compile(r"^\s*(\d{9})\s*([A-Za-z]{2})\s*(\d{4})\s*$")
_DIGITS_RUN = re.compile(r"^\s*\d[\d\s]*\d\s*$")
_ACCOUNT_NUMBER = re.compile(r"^\s*[0-9A-Za-z][0-9A-Za-z\s\-]*[0-9A-Za-z]\s*$")


@dataclass(frozen=True)
class AccountNumber:
    """An account number in both the printed and the joinable form (F6).

    One corpus vendor prints `1234 56 789 0123456`; the same account appears
    elsewhere without the spaces. Keeping both means the record can show what
    the document said while still matching on identity.
    """

    raw: str
    normalized: str


def _currency(raw: str) -> Decimal | None:
    return parse_money(raw)


def _currency_signed(raw: str) -> Decimal | None:
    """As `currency`, but the sign must have been printed.

    Used where an unsigned number would be a genuine ambiguity rather than an
    assumed positive - a credits column that is sometimes bare, for instance.
    """
    if not _SIGNED_MONEY.search(raw or ""):
        return None
    return parse_money(raw.replace("+", "", 1) if "+" in raw else raw)


def _integer(raw: str) -> int | None:
    m = _INTEGER.match(raw or "")
    if m is None:
        return None
    return int(m.group(1).replace(",", ""))


def _decimal(raw: str) -> Decimal | None:
    """Requires a decimal point, and preserves the printed precision.

    A unit price printed `12.3400` stays four places: the printed precision is
    evidence about the document, and Decimal is the only way to keep it without
    float drift.
    """
    m = _DECIMAL.match(raw or "")
    if m is None:
        return None
    whole = m.group(1).replace(",", "") or "0"
    text = f"{whole}.{m.group(2)}"
    if (raw or "").lstrip().startswith("-"):
        text = "-" + text
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _date(raw: str) -> DateResult | None:
    """Strict: unparseable input is a miss, never a passthrough."""
    result = parse_date(raw or "")
    return result if result.parsed else None


def _date_loose(raw: str) -> DateResult | None:
    """Lenient: keeps the raw text when it cannot be parsed (F9).

    One corpus vendor prints its due date as an ordinal day-of-month phrase
    rather than a calendar date (e.g. `Nth OF THE MONTH`). Recording that
    verbatim with `parsed: False` is the honest answer; inventing a calendar
    date from it would be a fabrication the reviewer could not see.
    """
    if not (raw or "").strip():
        return None
    return parse_date(raw)


def _text(raw: str) -> str | None:
    """The first non-empty line, outer whitespace stripped."""
    for line in (raw or "").splitlines():
        if line.strip():
            return line.strip()
    return None


def _text_block(raw: str) -> str | None:
    """Multi-line run with its line structure intact - for addresses."""
    stripped = (raw or "").strip()
    return stripped or None


def _account_number(raw: str) -> AccountNumber | None:
    candidate = (raw or "").strip()
    if len(candidate) < 2 or _ACCOUNT_NUMBER.match(candidate) is None:
        return None
    normalized = re.sub(r"[\s\-]", "", candidate)
    if not normalized:
        return None
    return AccountNumber(raw=candidate, normalized=normalized)


def _phone(raw: str) -> str | None:
    if _PHONE.match(raw or "") is None:
        return None
    return (raw or "").strip()


def _postal_code(raw: str) -> str | None:
    """US zip (5 or 5+4) or Canadian postal code.

    The Canadian form matters beyond the address: a CA postal code is a rung on
    the F14 currency-inference ladder.
    """
    candidate = (raw or "").strip()
    m = _CA_POSTAL.match(candidate)
    if m is not None:
        return f"{m.group(1).upper()} {m.group(2).upper()}"
    return candidate if _ZIP.match(candidate) else None


def _tax_id(raw: str) -> str | None:
    m = _TAX_ID.match(raw or "")
    if m is None:
        return None
    return f"{m.group(1)}{m.group(2).upper()}{m.group(3)}"


def _digits_run(raw: str) -> str | None:
    """Ten or more digits, internal spaces allowed and stripped (F7).

    Ten is the floor that keeps invoice numbers (one corpus vendor's is a
    seven-digit number) out of the scanline pattern.
    """
    if _DIGITS_RUN.match(raw or "") is None:
        return None
    digits = re.sub(r"\s", "", raw)
    return digits if len(digits) >= 10 else None


NAMED: dict[str, Callable[[str], Any]] = {
    "currency": _currency,
    "currency_signed": _currency_signed,
    "integer": _integer,
    "decimal": _decimal,
    "date": _date,
    "date_loose": _date_loose,
    "text": _text,
    "text_block": _text_block,
    "account_number": _account_number,
    "phone": _phone,
    "postal_code": _postal_code,
    "tax_id": _tax_id,
    "digits_run": _digits_run,
}

# --------------------------------------------------------------------------
# Restricted regex (section 3.2)
# --------------------------------------------------------------------------

MAX_PATTERN_LENGTH = 200
MAX_CAPTURE_GROUPS = 1

_BACKREFERENCE = re.compile(r"\\[1-9]|\(\?P=")
_LOOKBEHIND = re.compile(r"\(\?<[=!]")
_ATOMIC_GROUP = re.compile(r"\(\?>")
_POSSESSIVE = re.compile(r"[*+?}][+]")
# An unbounded quantifier: bare * or +, or an open-ended {n,}. The negative
# lookbehind on `\` keeps the literal escapes `\*` and `\+` out of it.
_UNBOUNDED = re.compile(r"(?<!\\)(?<!\[)[*+]|\{\d*,\}")
# A quantified group whose body itself contains a quantifier. Bounded at both
# levels and still exponential - see the nested-quantifier test.
_NESTED_QUANTIFIED = re.compile(r"\((?:\?[:=!])?[^()]*[*+}][^()]*\)\s*\{")


def compile_restricted(pattern: str) -> re.Pattern[str]:
    """Compile an agent-supplied regex, or reject it.

    Order matters. Length is checked before structure so that a 250-character
    pattern reports the length problem rather than whatever else happens to be
    wrong with it, and backreferences are checked independently of the capture
    count because `(a)\\1` is within the capture budget and still forbidden.

    The static restrictions are the first half of the linear-time guarantee; the
    50ms per-field runtime budget in the executor is the second. Neither is
    sufficient alone, which is why nested bounded quantifiers are rejected here
    rather than left for the timeout to absorb.
    """
    if not isinstance(pattern, str) or not pattern:
        raise ValidationError("pattern must be a non-empty string")

    if len(pattern) > MAX_PATTERN_LENGTH:
        raise ValidationError(
            f"pattern is {len(pattern)} characters; the limit is {MAX_PATTERN_LENGTH}"
        )
    if _BACKREFERENCE.search(pattern):
        raise ValidationError("pattern uses a backreference, which is not permitted")
    if _LOOKBEHIND.search(pattern):
        raise ValidationError("pattern uses a lookbehind, which is not permitted")
    if _ATOMIC_GROUP.search(pattern):
        raise ValidationError("pattern uses an atomic group, which is not permitted")
    if _POSSESSIVE.search(pattern):
        raise ValidationError("pattern uses a possessive quantifier, which is not permitted")
    if _UNBOUNDED.search(pattern):
        raise ValidationError(
            "pattern uses an unbounded quantifier; bound it explicitly, e.g. .{0,80}"
        )
    if _NESTED_QUANTIFIED.search(pattern):
        raise ValidationError(
            "pattern has a nested quantifier inside a quantified group; bounded "
            "nesting is still exponential"
        )

    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise ValidationError(f"pattern is an invalid regex: {exc}") from exc

    if compiled.groups > MAX_CAPTURE_GROUPS:
        raise ValidationError(
            f"pattern has {compiled.groups} capture groups; at most "
            f"{MAX_CAPTURE_GROUPS} is permitted (the value)"
        )
    return compiled


def resolve(pattern: str) -> Callable[[str], Any]:
    """Turn a selector's `pattern` string into a callable.

    The single place the two halves of section 3 meet, so callers never have to
    ask which kind of pattern they are holding.
    """
    named = NAMED.get(pattern)
    if named is not None:
        return named

    compiled = compile_restricted(pattern)

    def _match(raw: str) -> str | None:
        m = compiled.search(raw or "")
        if m is None:
            return None
        return m.group(1) if compiled.groups else m.group(0)

    return _match
