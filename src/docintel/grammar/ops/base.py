"""Value ops (`selector-grammar.md` section 4.1).

Each is `Callable[[Any], Any]`: it transforms one field's value, and which field
comes from the selector that declared it.

Two properties every op here holds to, both tested:

* **Idempotent.** Running an op twice must equal running it once. A persona may
  declare `trim` alongside a pattern that already trimmed, and Stage 6 must not
  care.
* **Safe on an already-parsed value.** `patterns.currency` returns a signed
  `Decimal`, so `parens_to_negative` will often be handed a value that has
  already had its parentheses resolved. Passing it straight through is correct;
  crashing or double-negating is not.

That second property is why these ops are mostly *narrower* than they look. They
exist for the raw-regex path, where a selector captured a string and nothing
interpreted it - not to second-guess the named patterns.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from docintel.core.dates import parse_date
from docintel.core.money import parse_money

_WHITESPACE = re.compile(r"\s+")
_CURRENCY_SYMBOLS = re.compile(r"[$€£]|\b(?:USD|CAD|EUR|GBP)\b")
_PARENTHESIZED = re.compile(r"^\s*\(\s*(.+?)\s*\)\s*$")
_TRAILING_CR = re.compile(r"^(.*?)\s*(?:cr|CR)\s*$")


def _as_money_or_text(text: str) -> Any:
    """Return a Decimal when the cleaned text is money-shaped, else the text.

    The ops below are declared on money fields but are legal on any field, so
    they must not force a non-numeric value into a number.
    """
    parsed = parse_money(text)
    return parsed if parsed is not None else text


def strip_internal_whitespace(value: Any) -> Any:
    """`8495 44 462 0365242` -> `8495444620365242` (F6)."""
    if not isinstance(value, str):
        return value
    return _WHITESPACE.sub("", value)


def collapse_internal_spaces(value: Any) -> Any:
    """Squeeze runs of whitespace to one space, for name matching."""
    if not isinstance(value, str):
        return value
    return _WHITESPACE.sub(" ", value).strip()


def strip_currency_symbols(value: Any) -> Any:
    """`$1,177.70` -> `1177.70`. A Decimal never carried a symbol, so it passes through."""
    if not isinstance(value, str):
        return value
    cleaned = _CURRENCY_SYMBOLS.sub("", value).strip()
    return _as_money_or_text(cleaned)


def parens_to_negative(value: Any) -> Any:
    """`(249.84)` -> `-249.84`. Lumen's "Payment Received" notation.

    A value that is already a negative Decimal is returned unchanged - which is
    the common case, because `patterns.currency` resolves parentheses itself.
    Re-negating here would turn Lumen's credit back into a charge.
    """
    if isinstance(value, Decimal):
        return value
    if not isinstance(value, str):
        return value
    match = _PARENTHESIZED.match(value)
    if match is None:
        return _as_money_or_text(value)
    return _as_money_or_text(f"-{match.group(1)}")


def trailing_cr_to_negative(value: Any) -> Any:
    """`212.87 cr` -> `-212.87`. Comcast's credit-card payment notation."""
    if isinstance(value, Decimal):
        return value
    if not isinstance(value, str):
        return value
    match = _TRAILING_CR.match(value)
    if match is None:
        return _as_money_or_text(value)
    body = match.group(1).strip()
    if body.startswith("-"):
        return _as_money_or_text(body)
    return _as_money_or_text(f"-{body}")


def normalize_date_iso(value: Any) -> Any:
    """Reduce a date to `YYYY-MM-DD`, or leave it exactly as it was.

    An unparseable date is returned untouched, never blanked. Centracom prints
    `25TH OF THE MONTH` (F9); losing that text would destroy the only record of
    what the document actually said.
    """
    iso = getattr(value, "iso", None)
    if isinstance(iso, str):
        return iso
    if not isinstance(value, str):
        return value
    result = parse_date(value)
    return result.iso if result.parsed and result.iso else value


def uppercase(value: Any) -> Any:
    return value.upper() if isinstance(value, str) else value


def lowercase(value: Any) -> Any:
    return value.lower() if isinstance(value, str) else value


def trim(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def join_lines_comma(value: Any) -> Any:
    """`500 North Defiance Trail\nSpencerville, OH 45887` -> the two joined by `, `.

    GRAMMAR EXTENSION, added deliberately in C5a. Section 4.1 had no way to turn a
    `text_block` capture into the single comma-joined string every gold label uses
    for an address - `collapse_internal_spaces` flattens the newline to a space and
    loses the separator entirely. Ten gold files carry `bill_to_address` and eight
    carry `vendor_address`, so without this op roughly eighteen assertions were
    unreachable by any legal persona.

    The spec's own rule for adding an op is that it needs review and a reason
    rather than an agent's say-so (section 10). This is that reason. It is a pure
    formatting op: it moves no value between fields and makes no business decision.
    """
    if not isinstance(value, str):
        return value
    parts = [line.strip() for line in value.splitlines() if line.strip()]
    return ", ".join(parts)


def dedupe_preserve_order(value: Any) -> Any:
    """Drop repeats from an `all_matches` list, keeping first-seen order.

    Order is preserved rather than sorted because position is evidence: the
    first reference on the page is not interchangeable with the last, and
    `prefer_current_charges_line` relies on the ordering surviving.
    """
    if not isinstance(value, list):
        return value
    seen: list[Any] = []
    for item in value:
        if item not in seen:
            seen.append(item)
    return seen


VALUE_OPS: dict[str, Callable[[Any], Any]] = {
    "strip_internal_whitespace": strip_internal_whitespace,
    "strip_currency_symbols": strip_currency_symbols,
    "parens_to_negative": parens_to_negative,
    "trailing_cr_to_negative": trailing_cr_to_negative,
    "normalize_date_iso": normalize_date_iso,
    "uppercase": uppercase,
    "lowercase": lowercase,
    "trim": trim,
    "collapse_internal_spaces": collapse_internal_spaces,
    "join_lines_comma": join_lines_comma,
    "dedupe_preserve_order": dedupe_preserve_order,
}
