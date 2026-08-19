"""Rendering already-emitted records into a spreadsheet.

Deliberately NOT a pipeline stage, same reasoning as `docintel.reconciliation`:
this is a second pass over records `docintel process --json` already
produced, not new state living inside `Runner.process()`. It exists because a
persona's `processing_profile.export` (`s4b_processing_profile.py`) can name
a layout an AP team needs, and nothing before this could actually produce one.
"""

from docintel.export.excel import (
    LAYOUTS,
    UnknownLayoutError,
    layout_names,
    write_records_to_xlsx,
)

__all__ = ["LAYOUTS", "UnknownLayoutError", "layout_names", "write_records_to_xlsx"]
