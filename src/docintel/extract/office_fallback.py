"""Tier-1 LibreOffice-free XLSX fallback: turn a workbook's visible,
populated cells into a real HTML table, so `extract.plaintext.load_document`
- the exact, unmodified reader a real `.html` file already uses - can read
it. Only reached when `extract.convert.soffice_available()` is `False` (see
`pipeline.stages.s2_filter`).

This is a genuinely different technique from the pure-Python geometry-
synthesis approach `extract.convert`'s own module docstring already
considered and rejected for the grammar engine: this module never invents
page/word coordinates for `grammar.regions` - it produces a real `.html`
file that flows through the same native-HTML reader a real `.html` input
already uses, completely unmodified.

Hidden-content exclusion mirrors `extract.xlsx_hidden.has_hidden_content`'s
own visibility rules on purpose: content invisible to a human opening the
workbook must not silently become visible to extraction here either.
"""

from __future__ import annotations

import html as html_module
import os
import tempfile

from docintel.core.errors import PermanentError


def _require_openpyxl():
    try:
        import openpyxl
    except ImportError as exc:
        raise PermanentError(
            "reading an XLSX document without LibreOffice needs the optional "
            "'openpyxl' package - pip install 'docintel[export]'"
        ) from exc
    return openpyxl


def xlsx_to_html(source_path: str) -> str:
    """Render an XLSX workbook's visible, populated cells to a temp `.html`
    file and return its path.

    Raises `PermanentError` for anything `openpyxl` cannot open, matching
    `extract.xlsx_hidden.has_hidden_content`'s discipline for the same
    failure mode.
    """
    openpyxl = _require_openpyxl()
    try:
        wb = openpyxl.load_workbook(source_path, data_only=True)
    except Exception as exc:
        raise PermanentError(
            f"could not open {os.path.basename(source_path)!r} as an XLSX workbook: {exc}"
        ) from exc

    try:
        tables_html = []
        for ws in wb.worksheets:
            if ws.sheet_state != "visible":
                continue
            table = _sheet_to_table(ws)
            if table:
                tables_html.append(table)
    finally:
        wb.close()

    out_dir = tempfile.mkdtemp(prefix="docintel-xlsxhtml-")
    out_path = os.path.join(out_dir, "converted.html")
    body = "\n".join(tables_html)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(f"<html><body>\n{body}\n</body></html>\n")
    return out_path


def _sheet_to_table(ws) -> str:
    hidden_columns = {letter for letter, dim in ws.column_dimensions.items() if dim.hidden}
    hidden_rows = {index for index, dim in ws.row_dimensions.items() if dim.hidden}

    rows_html = []
    for row in ws.iter_rows():
        if row and row[0].row in hidden_rows:
            continue
        cells = [
            cell for cell in row
            if cell.column_letter not in hidden_columns and cell.value not in (None, "")
        ]
        if not cells:
            continue
        cells_html = "".join(f"<td>{html_module.escape(str(cell.value))}</td>" for cell in cells)
        rows_html.append(f"<tr>{cells_html}</tr>")
    if not rows_html:
        return ""
    return "<table>\n" + "\n".join(rows_html) + "\n</table>"
