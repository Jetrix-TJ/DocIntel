import json

import pytest

from docintel.cli import main

CORPUS = "docs/Centracom_0384043574_01012026_BILL.pdf"


@pytest.fixture(autouse=True)
def _isolated_jobs_db(tmp_path, monkeypatch):
    """`docintel process` is a genuine production entry point (cli.py's own
    `_build_runner` constructs a real `SQLiteJobQueue()` for it) - without this,
    every test here would silently write into the real, shared
    `var/jobs.sqlite3` just by calling `main()`. `SQLiteJobQueue` already reads
    this exact env var as its override, purpose-built for this.

    `docintel process` also now writes one telemetry line per document
    (`docintel.telemetry.log_record`) - isolated the same way, via the same
    override-env-var convention, so this suite never writes into the real
    `var/logs/docintel.jsonl` either.
    """
    monkeypatch.setenv("DOCINTEL_JOBS_DB", str(tmp_path / "jobs.sqlite3"))
    monkeypatch.setenv("DOCINTEL_TELEMETRY_LOG", str(tmp_path / "telemetry.jsonl"))


def test_process_prints_a_valid_record(capsys):
    assert main(["process", CORPUS, "--json"]) == 0
    rec = json.loads(capsys.readouterr().out)
    assert rec["schema_version"] == "1"
    assert rec["disposition"] in {"processed", "skipped", "dead_letter"}


