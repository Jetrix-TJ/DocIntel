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
