"""Opt-in library telemetry, end to end, no CLI involved.

Tasks 1-4 each proved their own piece in isolation: `Runner` writes a line when
asked (`tests/pipeline/test_runner.py`), `build_pipeline()` forwards the flag
(`tests/pipeline/test_stages_skeleton.py`), the CLI opts in for exactly one
command (`tests/test_cli_process.py`), and `problem_records()` filters a log
file correctly (`tests/test_telemetry.py`). This file proves they compose
correctly into the one thing the whole feature was built for: a pure library
caller that never touches the CLI, opts in with one argument, and gets back
exactly the documents that need a human's attention - nothing more, nothing
less.
"""

from __future__ import annotations

import json

from digitaldirection import PACK as DIGITALDIRECTION_PACK

from docintel import build_pipeline, telemetry
from docintel.adapters.vision.fake import FakeVision
from docintel.core.contract import validate_record

CENTRACOM_PDF = "docs/Centracom_0384043574_01012026_BILL.pdf"

# Same fixture pack + same real document `test_end_to_end_pipeline.py` already
# proves extracts cleanly via cached rules (disposition="processed",
# extraction_route="5a_cached", real derived amount_payable) - reused here as
# the "clean" half of this test rather than re-establishing that fact.
_WITH_DIGITALDIRECTION = [DIGITALDIRECTION_PACK]


def test_a_real_adopter_opts_in_processes_a_batch_and_retrieves_the_problem_documents(
    tmp_path, monkeypatch,
):
    """build_pipeline(telemetry=True) -> process a clean document and a
    genuinely broken one -> telemetry.problem_records() returns exactly the
    broken one. No mocking of Runner, build_pipeline, or telemetry itself -
    every piece is the real, public API a real adopter would call."""
    log_path = tmp_path / "docintel.jsonl"
    monkeypatch.setenv("DOCINTEL_TELEMETRY_LOG", str(log_path))

    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"not a real pdf at all, just garbage bytes 0000000")

    pipeline = build_pipeline(
        vision=FakeVision(), extra_packs=_WITH_DIGITALDIRECTION, telemetry=True,
    )

    good = pipeline.process(document_id="e2e-tel-good", source_path=CENTRACOM_PDF)
    bad = pipeline.process(document_id="e2e-tel-bad", source_path=str(corrupt))

    validate_record(good)
    validate_record(bad)

    # -- the pipeline itself did what test_end_to_end_pipeline.py already
    #    establishes for these two document shapes ---------------------------
    assert good["disposition"] == "processed"
    assert good["lane"] not in ("review", "low")  # a genuinely clean extraction
    assert bad["disposition"] == "dead_letter"
    assert bad["reason"]  # a human gets an actual reason, not a blank

    # -- telemetry captured both, dead-letter included -----------------------
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 2

    # -- and problem_records() finds exactly the one that needs a human,
    #    never the clean one -------------------------------------------------
    problems = telemetry.problem_records(str(log_path))
    problem_ids = {entry["document_id"] for entry in problems}
    assert problem_ids == {"e2e-tel-bad"}


def test_the_same_adopter_never_writing_telemetry_by_default(tmp_path, monkeypatch):
    """The other half of the same story: the identical workflow above, minus
    the one argument, must leave zero trace on disk - the guarantee the whole
    feature exists to not break for every caller who doesn't ask for it."""
    log_path = tmp_path / "should_not_exist.jsonl"
    monkeypatch.setenv("DOCINTEL_TELEMETRY_LOG", str(log_path))

    pipeline = build_pipeline(vision=FakeVision(), extra_packs=_WITH_DIGITALDIRECTION)
    pipeline.process(document_id="e2e-tel-default", source_path=CENTRACOM_PDF)

    assert not log_path.exists()


def test_a_mixed_format_batch_with_a_duplicate_composes_correctly_with_telemetry_on(
    tmp_path, monkeypatch,
):
    """The other real adopter scenario this feature has to survive: a batch
    isn't always one clean PDF - it's several formats, sometimes with the
    same document handed in twice. Format handling and duplicate detection
    are already exhaustively proven on their own in
    tests/test_end_to_end_formats.py; this only confirms turning telemetry
    on doesn't disturb either guarantee, and that every document - whatever
    its format, duplicate or not - still gets exactly one telemetry line."""
    log_path = tmp_path / "docintel.jsonl"
    monkeypatch.setenv("DOCINTEL_TELEMETRY_LOG", str(log_path))

    pipeline = build_pipeline(
        vision=FakeVision(), extra_packs=_WITH_DIGITALDIRECTION, telemetry=True,
    )

    txt_path = tmp_path / "note.txt"
    txt_path.write_text("Invoice Number: INV-90001\nTotal Due: 42.00\n", encoding="utf-8")

    csv_path = tmp_path / "note.csv"
    csv_path.write_text("field,value\ninvoice_number,INV-90002\ntotal_due,84.00\n", encoding="utf-8")

    records = {
        "batch-pdf": pipeline.process(document_id="batch-pdf", source_path=CENTRACOM_PDF),
        "batch-txt-first": pipeline.process(document_id="batch-txt-first", source_path=str(txt_path)),
        "batch-txt-duplicate": pipeline.process(
            document_id="batch-txt-duplicate", source_path=str(txt_path),
        ),
        "batch-csv": pipeline.process(document_id="batch-csv", source_path=str(csv_path)),
    }

    for record in records.values():
        validate_record(record)
        assert record["disposition"] != "dead_letter"

    # -- duplicate detection still works with telemetry on -------------------
    assert records["batch-pdf"]["possible_duplicate_of"] is None
    assert records["batch-txt-first"]["possible_duplicate_of"] is None
    assert records["batch-txt-duplicate"]["possible_duplicate_of"] == "batch-txt-first"

    # -- every document got exactly one telemetry line, whatever its format,
    #    in processing order, duplicate or not ------------------------------
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 4
    logged_ids = [json.loads(line)["document_id"] for line in lines]
    assert logged_ids == ["batch-pdf", "batch-txt-first", "batch-txt-duplicate", "batch-csv"]
