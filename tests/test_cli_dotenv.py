"""`.env` loading: `main()` must pick up a real key file for `--vision live`
to have any chance of authenticating, but must never require `python-dotenv`
to be installed just to run `--vision fake`/`--vision cassette`.
"""

from __future__ import annotations

import sys

from docintel.cli import _load_dotenv_if_available


def test_missing_dotenv_package_is_a_silent_no_op(monkeypatch):
    """A dev without the `vision` extra installed must still be able to run
    `docintel process --vision fake` - simulate `python-dotenv` being absent
    and confirm nothing raises."""
    monkeypatch.setitem(sys.modules, "dotenv", None)  # forces ImportError on `from dotenv import ...`
    _load_dotenv_if_available()  # must not raise


def test_a_dotenv_file_populates_os_environ(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("DOCINTEL_TEST_DOTENV_PROBE=from-dotenv\n")
    monkeypatch.delenv("DOCINTEL_TEST_DOTENV_PROBE", raising=False)

    _load_dotenv_if_available()

    import os

    assert os.environ.get("DOCINTEL_TEST_DOTENV_PROBE") == "from-dotenv"


def test_a_real_exported_env_var_is_not_overridden_by_dotenv(tmp_path, monkeypatch):
    """`load_dotenv()`'s own default: fill gaps, never clobber an env var a
    real shell/CI already set - a stale `.env` value must not silently win
    over the operator's actual environment."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("DOCINTEL_TEST_DOTENV_PROBE=from-dotenv\n")
    monkeypatch.setenv("DOCINTEL_TEST_DOTENV_PROBE", "from-real-env")

    _load_dotenv_if_available()

    import os

    assert os.environ.get("DOCINTEL_TEST_DOTENV_PROBE") == "from-real-env"
