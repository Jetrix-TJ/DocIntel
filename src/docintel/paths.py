"""One configurable root for every path docintel writes state under.

Six modules each resolved their own `var/...` path relative to the process's
CWD, with inconsistent override support - `extract.ocr_cache` and
`extract.convert_cache` had none at all. Under gunicorn (or any deployment
where CWD isn't the repo root), state scatters to wherever the process
happened to start, unpredictably.

This is the one new knob. Each module's own specific env var still wins when
set; this is only the fallback for the common root:

| Module | Its own override | Falls back to |
|---|---|---|
| `jobs.store` | `DOCINTEL_JOBS_DB` | `state_root() / "jobs.sqlite3"` |
| `telemetry` | `DOCINTEL_TELEMETRY_LOG` | `state_root() / ...` |
| `extract.ocr_cache` | `DOCINTEL_OCR_CACHE_DIR` (new) | `state_root() / "ocr-cache"` |
| `extract.convert_cache` | `DOCINTEL_CONVERT_CACHE_DIR` (new) | `state_root() / "convert-cache"` |
| `evals.history` | `DOCINTEL_EVAL_HISTORY_DB` | `state_root() / "eval_history.sqlite3"` |
| `evals.corrections` | `DOCINTEL_CORRECTIONS_DB` | `state_root() / "corrections.sqlite3"` |

Every one of those fallbacks is computed inside a function, never frozen into
a module-level constant at import time, so setting `DOCINTEL_STATE_DIR` after
`docintel` is imported still takes effect.
"""

from __future__ import annotations

import os
from pathlib import Path


def state_root() -> Path:
    """`DOCINTEL_STATE_DIR` if set, else `var` (relative to CWD, matching
    every existing default in this codebase)."""
    override = os.environ.get("DOCINTEL_STATE_DIR")
    return Path(override) if override else Path("var")
