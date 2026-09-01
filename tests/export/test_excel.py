"""`write_records_to_xlsx`: registry dispatch, real file round-trip, absence
handled as a blank cell (never invented), unknown layout fails loudly.
"""

from __future__ import annotations

import pytest

from docintel.export import LAYOUTS, UnknownLayoutError, layout_names, write_records_to_xlsx

_RECORD = {
    "document_id": "d1",
    "fields": {
        "account_number": "0384043574",
        "bill_date": "2026-01-01",
        "prior_balance": "20123.80",
        "payments_credits": "-24120.20",
        "current_charges": "13752.60",
        "total_printed": "33876.40",
    },
    "derived": {
        "vendor_name": "CentraCom",
        "payable_basis": "current_charges",
        "amount_payable": "13752.60",
        "carried_balance": "20123.80",
    },
    "disposition": "processed",
    "lane": "high",
}


def test_layout_names_is_a_real_closed_registry():
    names = layout_names()
    assert names == frozenset(LAYOUTS)
    assert {"standard", "telecom_detail"} <= names


def test_an_unregistered_layout_fails_loudly(tmp_path):
    with pytest.raises(UnknownLayoutError, match="not_a_real_layout"):
        write_records_to_xlsx([_RECORD], str(tmp_path / "out.xlsx"), layout="not_a_real_layout")


