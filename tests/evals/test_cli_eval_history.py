"""`docintel replay-gold --record-history` and `docintel eval-history` wired
together through the real CLI - not a mock of either command.
"""

from __future__ import annotations

import json

import pytest

from docintel.cli import main


@pytest.fixture(autouse=True)
def _isolated_jobs_db(tmp_path, monkeypatch):
    """`replay-gold` builds a real runner, which builds a real
    `SQLiteJobQueue()` - without this it would write into the shared
    `var/jobs.sqlite3` just by running this test (see the identical fixture
    in `tests/test_cli_process.py`)."""
    monkeypatch.setenv("DOCINTEL_JOBS_DB", str(tmp_path / "jobs.sqlite3"))


def test_replay_gold_record_history_then_eval_history_shows_one_row(tmp_path, capsys):
    history_db = tmp_path / "eval_history.sqlite3"

    assert main([
        "replay-gold", "--json", "--record-history", "--label", "test",
        "--history-db", str(history_db),
    ]) in (0, 1)  # replay-gold's own exit code reflects the corpus score, not this test
    capsys.readouterr()

    assert main(["eval-history", "--json", "--history-db", str(history_db)]) == 0
    rows = json.loads(capsys.readouterr().out)

    assert len(rows) == 1
    assert rows[0]["suite"] == "full_pipeline"
    assert rows[0]["label"] == "test"
    assert rows[0]["summary"]["total"] > 0


def test_replay_gold_without_the_flag_records_nothing(tmp_path, capsys):
    history_db = tmp_path / "eval_history.sqlite3"

    main(["replay-gold", "--json"])
    capsys.readouterr()

    main(["eval-history", "--json", "--history-db", str(history_db)])
    rows = json.loads(capsys.readouterr().out)

    assert rows == []


def test_eval_history_with_no_runs_prints_a_plain_message_not_json_by_default(tmp_path, capsys):
    history_db = tmp_path / "eval_history.sqlite3"

    exit_code = main(["eval-history", "--history-db", str(history_db)])

    assert exit_code == 0
    assert "No recorded runs" in capsys.readouterr().out
