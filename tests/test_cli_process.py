import json
from docintel.cli import main

CORPUS = "docs/Centracom_0384043574_01012026_BILL.pdf"


def test_process_prints_a_valid_record(capsys):
    assert main(["process", CORPUS, "--json"]) == 0
    rec = json.loads(capsys.readouterr().out)
    assert rec["schema_version"] == "1"
    assert rec["disposition"] in {"processed", "skipped", "dead_letter"}


def test_process_reports_the_invariant(capsys):
    assert main(["process", "docs", "--json"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 10          # one record per document, none dropped


def test_missing_file_is_a_skip_not_a_crash(capsys):
    assert main(["process", "/nope/missing.pdf", "--json"]) == 0
    rec = json.loads(capsys.readouterr().out)
    assert rec["disposition"] == "skipped"
