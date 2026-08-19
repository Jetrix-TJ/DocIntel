"""Autouse isolation so this test suite never writes into the real
`var/eval_corrections/` directory.

`AgentEscalation` sets `review_flag = True` even when `jobs=None` (see
s5c_agent.py) - so any hard-miss document processed through the real
`/process` route retains its source bytes (`webui/app.py::_retain_source`)
regardless of whether a given test wires a job queue or cares about
retention at all. Without this, running the suite would silently accumulate
files in the real, shared directory the same way a forgotten `jobs=` used to
write into the real `var/jobs.sqlite3` before that got its own isolation.
"""

from __future__ import annotations

import pytest

from docintel.webui import app as app_module


@pytest.fixture(autouse=True)
def _isolated_corrections_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "CORRECTIONS_DIR", str(tmp_path / "eval_corrections"))
