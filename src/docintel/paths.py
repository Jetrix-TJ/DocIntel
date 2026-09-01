"""One configurable root for every path docintel writes state under.

Three modules (jobs.store, telemetry, extract.ocr_cache) each resolved their
own `var/...` path relative to the process's CWD, with inconsistent override
support - ocr_cache had none at all. Under gunicorn (or any deployment where
CWD isn't the repo root), state scatters to wherever the process happened to
start, unpredictably. This is the one new knob; each module's own specific
env var (DOCINTEL_JOBS_DB, DOCINTEL_TELEMETRY_LOG) still wins when set - this
is only the fallback for the common root, and ocr_cache's new override.
"""

from __future__ import annotations

import os
from pathlib import Path


def state_root() -> Path:
    """`DOCINTEL_STATE_DIR` if set, else `var` (relative to CWD, matching
    every existing default in this codebase)."""
    override = os.environ.get("DOCINTEL_STATE_DIR")
    return Path(override) if override else Path("var")
