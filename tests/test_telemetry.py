"""`docintel.telemetry` in isolation - no pipeline, no CLI, just: does
`log_record` write a well-formed JSON line, and does `aggregate` compute the
right rates from whatever's on disk.
"""

from __future__ import annotations

import json

from docintel import telemetry


def _record(**over):
    base = {
        "document_id": "doc-1", "disposition": "processed", "lane": "high",
        "doc_type": "invoice", "sender_fingerprint": "acme|acme",
        "review_flag": False, "regen_flag": False, "extraction_route": "5a_cached",
        "confidence": {"vendor_name": 0.95, "total_printed": 0.99},
    }
    base.update(over)
    return base


def test_log_record_writes_one_well_formed_json_line(tmp_path):
    path = str(tmp_path / "docintel.jsonl")
    telemetry.configure(path)

    telemetry.log_record(_record())

    lines = (tmp_path / "docintel.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["document_id"] == "doc-1"
    assert entry["disposition"] == "processed"
    assert entry["extraction_route"] == "5a_cached"
    assert "logged_at" in entry


def test_log_record_computes_mean_confidence(tmp_path):
    path = str(tmp_path / "log.jsonl")
    telemetry.configure(path)

    telemetry.log_record(_record(confidence={"a": 0.8, "b": 1.0}))

    entry = json.loads((tmp_path / "log.jsonl").read_text().strip())
    assert entry["mean_confidence"] == 0.9


def test_log_record_with_no_confidence_at_all_is_none_not_a_crash(tmp_path):
    path = str(tmp_path / "log.jsonl")
    telemetry.configure(path)

    telemetry.log_record(_record(confidence={}))

    entry = json.loads((tmp_path / "log.jsonl").read_text().strip())
    assert entry["mean_confidence"] is None


def test_log_record_includes_elapsed_ms_when_given(tmp_path):
    path = str(tmp_path / "log.jsonl")
    telemetry.configure(path)

    telemetry.log_record(_record(), elapsed_ms=123.456)

    entry = json.loads((tmp_path / "log.jsonl").read_text().strip())
    assert entry["elapsed_ms"] == 123.5


def test_configure_replaces_prior_handlers_not_accumulates(tmp_path):
    """Calling configure() twice (e.g. across two tests with different tmp
    paths) must not leave the logger writing into both files."""
    first = str(tmp_path / "first.jsonl")
    second = str(tmp_path / "second.jsonl")
    telemetry.configure(first)
    telemetry.configure(second)

    telemetry.log_record(_record())

    assert not (tmp_path / "first.jsonl").exists() or (tmp_path / "first.jsonl").read_text() == ""
    assert (tmp_path / "second.jsonl").read_text().strip() != ""


def test_aggregate_on_a_missing_file_is_all_zeroes(tmp_path):
    result = telemetry.aggregate(str(tmp_path / "nope.jsonl"))
    assert result == {
        "total": 0, "dispositions": {}, "routes": {},
        "dead_letter_rate": 0.0, "escalation_rate": 0.0, "mean_confidence": None,
    }


def test_aggregate_computes_dead_letter_and_escalation_rates(tmp_path):
    path = str(tmp_path / "log.jsonl")
    telemetry.configure(path)
    telemetry.log_record(_record(document_id="d1", disposition="processed", extraction_route="5a_cached"))
    telemetry.log_record(_record(document_id="d2", disposition="dead_letter", extraction_route=None))
    telemetry.log_record(_record(document_id="d3", disposition="processed", extraction_route="5b_vision"))
    telemetry.log_record(_record(document_id="d4", disposition="processed", extraction_route="5b_vision"))

    result = telemetry.aggregate(path)

    assert result["total"] == 4
    assert result["dead_letter_rate"] == 0.25
    assert result["escalation_rate"] == 0.5
    assert result["dispositions"] == {"processed": 3, "dead_letter": 1}


def test_aggregate_averages_mean_confidence_across_documents(tmp_path):
    path = str(tmp_path / "log.jsonl")
    telemetry.configure(path)
    telemetry.log_record(_record(document_id="d1", confidence={"a": 1.0}))
    telemetry.log_record(_record(document_id="d2", confidence={"a": 0.5}))

    result = telemetry.aggregate(path)

    assert result["mean_confidence"] == 0.75


def test_aggregate_since_days_excludes_older_entries(tmp_path):
    path = str(tmp_path / "log.jsonl")
    telemetry.configure(path)
    telemetry.log_record(_record(document_id="old"))

    with open(path, "a", encoding="utf-8") as fh:
        stale = json.dumps({
            "logged_at": "2020-01-01T00:00:00+00:00", "document_id": "ancient",
            "disposition": "processed", "extraction_route": "5a_cached",
        })
        fh.write(stale + "\n")

    result = telemetry.aggregate(path, since_days=1)

    assert result["total"] == 1


def test_aggregate_skips_a_malformed_trailing_line_instead_of_crashing(tmp_path):
    """A log file is not a fixed corpus - a process killed mid-write can
    leave a truncated last line. That must not make aggregate() blind to
    every well-formed line already on disk."""
    path = str(tmp_path / "log.jsonl")
    telemetry.configure(path)
    telemetry.log_record(_record(document_id="d1"))
    telemetry.log_record(_record(document_id="d2"))

    with open(path, "a", encoding="utf-8") as fh:
        fh.write('{"document_id": "d3", "disposition": "processed"' + "\n")  # truncated, no closing brace

    result = telemetry.aggregate(path)

    assert result["total"] == 2


def test_aggregate_skips_a_blank_and_whitespace_only_line(tmp_path):
    path = str(tmp_path / "log.jsonl")
    telemetry.configure(path)
    telemetry.log_record(_record(document_id="d1"))

    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n   \n")

    result = telemetry.aggregate(path)

    assert result["total"] == 1


def test_problem_records_returns_only_dead_letter_review_and_low(tmp_path):
    path = str(tmp_path / "log.jsonl")
    telemetry.configure(path)
    telemetry.log_record(_record(document_id="d1", disposition="processed", lane="high"))
    telemetry.log_record(_record(document_id="d2", disposition="processed", lane="medium"))
    telemetry.log_record(_record(document_id="d3", disposition="processed", lane="review"))
    telemetry.log_record(_record(document_id="d4", disposition="processed", lane="low"))
    telemetry.log_record(_record(document_id="d5", disposition="dead_letter", lane=None))

    result = telemetry.problem_records(path)

    ids = {entry["document_id"] for entry in result}
    assert ids == {"d3", "d4", "d5"}


def test_problem_records_on_a_missing_file_is_an_empty_list(tmp_path):
    result = telemetry.problem_records(str(tmp_path / "nope.jsonl"))
    assert result == []


def test_problem_records_since_days_excludes_older_entries(tmp_path):
    path = str(tmp_path / "log.jsonl")
    telemetry.configure(path)
    telemetry.log_record(_record(document_id="recent", disposition="dead_letter"))

    with open(path, "a", encoding="utf-8") as fh:
        stale = json.dumps({
            "logged_at": "2020-01-01T00:00:00+00:00", "document_id": "ancient",
            "disposition": "dead_letter", "lane": None,
        })
        fh.write(stale + "\n")

    result = telemetry.problem_records(path, since_days=1)

    assert [entry["document_id"] for entry in result] == ["recent"]


def test_problem_records_skips_a_malformed_trailing_line(tmp_path):
    path = str(tmp_path / "log.jsonl")
    telemetry.configure(path)
    telemetry.log_record(_record(document_id="d1", disposition="dead_letter"))

    with open(path, "a", encoding="utf-8") as fh:
        fh.write('{"document_id": "d2", "disposition": "dead_letter"' + "\n")  # truncated

    result = telemetry.problem_records(path)

    assert [entry["document_id"] for entry in result] == ["d1"]
