"""Tier-2 LibreOffice-free XLSX fallback: render a workbook's visible,
populated cells as a real image, for `pipeline.stages.s5b_vision` to hand to
a vision model exactly like any other image. Reached only when tier 1's
cached-rule extraction genuinely collapses (`s5b_vision._collapsed`) -
`pipeline.stages.s5b_vision._vision_source_path` calls this lazily, at most
once per document.

Re-reads the ORIGINAL workbook directly, not tier 1's `.html` output
(`extract.office_fallback.xlsx_to_html`), to avoid a second, avoidably-lossy
conversion hop. Hidden-content exclusion mirrors `extract.xlsx_hidden` and
`extract.office_fallback`'s own visibility rules, kept consistent on
purpose.
"""

from __future__ import annotations

import os
import tempfile

from PIL import Image, ImageDraw, ImageFont

from docintel.core.errors import PermanentError

_FONT: ImageFont.ImageFont | None = None
_ROW_HEIGHT = 26
_CHAR_WIDTH = 9
_MIN_COL_WIDTH = 80
_PADDING = 10

# A workbook this large would try to allocate a multi-gigabyte `PIL.Image`
# before any downstream size guard (e.g. `adapters.vision.gemini_adapter`'s
# `MAX_IMAGE_BYTES`) ever gets a chance to reject it - the LibreOffice-render
# path has an analogous cap already (`gemini_adapter.MAX_PAGES`); this
# pure-Python fallback needs its own equivalent since it never goes near
# that adapter code.
_MAX_ROWS = 500


def _require_openpyxl():
    try:
        import openpyxl
    except ImportError as exc:
        raise PermanentError(
            "rendering an XLSX document without LibreOffice needs the optional "
            "'openpyxl' package - pip install 'docintel[export]'"
        ) from exc
    return openpyxl


def _get_font() -> ImageFont.ImageFont:
    """Loads the fallback-rendering font on first use, not at import time -
    `office_render` is imported unconditionally by `pipeline.stages.s5b_vision`,
    which is on `build_pipeline`'s import path, so a module-level
    `ImageFont.load_default(size=...)` call would run for every `docintel`
    user, even ones who never touch an XLSX. Any failure becomes a
    `PermanentError`, mirroring `_require_openpyxl`'s discipline in this same
    file, rather than killing the whole pipeline at import time."""
    global _FONT
    if _FONT is None:
        try:
            _FONT = ImageFont.load_default(size=18)
        except Exception as exc:
            raise PermanentError(f"could not load a font to render an XLSX fallback image: {exc}") from exc
    return _FONT


def xlsx_to_image(source_path: str) -> str:
    """Render an XLSX workbook's visible, populated cells to a temp `.png`
    file with real gridlines, and return its path.

    Raises `PermanentError` for anything `openpyxl` cannot open, matching
    `extract.office_fallback.xlsx_to_html`'s discipline for the same
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
        rows = _visible_rows(wb)
    finally:
        wb.close()

    if len(rows) > _MAX_ROWS:
        raise PermanentError(
            f"{os.path.basename(source_path)!r} has {len(rows)} visible populated rows, over the "
            f"{_MAX_ROWS}-row guard for the LibreOffice-free XLSX fallback render"
        )

    if not rows:
        rows = [[""]]

    font = _get_font()
    col_count = max(len(row) for row in rows)
    col_widths = [_MIN_COL_WIDTH] * col_count
    for row in rows:
        for i, value in enumerate(row):
            col_widths[i] = max(col_widths[i], _CHAR_WIDTH * len(value) + _PADDING * 2)

    width = sum(col_widths) + 1
    height = _ROW_HEIGHT * len(rows) + 1

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    y = 0
    for row in rows:
        x = 0
        for i in range(col_count):
            value = row[i] if i < len(row) else ""
            draw.rectangle([x, y, x + col_widths[i], y + _ROW_HEIGHT], outline="black")
            draw.text((x + _PADDING, y + 4), value, fill="black", font=font)
            x += col_widths[i]
        y += _ROW_HEIGHT

    out_dir = tempfile.mkdtemp(prefix="docintel-xlsximg-")
    out_path = os.path.join(out_dir, "converted.png")
    img.save(out_path, "PNG")
    return out_path


def _visible_rows(wb) -> list[list[str]]:
    """Every visible, non-empty row's cell text, sheet by visible sheet -
    unit-tested directly (pure, no image work) for hidden-row/column
    exclusion; `xlsx_to_image` is the integration-level proof it renders."""
    rows: list[list[str]] = []
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        hidden_columns = {letter for letter, dim in ws.column_dimensions.items() if dim.hidden}
        hidden_rows = {index for index, dim in ws.row_dimensions.items() if dim.hidden}
        for row in ws.iter_rows():
            if row and row[0].row in hidden_rows:
                continue
            values = [
                str(cell.value) if cell.value not in (None, "") else ""
                for cell in row
                if cell.column_letter not in hidden_columns
            ]
            if any(v for v in values):
                rows.append(values)
    return rows
