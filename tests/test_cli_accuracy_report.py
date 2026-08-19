"""`docintel accuracy-report`: a readable rendering of `replay_gold`'s own
numbers - same scoring, grouped by company/doc_type, failures named. This
file tests the rendering against a small synthetic card, not the real gold
corpus (that's what `replay-gold` itself, and `tests/test_scorecard.py`,
already exercise).
"""

from __future__ import annotations

import json

from docintel.cli import _print_accuracy_report, main


def _card():
    return {
        "summary": {"total": 3, "passed": 1, "failed": 2, "assertions_passed": 5, "assertions_total": 8},
        "documents": [
            {
                "gold_id": "acme-invoice-1",
                "passed": True,
                "passed_count": 3,
                "total_count": 3,
                "assertions": [{"name": "fields.total_printed", "passed": True, "expected": 1.0, "actual": 1.0}],
            },
            {
                "gold_id": "acme-invoice-2",
                "passed": False,
                "passed_count": 1,
                "total_count": 3,
                "assertions": [
                    {"name": "fields.total_printed", "passed": True, "expected": 2.0, "actual": 2.0},
                    {"name": "fields.invoice_number", "passed": False, "expected": "INV-2", "actual": None},
                ],
            },
            {
                "gold_id": "beta-statement-1",
                "passed": False,
                "passed_count": 1,
                "total_count": 2,
                "assertions": [
                    {"name": "fields.balance_due", "passed": False, "expected": 5.0, "actual": None},
                ],
            },
        ],
    }


def _gold_meta():
    return {
        "acme-invoice-1": ("acme", "standard_invoice"),
        "acme-invoice-2": ("acme", "standard_invoice"),
        "beta-statement-1": ("beta", "statement"),
    }


def test_the_overall_line_reports_documents_and_assertions(capsys):
    _print_accuracy_report(_card(), _gold_meta())
    out = capsys.readouterr().out
    assert "1/3 documents fully correct" in out
    assert "5/8 individual values correct" in out


def test_grouped_by_company_and_by_document_type(capsys):
    _print_accuracy_report(_card(), _gold_meta())
    out = capsys.readouterr().out
    assert "acme" in out and "beta" in out
    assert "standard_invoice" in out and "statement" in out


def test_failing_documents_are_named_with_what_they_got_wrong(capsys):
    _print_accuracy_report(_card(), _gold_meta())
    out = capsys.readouterr().out
    assert "acme-invoice-2" in out
    assert "fields.invoice_number: expected 'INV-2', got None" in out
    assert "beta-statement-1" in out
    assert "fields.balance_due: expected 5.0, got None" in out
    # the one passing document's own name shouldn't appear in the failures list
    failures_section = out.split("Failing documents")[1]
    assert "acme-invoice-1" not in failures_section


def test_a_fully_passing_card_says_so_instead_of_listing_failures(capsys):
    card = _card()
    for doc in card["documents"]:
        doc["passed"] = True
    card["summary"]["failed"] = 0
    card["summary"]["passed"] = 3

    _print_accuracy_report(card, _gold_meta())

    assert "No failing documents." in capsys.readouterr().out


def test_the_cli_command_runs_the_real_replay_and_exits_nonzero_on_failures(monkeypatch, capsys):
    from docintel import cli

    monkeypatch.setattr(cli, "_build_runner", lambda args: object())
    monkeypatch.setattr("docintel.scorecard.replay_gold", lambda runner_factory: _card())
    monkeypatch.setattr("docintel.scorecard.load_gold", lambda: [
        {"gold_id": gid, "pack": pack, "classification": {"doc_type": doc_type}}
        for gid, (pack, doc_type) in _gold_meta().items()
    ])

    result = main(["accuracy-report"])

    assert result == 1
    out = capsys.readouterr().out
    assert "docintel accuracy report" in out
    assert "By company:" in out


def test_the_json_flag_prints_the_raw_scorecard_unchanged(monkeypatch, capsys):
    monkeypatch.setattr("docintel.scorecard.replay_gold", lambda runner_factory: _card())

    assert main(["accuracy-report", "--json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload == _card()
