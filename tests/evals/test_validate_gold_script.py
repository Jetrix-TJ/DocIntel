"""`docs/corpus/validate_gold.py`'s own `main()` entry point.

`test_promote.py`/`test_draft_gold.py` already exercise `Report`/`check()`
directly, in-process. This file is the one thing those cannot cover: running
the script exactly as a human or CI would - `python docs/corpus/
validate_gold.py` - because the bug this guards against (a `UnicodeEncodeError`
crash on Windows' default cp1252 console encoding, printing the ✓/✗ result
markers) only reproduces through the real stdout stream a subprocess gets,
not through pytest's own captured, UTF-8-safe stdout.
"""

from __future__ import annotations

import os
import subprocess
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPT = os.path.join(REPO_ROOT, "docs", "corpus", "validate_gold.py")


def test_the_script_exits_zero_on_a_clean_corpus():
    result = subprocess.run(
        [sys.executable, SCRIPT], cwd=REPO_ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "failures       : 0" in result.stdout


def test_the_script_does_not_crash_on_a_cp1252_console():
    """The real bug: Windows' default console codepage cannot encode the ✓/✗
    result markers, so a clean, 116/116-checks-passing run crashed with a raw
    `UnicodeEncodeError` traceback instead of exiting 0 - a CI step reading
    "exit 1 / traceback" would misdiagnose a fully consistent gold corpus as
    broken. Forcing `PYTHONIOENCODING=cp1252` reproduces the encoding a real
    Windows console uses regardless of which platform this test itself runs
    on."""
    env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONUTF8="0")
    result = subprocess.run(
        [sys.executable, SCRIPT], cwd=REPO_ROOT, capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "UnicodeEncodeError" not in result.stderr
    assert "Traceback" not in result.stderr
