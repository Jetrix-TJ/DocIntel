import json
from docintel.cli import main

CORPUS = "docs/Centracom_0384043574_01012026_BILL.pdf"


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
