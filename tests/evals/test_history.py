"""`EvalHistoryStore` in isolation - no pipeline, no scorecard, just the
store's own contract: record a card, read it back, get the trend in order.
"""

from __future__ import annotations

from docintel.evals.history import EvalHistoryStore


def _store(tmp_path):
    return EvalHistoryStore(tmp_path / "eval_history.sqlite3")


def _card(passed: int, total: int) -> dict:
    return {
        "documents": [
            {"gold_id": "doc-a", "passed": True, "passed_count": 1, "total_count": 1,
             "assertions": [{"name": "fields.x", "passed": True}]},
        ],
        "summary": {
            "total": total, "passed": passed, "failed": total - passed,
            "assertions_passed": passed, "assertions_total": total,
        },
    }


def test_record_returns_a_row_id_and_is_retrievable_by_it(tmp_path):
    store = _store(tmp_path)
    run_id = store.record(suite="full_pipeline", label="manual", vision_mode="cassette",
                           card=_card(10, 15))
    run = store.get(run_id)
    assert run is not None
    assert run.suite == "full_pipeline"
    assert run.label == "manual"
    assert run.vision_mode == "cassette"
    assert run.summary == _card(10, 15)["summary"]
    assert run.documents == _card(10, 15)["documents"]


def test_history_returns_runs_oldest_to_newest(tmp_path):
    store = _store(tmp_path)
    store.record(suite="full_pipeline", label="before", vision_mode="cassette", card=_card(10, 15))
    store.record(suite="full_pipeline", label="after", vision_mode="cassette", card=_card(12, 15))

    runs = store.history("full_pipeline")

    assert [r.label for r in runs] == ["before", "after"]
    assert [r.summary["passed"] for r in runs] == [10, 12]


def test_history_respects_limit(tmp_path):
    store = _store(tmp_path)
    for i in range(5):
        store.record(suite="full_pipeline", label=f"run-{i}", vision_mode="cassette",
                      card=_card(i, 15))

    runs = store.history("full_pipeline", limit=2)

    assert [r.label for r in runs] == ["run-3", "run-4"]


def test_history_is_scoped_to_its_own_suite(tmp_path):
    store = _store(tmp_path)
    store.record(suite="full_pipeline", label="a", vision_mode="cassette", card=_card(10, 15))
    store.record(suite="gate_classifier", label="b", vision_mode="cassette", card=_card(3, 3))

    assert [r.label for r in store.history("full_pipeline")] == ["a"]
    assert [r.label for r in store.history("gate_classifier")] == ["b"]


def test_latest_with_no_label_returns_the_most_recent_run(tmp_path):
    store = _store(tmp_path)
    store.record(suite="full_pipeline", label="a", vision_mode="cassette", card=_card(10, 15))
    store.record(suite="full_pipeline", label="b", vision_mode="cassette", card=_card(11, 15))

    latest = store.latest("full_pipeline")

    assert latest is not None
    assert latest.label == "b"


def test_latest_with_a_label_returns_the_most_recent_run_under_that_label(tmp_path):
    store = _store(tmp_path)
    store.record(suite="full_pipeline", label="main", vision_mode="cassette", card=_card(10, 15))
    store.record(suite="full_pipeline", label="candidate", vision_mode="cassette", card=_card(9, 15))
    store.record(suite="full_pipeline", label="main", vision_mode="cassette", card=_card(11, 15))

    latest_main = store.latest("full_pipeline", label="main")

    assert latest_main is not None
    assert latest_main.summary["passed"] == 11


def test_latest_returns_none_when_the_suite_has_no_runs(tmp_path):
    store = _store(tmp_path)
    assert store.latest("full_pipeline") is None


def test_find_resolves_a_numeric_id(tmp_path):
    store = _store(tmp_path)
    run_id = store.record(suite="full_pipeline", label="whatever", vision_mode="cassette",
                          card=_card(10, 15))

    found = store.find("full_pipeline", str(run_id))

    assert found is not None
    assert found.id == run_id


def test_find_resolves_a_label(tmp_path):
    store = _store(tmp_path)
    store.record(suite="full_pipeline", label="main", vision_mode="cassette", card=_card(10, 15))

    found = store.find("full_pipeline", "main")

    assert found is not None
    assert found.label == "main"


def test_find_returns_none_for_an_id_from_a_different_suite(tmp_path):
    store = _store(tmp_path)
    run_id = store.record(suite="gate_classifier", label="x", vision_mode="cassette",
                          card=_card(3, 3))

    assert store.find("full_pipeline", str(run_id)) is None


def test_documents_survive_the_json_round_trip_intact(tmp_path):
    """The whole point of storing the full card (not just the summary) is so a
    later diff can name the exact gold_id/assertion that flipped - prove the
    per-assertion detail actually comes back, not just the top-level counts."""
    store = _store(tmp_path)
    card = _card(10, 15)
    run_id = store.record(suite="full_pipeline", label="manual", vision_mode="cassette", card=card)

    run = store.get(run_id)

    assert run.documents[0]["gold_id"] == "doc-a"
    assert run.documents[0]["assertions"][0]["name"] == "fields.x"


def test_falls_back_to_the_shared_state_root_when_the_env_var_is_unset(tmp_path, monkeypatch):
    """I3 (final-review fix wave): Task 15 wired `paths.state_root()` into
    `jobs.store`/`telemetry`/`ocr_cache` but missed this module, which kept a
    hardcoded `var/eval_history.sqlite3`. With no explicit `path` and no
    `DOCINTEL_EVAL_HISTORY_DB`, the DB must land under `state_root()` (honoring
    `DOCINTEL_STATE_DIR`), not relative to whatever CWD the process started in.
    """
    monkeypatch.delenv("DOCINTEL_EVAL_HISTORY_DB", raising=False)
    monkeypatch.setenv("DOCINTEL_STATE_DIR", str(tmp_path))

    store = EvalHistoryStore()

    assert store.path == tmp_path / "eval_history.sqlite3"
    assert store.path.exists()


def test_the_modules_own_env_var_still_wins_over_the_shared_state_root(tmp_path, monkeypatch):
    """Precedence, same as every other module Task 15 touched: the specific
    override outranks the shared root, and an explicit constructor arg outranks
    both."""
    monkeypatch.setenv("DOCINTEL_STATE_DIR", str(tmp_path / "shared"))
    monkeypatch.setenv("DOCINTEL_EVAL_HISTORY_DB", str(tmp_path / "specific.sqlite3"))

    assert EvalHistoryStore().path == tmp_path / "specific.sqlite3"
    explicit = tmp_path / "explicit.sqlite3"
    assert EvalHistoryStore(explicit).path == explicit
