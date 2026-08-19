"""`docintel queue-status` and `docintel telemetry-report` through the real
CLI - real SQLite queue, real JSONL log, no mocks.
"""

from __future__ import annotations

import json

from docintel.cli import main
from docintel.jobs.store import SQLiteJobQueue


def test_queue_status_on_an_empty_queue(tmp_path, capsys):
    jobs_db = tmp_path / "jobs.sqlite3"
    SQLiteJobQueue(jobs_db)  # create an empty db

    exit_code = main(["queue-status", "--jobs-db", str(jobs_db), "--json"])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "total_open": 0, "by_kind": {}, "oldest_created_at": None, "oldest_age_hours": None,
    }


def test_queue_status_reports_depth_by_kind(tmp_path, capsys):
    jobs_db = tmp_path / "jobs.sqlite3"
    jobs = SQLiteJobQueue(jobs_db)
    jobs.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    jobs.enqueue_once("newvendor|newvendor", None, kind="persona_authoring")
    jobs.enqueue_once("newvendor2|newvendor2", None, kind="persona_authoring")

    main(["queue-status", "--jobs-db", str(jobs_db), "--json"])

    result = json.loads(capsys.readouterr().out)
    assert result["total_open"] == 3
    assert result["by_kind"] == {"prior_balance_basis": 1, "persona_authoring": 2}
    assert result["oldest_age_hours"] >= 0


def test_queue_status_does_not_fail_by_default_no_matter_the_age(tmp_path):
    jobs_db = tmp_path / "jobs.sqlite3"
    jobs = SQLiteJobQueue(jobs_db)
    jobs.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")

    exit_code = main(["queue-status", "--jobs-db", str(jobs_db)])

    assert exit_code == 0


def test_queue_status_fails_when_the_oldest_job_crosses_the_threshold(tmp_path):
    jobs_db = tmp_path / "jobs.sqlite3"
    jobs = SQLiteJobQueue(jobs_db)
    jobs.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")

    exit_code = main([
        "queue-status", "--jobs-db", str(jobs_db), "--fail-if-older-than-hours", "0",
    ])

    assert exit_code == 1


def test_queue_status_does_not_fail_when_under_the_threshold(tmp_path):
    jobs_db = tmp_path / "jobs.sqlite3"
    jobs = SQLiteJobQueue(jobs_db)
    jobs.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")

    exit_code = main([
        "queue-status", "--jobs-db", str(jobs_db), "--fail-if-older-than-hours", "24",
    ])

    assert exit_code == 0


def test_telemetry_report_with_no_log_file_is_all_zeroes(tmp_path, capsys):
    exit_code = main([
        "telemetry-report", "--log-path", str(tmp_path / "nope.jsonl"), "--json",
    ])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["total"] == 0
    assert result["dead_letter_rate"] == 0.0


def test_telemetry_report_aggregates_a_real_log_file(tmp_path, capsys):
    from docintel import telemetry

    log_path = str(tmp_path / "docintel.jsonl")
    telemetry.configure(log_path)
    telemetry.log_record({
        "document_id": "d1", "disposition": "processed", "extraction_route": "5a_cached",
        "confidence": {"a": 1.0},
    })
    telemetry.log_record({
        "document_id": "d2", "disposition": "dead_letter", "extraction_route": None,
        "confidence": {},
    })

    main(["telemetry-report", "--log-path", log_path, "--json"])

    result = json.loads(capsys.readouterr().out)
    assert result["total"] == 2
    assert result["dead_letter_rate"] == 0.5


def test_telemetry_report_non_json_output_is_human_readable(tmp_path, capsys):
    from docintel import telemetry

    log_path = str(tmp_path / "docintel.jsonl")
    telemetry.configure(log_path)
    telemetry.log_record({
        "document_id": "d1", "disposition": "processed", "extraction_route": "5a_cached",
        "confidence": {"a": 1.0},
    })

    main(["telemetry-report", "--log-path", log_path])

    out = capsys.readouterr().out
    assert "1 document(s) logged" in out
    assert "dead-letter rate" in out
