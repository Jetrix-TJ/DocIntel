"""`docintel eval-compare` through the real CLI, against a real history db -
not the internal `compare()` function directly (see test_compare.py for that).
"""

from __future__ import annotations

import json

from docintel.cli import main
from docintel.evals.history import EvalHistoryStore


def _card(passed_names: dict) -> dict:
    """One document, `doc-a`, whose assertions are named/passed exactly as given."""
    assertions = [{"name": name, "passed": passed} for name, passed in passed_names.items()]
    passed_count = sum(passed_names.values())
    return {
        "documents": [{
            "gold_id": "doc-a", "assertions": assertions,
            "passed": passed_count == len(assertions),
            "passed_count": passed_count, "total_count": len(assertions),
        }],
        "summary": {
            "total": 1, "passed": 1 if passed_count == len(assertions) else 0,
            "failed": 0 if passed_count == len(assertions) else 1,
            "assertions_passed": passed_count, "assertions_total": len(assertions),
        },
    }


def test_eval_compare_exits_zero_with_no_regressions(tmp_path, capsys):
    history_db = tmp_path / "eval_history.sqlite3"
    store = EvalHistoryStore(history_db)
    store.record(suite="full_pipeline", label="before", vision_mode="cassette",
                  card=_card({"fields.vendor_name": True}))
    store.record(suite="full_pipeline", label="after", vision_mode="cassette",
                  card=_card({"fields.vendor_name": True}))

    exit_code = main([
        "eval-compare", "before", "after", "--history-db", str(history_db),
    ])

    assert exit_code == 0
    assert "No regressions" in capsys.readouterr().out


def test_eval_compare_exits_one_and_names_a_real_regression(tmp_path, capsys):
    history_db = tmp_path / "eval_history.sqlite3"
    store = EvalHistoryStore(history_db)
    store.record(suite="full_pipeline", label="before", vision_mode="cassette",
                  card=_card({"fields.vendor_name": True}))
    store.record(suite="full_pipeline", label="after", vision_mode="cassette",
                  card=_card({"fields.vendor_name": False}))

    exit_code = main([
        "eval-compare", "before", "after", "--history-db", str(history_db),
    ])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "doc-a: fields.vendor_name" in out


def test_eval_compare_json_output(tmp_path, capsys):
    history_db = tmp_path / "eval_history.sqlite3"
    store = EvalHistoryStore(history_db)
    store.record(suite="full_pipeline", label="before", vision_mode="cassette",
                  card=_card({"fields.vendor_name": True}))
    store.record(suite="full_pipeline", label="after", vision_mode="cassette",
                  card=_card({"fields.vendor_name": False}))

    main(["eval-compare", "before", "after", "--history-db", str(history_db), "--json"])

    regressions = json.loads(capsys.readouterr().out)
    assert regressions == [{
        "gold_id": "doc-a", "assertion": "fields.vendor_name",
        "baseline_passed": True, "candidate_passed": False,
    }]


def test_eval_compare_resolves_runs_by_numeric_id(tmp_path, capsys):
    history_db = tmp_path / "eval_history.sqlite3"
    store = EvalHistoryStore(history_db)
    a = store.record(suite="full_pipeline", label="x", vision_mode="cassette",
                      card=_card({"fields.vendor_name": True}))
    b = store.record(suite="full_pipeline", label="y", vision_mode="cassette",
                      card=_card({"fields.vendor_name": False}))

    exit_code = main([
        "eval-compare", str(a), str(b), "--history-db", str(history_db),
    ])

    assert exit_code == 1


def test_eval_compare_fails_cleanly_for_an_unknown_baseline(tmp_path, capsys):
    history_db = tmp_path / "eval_history.sqlite3"
    EvalHistoryStore(history_db)  # create an empty store

    exit_code = main([
        "eval-compare", "nope", "also-nope", "--history-db", str(history_db),
    ])

    assert exit_code == 1
    assert "No run found for baseline" in capsys.readouterr().err
