"""The extract layer: turns a PDF on disk into normalized, position-tagged text.

Everything downstream of Stage 2 reads `PageText` / `PageMeta`, never a PDF
file directly. This package is the only place that knows whether a document's
words came off the text layer or out of an OCR engine.
"""

from __future__ import annotations

# `from __future__ import annotations` above binds this package's own
# `annotations` attribute to a `__future__._Feature` object. Left alone,
# `from docintel.extract import annotations` would resolve to that feature
# flag instead of the `annotations.py` submodule (finding module.py) —
# `getattr` finds the pre-existing package attribute and never triggers the
# submodule import. The explicit dotted import below runs the real
# submodule import unconditionally and overwrites the shadowed attribute
# with it, so both `from docintel.extract import annotations` and
# `docintel.extract.annotations` resolve correctly from here on.
import docintel.extract.annotations as annotations  # noqa: E402,F401
