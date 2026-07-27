"""The extract layer: turns a PDF on disk into normalized, position-tagged text.

Everything downstream of Stage 2 reads `PageText` / `PageMeta`, never a PDF
file directly. This package is the only place that knows whether a document's
words came off the text layer or out of an OCR engine.
"""

from __future__ import annotations
