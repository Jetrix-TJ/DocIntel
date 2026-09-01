"""`docintel.paths.state_root` in isolation: the one shared fallback root
that `jobs.store`, `telemetry`, and `extract.ocr_cache` each resolve to when
their own specific env var override isn't set.
"""

from __future__ import annotations

from pathlib import Path

from docintel.paths import state_root


def test_state_root_defaults_to_var(monkeypatch):
    monkeypatch.delenv("DOCINTEL_STATE_DIR", raising=False)
    assert state_root() == Path("var")


def test_state_root_honors_the_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCINTEL_STATE_DIR", str(tmp_path))
    assert state_root() == tmp_path