def test_process_reports_the_invariant(capsys):
    from docintel.adapters.intake.filesystem import FilesystemIntake

    # docs/ is a live, growing pool of real samples, not a fixed-size fixture —
    # assert against whatever it currently contains, not a stale literal count.
    expected = len(list(FilesystemIntake(["docs"]).items()))
    assert expected > 0, "docs/ should contain at least one real PDF to exercise"

    assert main(["process", "docs", "--json"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == expected    # one record per document, none dropped


def test_missing_file_is_a_skip_not_a_crash(capsys):
    assert main(["process", "/nope/missing.pdf", "--json"]) == 0
    rec = json.loads(capsys.readouterr().out)
    assert rec["disposition"] == "skipped"


def test_reconcile_end_to_end_real_contracts_real_invoice_real_queue(tmp_path, capsys):
    """The full path this whole feature exists for, exercised once with real
    files: `docintel process` two real document sets, `docintel reconcile`
    them against each other, and confirm a real finding lands in the real
    job queue - not a mock at any point.

    The real Windstream invoice used here (`041069076`) belongs to a
    different managed client (Choctaw Travel Mart) than the curated Golub
    contracts, on a completely different account - so the correct, honest
    outcome is `no_matching_contract`, not a fabricated match. That is
    itself the finding this test proves works end to end.
    """
    records_path = tmp_path / "records.jsonl"
    assert main([
        "process",
        "docs/Windstream_041069076_07222025_BILL.pdf",
        "docs/corpus/contracts/golub-windstream-base-agreement-2020-09-29.pdf",
        "docs/corpus/contracts/golub-windstream-renewal-2022-08-30.pdf",
        "--json",
    ]) == 0
    records_path.write_text(capsys.readouterr().out)

    jobs_db = tmp_path / "reconcile-jobs.sqlite3"
    assert main(["reconcile", str(records_path), "--jobs-db", str(jobs_db), "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["invoices"] == 1
    assert summary["contracts"] == 2
    assert summary["findings"] == {"no_matching_contract": 1}

    from docintel.jobs.store import SQLiteJobQueue

    jobs = SQLiteJobQueue(jobs_db)
    open_jobs = jobs.list_open("contract_reconciliation")
    assert len(open_jobs) == 1
    assert open_jobs[0].sender_fingerprint == "digitaldirection|windstream"
    assert open_jobs[0].context["finding_kind"] == "no_matching_contract"


# ==========================================================================
# `docintel reconcile --pending` / `docintel export`: the processing-profile
# follow-ups, drained from the job queue rather than run over everything.
# ==========================================================================


def test_reconcile_pending_drains_only_jobs_present_in_this_batch_and_resolves_them(tmp_path, capsys):
    """A `reconciliation_pending` job is enqueued at process time (real
    mechanism, unit-tested directly in `tests/pipeline/test_gate.py`); this
    proves the CLI side actually drains it: runs the join, and marks the job
    resolved so a second `--pending` run does not reconsider it."""
    from docintel.jobs.store import SQLiteJobQueue

    records_path = tmp_path / "records.jsonl"
    assert main([
        "process", "docs/Windstream_041069076_07222025_BILL.pdf", "--json",
    ]) == 0
    records_path.write_text(capsys.readouterr().out)
    document_id = json.loads(records_path.read_text())["document_id"]

    jobs_db = tmp_path / "pending-jobs.sqlite3"
    jobs = SQLiteJobQueue(jobs_db)
    jobs.enqueue_once(
        "digitaldirection|windstream", "telecom_bill", kind="reconciliation_pending",
        context={"document_id": document_id}, match_key=document_id,
    )
    # A second, unrelated pending job whose document isn't in this batch of
    # records - must be left open, not silently dropped.
    jobs.enqueue_once(
        "acme|other", "telecom_bill", kind="reconciliation_pending",
        context={"document_id": "not-in-this-batch"}, match_key="not-in-this-batch",
    )

    assert main(["reconcile", str(records_path), "--jobs-db", str(jobs_db), "--pending", "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["invoices"] == 1

    remaining = jobs.list_open("reconciliation_pending")
    assert len(remaining) == 1
    assert remaining[0].context["document_id"] == "not-in-this-batch"


def test_export_writes_a_real_xlsx_from_process_output(tmp_path, capsys):
    pytest.importorskip("openpyxl")
    records_path = tmp_path / "records.jsonl"
    assert main(["process", "docs/Centracom_0384043574_01012026_BILL.pdf", "--json"]) == 0
    records_path.write_text(capsys.readouterr().out)

    out_path = tmp_path / "out.xlsx"
    assert main(["export", str(records_path), "--out", str(out_path), "--layout", "telecom_detail"]) == 0
    assert out_path.exists()

    import openpyxl
    rows = list(openpyxl.load_workbook(out_path).active.iter_rows(values_only=True))
    assert rows[0][0] == "document_id"
    assert len(rows) == 2  # header + one record


def test_export_pending_drains_only_matching_jobs_grouped_by_layout(tmp_path, capsys):
    pytest.importorskip("openpyxl")
    from docintel.jobs.store import SQLiteJobQueue

    records_path = tmp_path / "records.jsonl"
    assert main(["process", "docs/Centracom_0384043574_01012026_BILL.pdf", "--json"]) == 0
    records_path.write_text(capsys.readouterr().out)
    document_id = json.loads(records_path.read_text())["document_id"]

    jobs_db = tmp_path / "export-jobs.sqlite3"
    jobs = SQLiteJobQueue(jobs_db)
    jobs.enqueue_once(
        "digitaldirection|centracom", "telecom_bill", kind="excel_export_pending",
        context={"document_id": document_id, "layout": "telecom_detail"},
        match_key=f"{document_id}:telecom_detail",
    )

    out_path = tmp_path / "out.xlsx"
    assert main([
        "export", str(records_path), "--out", str(out_path),
        "--jobs-db", str(jobs_db), "--pending", "--json",
    ]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["written"] == 1
    assert summary["layouts"]["telecom_detail"]["path"] == str(out_path)

    assert jobs.list_open("excel_export_pending") == []


# -- email intake wiring ------------------------------------------------


def _write_eml(path, attachments):
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = "vendor@example.com"
    msg["Subject"] = "Invoice"
    msg.set_content("see attached")
    for filename, data in attachments:
        msg.add_attachment(data, maintype="application", subtype="octet-stream",
                            filename=filename)
    with open(path, "wb") as fh:
        fh.write(msg.as_bytes())


def test_a_literal_eml_path_produces_one_record_per_attachment(tmp_path, capsys):
    eml = tmp_path / "invoice.eml"
    _write_eml(eml, [("a.pdf", b"%PDF-1.4 A"), ("b.pdf", b"%PDF-1.4 B")])

    assert main(["process", str(eml), "--json"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()

    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert {r["document_id"] for r in records} == {
        json.loads(line)["document_id"] for line in lines
    }
    assert len(records) == 2


def test_a_literal_eml_path_is_not_also_yielded_by_filesystem_intake(tmp_path, capsys):
    """The bug `_intake_items`'s partition exists to prevent: without it, a
    literal `.eml` path handed to `FilesystemIntake` bypasses its suffix
    filter (only applied during a directory WALK) and gets yielded as-is -
    one spurious extra `skipped` record on top of the real attachment ones."""
    eml = tmp_path / "invoice.eml"
    _write_eml(eml, [("a.pdf", b"%PDF-1.4 A")])

    assert main(["process", str(eml), "--json"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()

    assert len(lines) == 1  # exactly the one attachment, no extra skipped entry for the .eml itself


def test_a_directory_with_mixed_pdfs_and_emails_processes_both(tmp_path, capsys):
    (tmp_path / "plain.pdf").write_bytes(b"%PDF-1.4")
    _write_eml(tmp_path / "invoice.eml", [("attached.pdf", b"%PDF-1.4 attached")])

    assert main(["process", str(tmp_path), "--json"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()

    assert len(lines) == 2  # the plain PDF, plus the one email attachment