def test_the_standard_layout_writes_a_real_readable_xlsx(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "out.xlsx"

    write_records_to_xlsx([_RECORD], str(path), layout="standard")

    wb = openpyxl.load_workbook(path)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == (
        "document_id", "vendor_name", "account_number", "bill_date",
        "total_printed", "amount_payable", "disposition", "lane",
    )
    assert rows[1] == ("d1", "CentraCom", "0384043574", "2026-01-01", "33876.40", "13752.60", "processed", "high")


def test_the_telecom_detail_layout_surfaces_the_f1_derivation(tmp_path):
    """The whole point of this layout: prior_balance, current_charges, AND
    the derived amount_payable are all visible side by side - an AP reader
    should never have to guess why the payable differs from the printed
    total."""
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "out.xlsx"

    write_records_to_xlsx([_RECORD], str(path), layout="telecom_detail")

    wb = openpyxl.load_workbook(path)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header, data = rows[0], rows[1]
    as_dict = dict(zip(header, data, strict=True))
    assert as_dict["total_printed"] == "33876.40"
    assert as_dict["amount_payable"] == "13752.60"
    assert as_dict["payable_basis"] == "current_charges"


def test_a_missing_field_is_a_blank_cell_not_an_invented_value(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "out.xlsx"
    sparse_record = {"document_id": "d2", "fields": {}, "derived": {}, "disposition": "dead_letter", "lane": None}

    write_records_to_xlsx([sparse_record], str(path), layout="standard")

    wb = openpyxl.load_workbook(path)
    rows = list(wb.active.iter_rows(values_only=True))
    assert rows[1] == ("d2", None, None, None, None, None, "dead_letter", None)


def test_multiple_records_write_in_the_given_order(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "out.xlsx"
    second = {**_RECORD, "document_id": "d2"}

    write_records_to_xlsx([_RECORD, second], str(path), layout="standard")

    wb = openpyxl.load_workbook(path)
    rows = list(wb.active.iter_rows(values_only=True))
    assert [r[0] for r in rows[1:]] == ["d1", "d2"]


def test_a_vendor_name_starting_with_equals_is_escaped_not_written_as_a_live_formula(tmp_path):
    """A vendor name of =cmd|...!A1 becomes a live formula the instant Excel opens the file.
    This is classic CSV/spreadsheet formula injection. Escape it with a leading single quote,
    the standard spreadsheet text-force guard that every application renders as text."""
    openpyxl = pytest.importorskip("openpyxl")
    records = [{
        "document_id": "d1",
        "derived": {"vendor_name": "=cmd|'/c calc'!A1"},
        "fields": {}, "disposition": "processed", "lane": "high",
    }]
    out_path = tmp_path / "out.xlsx"
    write_records_to_xlsx(records, str(out_path), layout="standard")

    wb = openpyxl.load_workbook(out_path)
    cell_value = wb.active.cell(row=2, column=2).value  # vendor_name is column 2
    assert not cell_value.startswith("="), f"Cell value should be escaped but got: {cell_value!r}"
    assert cell_value.startswith("'"), f"Cell value should start with quote but got: {cell_value!r}"


def test_formula_injection_escaping_covers_all_trigger_chars(tmp_path):
    """Test all four formula-injection trigger characters: =, +, -, @ are escaped."""
    openpyxl = pytest.importorskip("openpyxl")

    test_cases = [
        ("=cmd|'/c calc'!A1", "="),
        ("+2+5", "+"),
        ("-2+3", "-"),
        ("@SUM(A1:A10)", "@"),
    ]

    for i, (injection_str, trigger_char) in enumerate(test_cases):
        records = [{
            "document_id": f"d{i}",
            "derived": {"vendor_name": injection_str},
            "fields": {}, "disposition": "processed", "lane": "high",
        }]
        out_path = tmp_path / f"out_{i}.xlsx"
        write_records_to_xlsx(records, str(out_path), layout="standard")

        wb = openpyxl.load_workbook(out_path)
        cell_value = wb.active.cell(row=2, column=2).value  # vendor_name is column 2
        # The escaped value should start with a single quote and contain the original content
        assert cell_value.startswith("'"), (
            f"Trigger char {trigger_char!r} should be escaped with a quote, "
            f"but got: {cell_value!r}"
        )
        # The content after the quote should be the original injection string
        expected = "'" + injection_str
        assert cell_value == expected, (
            f"Escaped value should be quote + original string, "
            f"but got: {cell_value!r} instead of {expected!r}"
        )


def test_formula_injection_escaping_applies_to_telecom_detail_layout(tmp_path):
    """Ensure escaping works for both standard and telecom_detail layouts."""
    openpyxl = pytest.importorskip("openpyxl")
    records = [{
        "document_id": "d1",
        "fields": {
            "account_number": "0384043574",
            "bill_date": "2026-01-01",
        },
        "derived": {
            "vendor_name": "=cmd|'/c calc'!A1",
            "amount_payable": "13752.60",
        },
        "disposition": "processed",
        "lane": "high",
    }]
    out_path = tmp_path / "out.xlsx"
    write_records_to_xlsx(records, str(out_path), layout="telecom_detail")

    wb = openpyxl.load_workbook(out_path)
    cell_value = wb.active.cell(row=2, column=2).value  # vendor_name is column 2
    assert cell_value.startswith("'"), f"Cell value should be escaped but got: {cell_value!r}"


def test_normal_strings_starting_with_other_chars_are_not_escaped(tmp_path):
    """Ensure that normal strings that don't start with formula chars are not modified."""
    openpyxl = pytest.importorskip("openpyxl")
    records = [{
        "document_id": "d1",
        "derived": {"vendor_name": "NormalVendorName"},
        "fields": {}, "disposition": "processed", "lane": "high",
    }]
    out_path = tmp_path / "out.xlsx"
    write_records_to_xlsx(records, str(out_path), layout="standard")

    wb = openpyxl.load_workbook(out_path)
    cell_value = wb.active.cell(row=2, column=2).value  # vendor_name is column 2
    assert cell_value == "NormalVendorName", f"Normal string should not be escaped: {cell_value!r}"


def test_numeric_fields_are_unaffected_by_escaping(tmp_path):
    """Numeric fields (like total_printed) pass through as numbers, not strings,
    so they never trigger the escaping logic."""
    openpyxl = pytest.importorskip("openpyxl")
    records = [{
        "document_id": "d1",
        "fields": {
            "total_printed": "33876.40",  # This is a string representation of a number
        },
        "derived": {"vendor_name": "TestVendor"},
        "disposition": "processed",
        "lane": "high",
    }]
    out_path = tmp_path / "out.xlsx"
    write_records_to_xlsx(records, str(out_path), layout="standard")

    wb = openpyxl.load_workbook(out_path)
    # total_printed is in column 5 of standard layout
    cell_value = wb.active.cell(row=2, column=5).value
    # The value should be "33876.40" without a leading quote
    assert cell_value == "33876.40", f"Numeric string should not be escaped: {cell_value!r}"
