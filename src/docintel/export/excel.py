"""Render already-emitted records into an `.xlsx` file.

`openpyxl` is a lazy import inside `write_records_to_xlsx` itself, not a
module-level one - the `export` extra must stay optional, the same
convention `adapters/vision/gemini_adapter.py` and `webui/app.py` already
follow for their own optional dependencies. Importing this package (to read
`LAYOUTS`/`layout_names()`, e.g. from `s4b_processing_profile.py` to validate
a persona's declared export list) must never require `openpyxl` to be
installed - only actually writing a file does.

Each layout is a `(header, row_fn)` pair: `row_fn` reads one already-emitted
record's `fields`/`derived` dicts with `.get(...)`, the same "absence is a
blank cell, never invented" discipline `core/contract.py` already applies to
the JSON record itself. Adding a new vendor-specific layout is a new pair in
`LAYOUTS`, not a new code path threaded through the CLI.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Row = list[Any]
RowFn = Callable[[dict[str, Any]], Row]


class UnknownLayoutError(ValueError):
    """A `processing_profile.export`/`--layout` name isn't registered - fails
    loudly rather than silently falling back to a default layout, matching
    every other closed-vocabulary check in this codebase."""


_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@")


def _escape_formula_injection(value: Any) -> Any:
    """A leading =/+/-/@ makes Excel treat a cell as a live formula. Prefix
    with a single quote, which every spreadsheet application already renders
    as "force this to be text" - the same guard OWASP recommends for any
    CSV/XLSX export of untrusted string data. Non-strings pass through
    unchanged; a leading '-' on a real negative number never reaches this
    function as a string in the first place (see _get()'s callers, which
    keep numeric fields as numbers, not formatted strings)."""
    if isinstance(value, str) and value.startswith(_FORMULA_TRIGGER_CHARS):
        return "'" + value
    return value


def _get(record: dict[str, Any], *, field: str | None = None, derived: str | None = None) -> Any:
    if field is not None:
        return (record.get("fields") or {}).get(field)
    return (record.get("derived") or {}).get(derived)  # type: ignore[arg-type]


_STANDARD_HEADER = [
    "document_id", "vendor_name", "account_number", "bill_date",
    "total_printed", "amount_payable", "disposition", "lane",
]


def _standard_row(record: dict[str, Any]) -> Row:
    return [
        record.get("document_id"),
        _get(record, derived="vendor_name"),
        _get(record, field="account_number"),
        _get(record, field="bill_date"),
        _get(record, field="total_printed"),
        _get(record, derived="amount_payable"),
        record.get("disposition"),
        record.get("lane"),
    ]


_TELECOM_DETAIL_HEADER = [
    "document_id", "vendor_name", "account_number", "bill_date",
    "prior_balance", "payments_credits", "current_charges", "total_printed",
    "payable_basis", "amount_payable", "carried_balance",
    "disposition", "lane",
]


def _telecom_detail_row(record: dict[str, Any]) -> Row:
    return [
        record.get("document_id"),
        _get(record, derived="vendor_name"),
        _get(record, field="account_number"),
        _get(record, field="bill_date"),
        _get(record, field="prior_balance"),
        _get(record, field="payments_credits"),
        _get(record, field="current_charges"),
        _get(record, field="total_printed"),
        _get(record, derived="payable_basis"),
        _get(record, derived="amount_payable"),
        _get(record, derived="carried_balance"),
        record.get("disposition"),
        record.get("lane"),
    ]


# The closed registry. `s4b_processing_profile.py` validates a persona's
# declared export list against `layout_names()` at classification time, well
# before any record reaches this module - so an unrecognized name is caught
# per-vendor at load, not per-batch at export time.
LAYOUTS: dict[str, tuple[list[str], RowFn]] = {
    "standard": (_STANDARD_HEADER, _standard_row),
    "telecom_detail": (_TELECOM_DETAIL_HEADER, _telecom_detail_row),
}


def layout_names() -> frozenset[str]:
    return frozenset(LAYOUTS)


def write_records_to_xlsx(
    records: list[dict[str, Any]], path: str, layout: str = "standard"
) -> None:
    """One worksheet, one header row, one row per record - in that order,
    since a spreadsheet a human opens should read top-to-bottom in the order
    the records were given, not resorted by this function."""
    if layout not in LAYOUTS:
        raise UnknownLayoutError(
            f"{layout!r} is not a registered export layout - registered: {sorted(LAYOUTS)}"
        )
    header, row_fn = LAYOUTS[layout]

    from openpyxl import Workbook  # pragma: no cover - depends on the environment

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = layout
    worksheet.append(header)
    for record in records:
        row = [_escape_formula_injection(cell) for cell in row_fn(record)]
        worksheet.append(row)
    workbook.save(path)
