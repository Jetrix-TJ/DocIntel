"""`SQLiteJobQueue` in isolation - no pipeline, no Flask, just the queue's own
contract: single-flight dedup, context round-trip, resolve.
"""

from __future__ import annotations

from docintel.jobs.store import SQLiteJobQueue


def _queue(tmp_path):
    return SQLiteJobQueue(tmp_path / "jobs.sqlite3")


def test_enqueue_once_creates_the_job_and_reports_that_it_did(tmp_path):
    queue = _queue(tmp_path)
    created = queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    assert created is True
    assert len(queue.list_open()) == 1


def test_enqueue_once_is_a_single_flight_per_kind_sender_and_doc_type(tmp_path):
    """A second document from the same still-unresolved sender is a duplicate
    of the same open question, not a second job - that's what the unique index
    on (kind, sender_fingerprint, doc_type) is for.
    """
    queue = _queue(tmp_path)
    first = queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    second = queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    assert first is True
    assert second is False
    assert len(queue.list_open()) == 1


def test_a_different_doc_type_is_a_distinct_job(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    created = queue.enqueue_once("northstar|edco", "credit_memo", kind="prior_balance_basis")
    assert created is True
    assert len(queue.list_open()) == 2


def test_a_different_kind_is_a_distinct_job_for_the_same_sender(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue_once("newvendor|newvendor", None, kind="persona_authoring")
    created = queue.enqueue_once("newvendor|newvendor", None, kind="prior_balance_basis")
    assert created is True
    assert len(queue.list_open()) == 2


def test_context_round_trips_through_json(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue_once(
        "northstar|edco",
        "standard_invoice",
        kind="prior_balance_basis",
        context={"prior_balance": 298.34, "current_charges": 69.62},
    )
    job = queue.list_open()[0]
    assert job.context == {"prior_balance": 298.34, "current_charges": 69.62}


def test_context_defaults_to_an_empty_dict_when_none_is_given(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue_once("northstar|edco", "standard_invoice", kind="persona_authoring")
    job = queue.list_open()[0]
    assert job.context == {}


def test_list_open_filters_by_kind(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    queue.enqueue_once("newvendor|newvendor", None, kind="persona_authoring")
    assert [j.kind for j in queue.list_open("persona_authoring")] == ["persona_authoring"]
    assert [j.kind for j in queue.list_open("prior_balance_basis")] == ["prior_balance_basis"]


def test_get_returns_none_for_an_unknown_id(tmp_path):
    queue = _queue(tmp_path)
    assert queue.get(999) is None


def test_get_returns_the_job_by_id(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    job = queue.list_open()[0]
    assert queue.get(job.id) == job


def test_resolve_marks_the_job_resolved_and_records_who_and_what(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    job = queue.list_open()[0]

    queue.resolve(job.id, {"basis": "gross"}, resolved_by="jeeva")

    resolved = queue.get(job.id)
    assert resolved.status == "resolved"
    assert resolved.resolved_by == "jeeva"
    assert resolved.resolution == {"basis": "gross"}
    assert resolved.resolved_at is not None


def test_resolved_jobs_no_longer_appear_in_list_open(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    job = queue.list_open()[0]
    queue.resolve(job.id, {"basis": "gross"}, resolved_by="jeeva")
    assert queue.list_open() == []


def test_the_unique_key_stays_taken_after_resolution(tmp_path):
    """The single-flight index covers (kind, sender_fingerprint, doc_type) for
    every row, resolved or not - a resolved job's key is not freed for reuse.
    In practice this is moot for `prior_balance_basis`: once resolved, the
    overlay file makes the underlying question not-unknown, so the tag that
    would re-trigger `enqueue_once` never fires again.
    """
    queue = _queue(tmp_path)
    queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    first = queue.list_open()[0]
    queue.resolve(first.id, {"basis": "gross"}, resolved_by="jeeva")

    created = queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    assert created is False
    assert queue.list_open() == []


def test_a_second_queue_instance_against_the_same_path_sees_the_same_jobs(tmp_path):
    """The Flask app and the pipeline stages each open their own connection
    per call - this is what makes that safe."""
    path = tmp_path / "jobs.sqlite3"
    writer = SQLiteJobQueue(path)
    writer.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")

    reader = SQLiteJobQueue(path)
    assert len(reader.list_open()) == 1


# ==========================================================================
# `match_key` (Phase 5): finer single-flight than (kind, sender_fingerprint,
# doc_type) alone, for callers like reconciliation findings that need one
# job per INVOICE, not one per vendor/doc_type.
# ==========================================================================


def test_match_key_defaults_to_empty_string_not_none(tmp_path):
    """The load-bearing detail: SQLite treats NULLs as mutually distinct in a
    unique index, so a NULL default would silently break single-flight for
    the two existing kinds instead of preserving it."""
    queue = _queue(tmp_path)
    queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    job = queue.list_open()[0]
    assert job.match_key == ""


def test_existing_kinds_are_still_single_flight_with_the_default_match_key(tmp_path):
    """Regression guard: adding the column must not change today's behavior
    for callers that never pass match_key."""
    queue = _queue(tmp_path)
    first = queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    second = queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    assert first is True
    assert second is False
    assert len(queue.list_open()) == 1


def test_different_match_keys_are_distinct_jobs_even_with_identical_everything_else(tmp_path):
    """The actual gap this phase closes: two invoices under the same vendor,
    each raising their own finding, must not collapse into one job."""
    queue = _queue(tmp_path)
    first = queue.enqueue_once(
        "digitaldirection|windstream", "telecom_bill", kind="contract_reconciliation",
        match_key="invoice-001",
    )
    second = queue.enqueue_once(
        "digitaldirection|windstream", "telecom_bill", kind="contract_reconciliation",
        match_key="invoice-002",
    )
    assert first is True
    assert second is True
    assert len(queue.list_open("contract_reconciliation")) == 2


def test_the_same_match_key_is_still_single_flight(tmp_path):
    queue = _queue(tmp_path)
    first = queue.enqueue_once(
        "digitaldirection|windstream", "telecom_bill", kind="contract_reconciliation",
        match_key="invoice-001",
    )
    second = queue.enqueue_once(
        "digitaldirection|windstream", "telecom_bill", kind="contract_reconciliation",
        match_key="invoice-001",
    )
    assert first is True
    assert second is False
    assert len(queue.list_open("contract_reconciliation")) == 1


def test_an_old_shaped_database_migrates_cleanly(tmp_path):
    """A `var/jobs.sqlite3` created before this phase has no `match_key`
    column at all - `_init_schema` must add it (and rebuild the index against
    it) without raising, and a pre-migration row must survive with
    `match_key == ''`, not vanish or corrupt."""
    import sqlite3

    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                sender_fingerprint TEXT NOT NULL,
                doc_type TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                context_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                resolved_by TEXT,
                resolution_json TEXT
            );
            CREATE UNIQUE INDEX jobs_single_flight
                ON jobs (kind, sender_fingerprint, doc_type);
            """
        )
        conn.execute(
            "INSERT INTO jobs (kind, sender_fingerprint, doc_type, status, "
            "context_json, created_at) VALUES (?, ?, ?, 'open', '{}', ?)",
            ("prior_balance_basis", "northstar|edco", "standard_invoice", "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    queue = SQLiteJobQueue(path)
    jobs = queue.list_open()
    assert len(jobs) == 1
    assert jobs[0].match_key == ""
    assert jobs[0].sender_fingerprint == "northstar|edco"

    # The rebuilt index must actually enforce single-flight post-migration.
    created = queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    assert created is False
