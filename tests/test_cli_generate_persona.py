"""`docintel generate-persona`: wiring only - `generate_field_hints`'s own
request/response handling is tested exhaustively in
`tests/generation/test_persona_agent.py`. This file proves the CLI calls it
correctly and reports both outcomes without crashing.
"""

from __future__ import annotations

import json

from docintel.cli import main


class _FakeSpec:
    def __init__(self):
        self.fields = [_Field("total_printed", "currency", "bottom right")]
        self.row_groups = []
        self.notes = "a note"

    def model_dump_json(self):
        return json.dumps({
            "fields": [{"name": f.name, "type": f.type, "hint": f.hint} for f in self.fields],
            "row_groups": [],
            "notes": self.notes,
        })


class _Field:
    def __init__(self, name, type_, hint):
        self.name = name
        self.type = type_
        self.hint = hint


def test_a_successful_generation_writes_a_labelled_draft_and_prints_a_summary(tmp_path, monkeypatch, capsys):
    from docintel.generation import persona_agent

    monkeypatch.setattr(persona_agent, "generate_field_hints", lambda pdf, *, company_name, model: _FakeSpec())
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    out = tmp_path / "acme.hints.json"

    assert main(["generate-persona", str(pdf), "--company", "Acme Corp", "--out", str(out)]) == 0

    out_text = out.read_text()
    payload = json.loads(out_text)
    assert "draft" in payload["status"].lower()
    printed = capsys.readouterr().out
    assert "DRAFT" in printed
    assert "total_printed" in printed
    assert "docs/onboarding/CONFIG-SPACE.md" in printed


def test_a_generation_failure_exits_nonzero_without_a_raw_traceback(tmp_path, monkeypatch, capsys):
    from docintel.generation import persona_agent

    def _raise(pdf, *, company_name, model):
        raise RuntimeError("the model declined")

    monkeypatch.setattr(persona_agent, "generate_field_hints", _raise)
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    result = main(["generate-persona", str(pdf), "--company", "Acme Corp", "--out", str(tmp_path / "out.json")])

    assert result == 1
    assert "generation failed" in capsys.readouterr().err


def test_the_default_output_path_is_derived_from_a_slugified_company_name(tmp_path, monkeypatch):
    from docintel.generation import persona_agent

    monkeypatch.setattr(persona_agent, "generate_field_hints", lambda pdf, *, company_name, model: _FakeSpec())
    monkeypatch.chdir(tmp_path)
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    assert main(["generate-persona", str(pdf), "--company", "Milwaukee Bearing & Machining"]) == 0

    expected = tmp_path / "docs" / "onboarding" / "generated" / "milwaukee-bearing---machining.hints.json"
    assert expected.exists()
