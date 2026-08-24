"""`extract.xlsx_hidden.has_hidden_content`: detection only, never extraction -
does a workbook have hidden sheet/row/column content a render could never
show?"""

from __future__ import annotations

import pytest

openpyxl = pytest.importorskip("openpyxl")

from docintel.core.errors import PermanentError
from docintel.extract import xlsx_hidden


def _save(tmp_path, name, build):
    wb = openpyxl.Workbook()
    build(wb)
    path = tmp_path / name
    wb.save(path)
    return str(path)


def test_no_hidden_anything_is_false(tmp_path):
    path = _save(tmp_path, "clean.xlsx", lambda wb: wb.active.__setitem__("A1", "Invoice"))
    assert xlsx_hidden.has_hidden_content(path) is False


def test_a_hidden_column_with_data_is_true(tmp_path):
    def build(wb):
        ws = wb.active
        ws["A1"] = "Invoice"
        ws["C1"] = "adjusted total"
        ws.column_dimensions["C"].hidden = True

    path = _save(tmp_path, "hidden_col.xlsx", build)
    assert xlsx_hidden.has_hidden_content(path) is True


def test_a_hidden_but_empty_column_is_false(tmp_path):
    def build(wb):
        ws = wb.active
        ws["A1"] = "Invoice"
        ws.column_dimensions["C"].hidden = True

    path = _save(tmp_path, "hidden_empty_col.xlsx", build)
    assert xlsx_hidden.has_hidden_content(path) is False


def test_a_hidden_row_with_data_is_true(tmp_path):
    def build(wb):
        ws = wb.active
        ws["A1"] = "Invoice"
        ws["A2"] = "hidden note"
        ws.row_dimensions[2].hidden = True

    path = _save(tmp_path, "hidden_row.xlsx", build)
    assert xlsx_hidden.has_hidden_content(path) is True


def test_a_hidden_sheet_with_data_is_true(tmp_path):
    def build(wb):
        wb.active["A1"] = "Invoice"
        backup = wb.create_sheet("Backup")
        backup["A1"] = "real total"
        backup.sheet_state = "hidden"

    path = _save(tmp_path, "hidden_sheet.xlsx", build)
    assert xlsx_hidden.has_hidden_content(path) is True


def test_a_hidden_but_empty_sheet_is_false(tmp_path):
    def build(wb):
        wb.active["A1"] = "Invoice"
        backup = wb.create_sheet("Backup")
        backup.sheet_state = "hidden"

    path = _save(tmp_path, "hidden_empty_sheet.xlsx", build)
    assert xlsx_hidden.has_hidden_content(path) is False


def test_a_corrupted_file_is_a_permanent_error(tmp_path):
    path = tmp_path / "corrupt.xlsx"
    path.write_bytes(b"not a real xlsx file at all")
    with pytest.raises(PermanentError, match="could not open"):
        xlsx_hidden.has_hidden_content(str(path))
