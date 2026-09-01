"""`CorrectionStore` in isolation - no webui, no pipeline, just the store's
own contract: add a correction, read it back, promote it.
"""

from __future__ import annotations

from docintel.evals.corrections import CorrectionStore


def _store(tmp_path):
    return CorrectionStore(tmp_path / "corrections.sqlite3")


def test_add_returns_a_row_id_and_is_retrievable_by_it(tmp_path):
    store = _store(tmp_path)
    correction_id = store.add(
        document_id="doc-1", source_path="/x.pdf",
        original_record={"fields": {"vendor_name": None}},
        corrected_fields={"vendor_name": "Acme Corp"},
        corrected_by="alice",
    )
    correction = store.get(correction_id)
    assert correction is not None
    assert correction.document_id == "doc-1"
    assert correction.corrected_fields == {"vendor_name": "Acme Corp"}
    assert correction.corrected_by == "alice"
    assert correction.status == "pending_promotion"


def test_a_confirmed_clean_correction_has_an_empty_corrected_fields_dict(tmp_path):
    store = _store(tmp_path)
    correction_id = store.add(
        document_id="doc-1", source_path="/x.pdf",
        original_record={"fields": {"vendor_name": "Acme Corp"}},
        corrected_fields={},
        corrected_by="alice",
    )
    correction = store.get(correction_id)
    assert correction.corrected_fields == {}


def test_job_id_is_optional_and_defaults_to_none(tmp_path):
    store = _store(tmp_path)
    correction_id = store.add(
        document_id="doc-1", source_path="/x.pdf",
        original_record={}, corrected_fields={}, corrected_by="alice",
    )
    assert store.get(correction_id).job_id is None


def test_job_id_round_trips_when_given(tmp_path):
    store = _store(tmp_path)
    correction_id = store.add(
        document_id="doc-1", source_path="/x.pdf",
        original_record={}, corrected_fields={}, corrected_by="alice", job_id=42,
    )
    assert store.get(correction_id).job_id == 42


def test_get_returns_none_for_an_unknown_id(tmp_path):
    store = _store(tmp_path)
    assert store.get(999) is None


def test_list_pending_returns_only_unpromoted_corrections_oldest_first(tmp_path):
    store = _store(tmp_path)
    first = store.add(document_id="doc-1", source_path="/a.pdf",
                       original_record={}, corrected_fields={}, corrected_by="alice")
    second = store.add(document_id="doc-2", source_path="/b.pdf",
                        original_record={}, corrected_fields={}, corrected_by="bob")
    store.mark_promoted(first)

    pending = store.list_pending()

    assert [c.id for c in pending] == [second]


def test_mark_promoted_updates_status(tmp_path):
    store = _store(tmp_path)
    correction_id = store.add(document_id="doc-1", source_path="/x.pdf",
                               original_record={}, corrected_fields={}, corrected_by="alice")

    store.mark_promoted(correction_id)

    assert store.get(correction_id).status == "promoted"


def test_falls_back_to_the_shared_state_root_when_the_env_var_is_unset(tmp_path, monkeypatch):
    """I3 (final-review fix wave): Task 15 wired `paths.state_root()` into
    `jobs.store`/`telemetry`/`ocr_cache` but missed this module, which kept a
    hardcoded `var/corrections.sqlite3`. With no explicit `path` and no
    `DOCINTEL_CORRECTIONS_DB`, the DB must land under `state_root()` (honoring
    `DOCINTEL_STATE_DIR`), not relative to whatever CWD the process started in.
    """
    monkeypatch.delenv("DOCINTEL_CORRECTIONS_DB", raising=False)
    monkeypatch.setenv("DOCINTEL_STATE_DIR", str(tmp_path))

    store = CorrectionStore()

    assert store.path == tmp_path / "corrections.sqlite3"
    assert store.path.exists()


def test_the_modules_own_env_var_still_wins_over_the_shared_state_root(tmp_path, monkeypatch):
    """Precedence, same as every other module Task 15 touched: the specific
    override outranks the shared root, and an explicit constructor arg outranks
    both."""
    monkeypatch.setenv("DOCINTEL_STATE_DIR", str(tmp_path / "shared"))
    monkeypatch.setenv("DOCINTEL_CORRECTIONS_DB", str(tmp_path / "specific.sqlite3"))

    assert CorrectionStore().path == tmp_path / "specific.sqlite3"
    explicit = tmp_path / "explicit.sqlite3"
    assert CorrectionStore(explicit).path == explicit
