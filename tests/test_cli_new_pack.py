"""`docintel new-pack` through the real CLI - real file writes, sandboxed to
a temp working directory.
"""

from __future__ import annotations

import json

from docintel.cli import main


def _hints_file(tmp_path, wrapped=True):
    spec = {
        "fields": [{"name": "total_printed", "type": "currency", "hint": "bottom right"}],
        "row_groups": [],
        "notes": "a note",
    }
    payload = {
        "status": "draft - not reviewed, do not use in production",
        "company_name": "Acme Corp",
        "source_pdf": "sample.pdf",
        "field_vocabulary_version": ["total_printed"],
        "spec": spec,
    } if wrapped else spec
    path = tmp_path / "acme.hints.json"
    path.write_text(json.dumps(payload))
    return str(path)


def test_new_pack_writes_a_pack_and_a_persona(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    exit_code = main([
        "new-pack", "acme", "--company", "Acme Corp", "--doc-type", "standard_invoice",
    ])

    assert exit_code == 0
    pack_path = tmp_path / "docs" / "onboarding" / "generated" / "acme" / "pack.json"
    persona_path = tmp_path / "docs" / "onboarding" / "generated" / "acme" / "personas" / "acme.json"
    assert pack_path.exists()
    assert persona_path.exists()

    pack = json.loads(pack_path.read_text())
    assert pack["name"] == "acme"
    assert pack["doc_types"] == ["standard_invoice"]

    persona = json.loads(persona_path.read_text())
    assert persona["sender_fingerprint"] == "acme|acme"
    assert persona["field_selectors"] == []

    out = capsys.readouterr().out
    assert "validate-persona" in out


def test_new_pack_supports_more_than_one_doc_type(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    main([
        "new-pack", "acme", "--company", "Acme Corp",
        "--doc-type", "standard_invoice", "--doc-type", "credit_memo",
    ])

    pack = json.loads((tmp_path / "docs" / "onboarding" / "generated" / "acme" / "pack.json").read_text())
    assert pack["doc_types"] == ["standard_invoice", "credit_memo"]
    assert len(pack["ladder"]["rungs"]) == 2


def test_new_pack_seeds_field_selectors_from_a_wrapped_hints_draft(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    hints_path = _hints_file(tmp_path, wrapped=True)

    main([
        "new-pack", "acme", "--company", "Acme Corp",
        "--doc-type", "standard_invoice", "--hints", hints_path,
    ])

    persona = json.loads(
        (tmp_path / "docs" / "onboarding" / "generated" / "acme" / "personas" / "acme.json").read_text()
    )
    assert persona["field_selectors"][0]["field"] == "total_printed"


def test_new_pack_accepts_an_unwrapped_hint_spec_too(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    hints_path = _hints_file(tmp_path, wrapped=False)

    main([
        "new-pack", "acme", "--company", "Acme Corp",
        "--doc-type", "standard_invoice", "--hints", hints_path,
    ])

    persona = json.loads(
        (tmp_path / "docs" / "onboarding" / "generated" / "acme" / "personas" / "acme.json").read_text()
    )
    assert persona["field_selectors"][0]["field"] == "total_printed"


def test_new_pack_vendor_overrides_the_default_persona_slug(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    main([
        "new-pack", "acme", "--company", "Acme Corp", "--doc-type", "standard_invoice",
        "--vendor", "acme_east_branch",
    ])

    persona_path = tmp_path / "docs" / "onboarding" / "generated" / "acme" / "personas" / "acme_east_branch.json"
    assert persona_path.exists()
    assert json.loads(persona_path.read_text())["sender_fingerprint"] == "acme|acme_east_branch"


def test_new_pack_refuses_to_overwrite_an_existing_scaffold_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    main(["new-pack", "acme", "--company", "Acme Corp", "--doc-type", "standard_invoice"])

    exit_code = main(["new-pack", "acme", "--company", "Acme Corp", "--doc-type", "standard_invoice"])

    assert exit_code == 1
    assert "already exists" in capsys.readouterr().err


def test_new_pack_force_overwrites_an_existing_scaffold(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    main(["new-pack", "acme", "--company", "Acme Corp", "--doc-type", "standard_invoice"])

    exit_code = main([
        "new-pack", "acme", "--company", "Acme Corp", "--doc-type", "standard_invoice", "--force",
    ])

    assert exit_code == 0


def test_new_pack_fails_cleanly_when_the_hints_file_is_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    exit_code = main([
        "new-pack", "acme", "--company", "Acme Corp", "--doc-type", "standard_invoice",
        "--hints", str(tmp_path / "nope.json"),
    ])

    assert exit_code == 1
    assert "could not read hints file" in capsys.readouterr().err
