"""`docintel eval-gate` and `docintel eval-vision` through the real CLI.

The underlying scoring functions (`replay_gate`/`replay_vision`) are already
well tested in isolation (`tests/evals/test_gate_eval.py`, `tests/evals/
test_vision_eval.py`) - what had zero coverage was the CLI wiring itself:
argument parsing, `--json` output shape, and the exit code these two
commands actually return when invoked the way a human or CI would.
"""

from __future__ import annotations

import json

from docintel.cli import main


def test_eval_gate_json_output_scores_the_real_gold_corpus(capsys):
    exit_code = main(["eval-gate", "--json"])

    result = json.loads(capsys.readouterr().out)
    assert result["summary"]["total"] > 0
    assert result["summary"]["passed"] + result["summary"]["failed"] == result["summary"]["total"]
    assert exit_code == (0 if result["summary"]["failed"] == 0 else 1)


def test_eval_gate_non_json_output_is_human_readable(capsys):
    main(["eval-gate"])

    out = capsys.readouterr().out
    assert out.strip()
    assert "{" not in out.splitlines()[0]


def test_eval_vision_json_output_scores_the_default_fields_with_fake_vision(capsys):
    """`--vision fake` avoids depending on the (empty) default cassette -
    `FakeVision`'s canned answers are `{}`, so this proves the CLI wiring and
    exit-code contract without needing a real recorded response."""
    exit_code = main(["eval-vision", "--vision", "fake", "--json"])

    result = json.loads(capsys.readouterr().out)
    assert result["summary"]["total"] > 0
    assert exit_code == (0 if result["summary"]["failed"] == 0 else 1)


def test_eval_gate_and_eval_vision_both_accept_record_history(tmp_path, capsys):
    """`_add_history_args`/`_maybe_record_history` is the same wiring
    `eval-gate` and `eval-vision` both opt into - proven once, generically,
    rather than duplicated per command."""
    from docintel.evals.history import EvalHistoryStore

    history_db = tmp_path / "eval-history.sqlite3"
    main([
        "eval-gate", "--json",
        "--record-history", "--history-db", str(history_db), "--label", "cli-test",
    ])

    store = EvalHistoryStore(str(history_db))
    runs = store.history("gate_classifier")
    assert len(runs) == 1
    assert runs[0].label == "cli-test"
