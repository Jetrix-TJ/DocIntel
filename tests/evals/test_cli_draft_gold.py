"""`docintel draft-gold` through the real CLI - real file writes, sandboxed to
a temp working directory, with a fake runner standing in for the real
pipeline (the pipeline's own correctness is `docintel process`'s concern, not
this command's; `tests/evals/test_draft_gold.py` covers the fixture-shaping
logic in isolation).
"""

from __future__ import annotations

import json

from docintel.cli import main


class _FakeRunner:
    def __init__(self, record):
        self._record = record

    def process(self, document_id, source_path):
        return {**self._record, "document_id": document_id}


def _record(**over):
    base = {
        "document_id": "d1",
        "doc_type": "standard_invoice",
        "tags": [],
        "sender_fingerprint": "acme|acme_invoicing",
        "text_source": "native",
        "page_roles": ["primary"],
        "fields": {"vendor_name": "Acme Corp", "total_printed": "640.50"},
        "derived": {"document_identity": "123", "identity_basis": "invoice_number"},
        "review_flag": False,
        "regen_flag": False,
        "lane": "high",
        "disposition": "processed",
        "reference_list": [],
        "line_items": [],
        "charges": [],
        "sub_account": [],
        "scanline": None,
    }
    base.update(over)
    return base


def _patch_runner(monkeypatch, record=None):
    from docintel import cli

    monkeypatch.setattr(cli, "_build_runner", lambda args: _FakeRunner(record or _record()))


def test_draft_gold_writes_a_fixture_and_copies_the_source_pdf(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _patch_runner(monkeypatch)
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4 fake bytes")

    exit_code = main(["draft-gold", "test-1", "--source", str(source)])

    assert exit_code == 0
    gold_path = tmp_path / "docs" / "corpus" / "gold" / "test-1.json"
    assert gold_path.exists()
    fixture = json.loads(gold_path.read_text())
    assert fixture["gold_id"] == "test-1"
    assert fixture["pack"] == "acme"
    assert fixture["fields"]["total_printed"] == 640.50

    dest_pdf = tmp_path / "docs" / "corpus" / "acme" / "test-1.pdf"
    assert dest_pdf.exists()
    assert dest_pdf.read_bytes() == b"%PDF-1.4 fake bytes"
    assert fixture["source_file"] == "corpus/acme/test-1.pdf"


def test_draft_gold_prints_a_reminder_naming_every_human_only_field(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _patch_runner(monkeypatch, _record(line_items=[{"amount": "1.00"}], reference_list=[{"value": "x"}]))
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4")

    main(["draft-gold", "test-1", "--source", str(source)])

    out = capsys.readouterr().out
    assert "expected_routing" in out
    assert "line_items_complete" in out
    assert "reference_list_complete" in out


def test_draft_gold_refuses_to_overwrite_an_existing_fixture_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _patch_runner(monkeypatch)
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4")
    main(["draft-gold", "test-1", "--source", str(source)])

    exit_code = main(["draft-gold", "test-1", "--source", str(source)])

    assert exit_code == 1
    assert "already exists" in capsys.readouterr().err


def test_draft_gold_force_overwrites_an_existing_fixture(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _patch_runner(monkeypatch)
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4")
    main(["draft-gold", "test-1", "--source", str(source)])

    exit_code = main(["draft-gold", "test-1", "--source", str(source), "--force"])

    assert exit_code == 0
