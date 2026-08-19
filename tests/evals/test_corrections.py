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
