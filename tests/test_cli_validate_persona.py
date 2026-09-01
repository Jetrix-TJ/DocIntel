"""`docintel validate-persona`: wiring only - `validate_persona`'s own V1-V14
rules are tested exhaustively in `tests/grammar/test_validator.py`. This file
proves the CLI reads a persona file, resolves --pack/--pack-file correctly,
and reports both outcomes without crashing.
"""

from __future__ import annotations

import json

import pytest

from docintel.cli import main

_GOOD_PERSONA = {
    "sender_fingerprint": "acme|acme_invoicing",
    "doc_type": "standard_invoice",
    "rule_version": 1,
    "status": "active",
    "field_selectors": [
        {
            "field": "total_printed",
            "pattern": "currency",
            "region": "any-page",
            "anchor": "Total",
        },
    ],
}


def _write(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return str(path)


def test_a_structurally_valid_persona_passes_with_no_pack_given(tmp_path, capsys):
    persona_path = _write(tmp_path, "persona.json", _GOOD_PERSONA)

    assert main(["validate-persona", persona_path]) == 0

    out = capsys.readouterr().out
    assert "structurally valid" in out
    assert "wasn't checked" in out


def test_an_invalid_persona_fails_clearly(tmp_path, capsys):
    broken = json.loads(json.dumps(_GOOD_PERSONA))
    del broken["field_selectors"][0]["region"]
    persona_path = _write(tmp_path, "persona.json", broken)

    result = main(["validate-persona", persona_path])

    assert result == 1
    err = capsys.readouterr().err
    assert "INVALID" in err
    assert "(V5)" in err


def test_the_invalid_message_names_the_failing_selector(tmp_path, capsys):
    broken = json.loads(json.dumps(_GOOD_PERSONA))
    del broken["field_selectors"][0]["region"]
    persona_path = _write(tmp_path, "persona.json", broken)

    main(["validate-persona", persona_path])

    assert "total_printed" in capsys.readouterr().err


def test_a_missing_persona_file_fails_cleanly_not_with_a_traceback(tmp_path, capsys):
    result = main(["validate-persona", str(tmp_path / "nope.json")])

    assert result == 1
    assert "could not read" in capsys.readouterr().err


def test_an_unparsable_persona_file_fails_cleanly(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{not json")

    result = main(["validate-persona", str(path)])

    assert result == 1
    assert "could not read" in capsys.readouterr().err


def test_pack_checks_field_registration_and_names_the_pack_on_success(capsys, monkeypatch):
    """`northstar` is a test fixture (`tests/fixtures/packs/`), not a shipped
    pack, so `--pack northstar` needs it injected into `load_packs()` for
    this test's own duration - same narrow, explicit pattern used in
    `test_cli_process.py`'s reconcile test."""
    import docintel.packs.registry as registry
    from northstar import PACK as NORTHSTAR_PACK

    real_load_packs = registry.load_packs
    monkeypatch.setattr(registry, "load_packs", lambda: real_load_packs() + [NORTHSTAR_PACK])

    persona_path = "tests/fixtures/packs/northstar/personas/dtss.json"

    assert main(["validate-persona", persona_path, "--pack", "northstar"]) == 0

    assert "pack 'northstar'" in capsys.readouterr().out


def test_an_unknown_pack_name_fails_cleanly_and_lists_whats_registered(tmp_path, capsys, monkeypatch):
    """No pack ships by default, so this injects one (same narrow,
    test-local pattern used elsewhere in this file) purely to prove the
    error message actually NAMES what IS registered, not just what isn't."""
    import docintel.packs.registry as registry
    from spt_metals import PACK as SPT_METALS_PACK

    real_load_packs = registry.load_packs
    monkeypatch.setattr(registry, "load_packs", lambda: real_load_packs() + [SPT_METALS_PACK])

    persona_path = _write(tmp_path, "persona.json", _GOOD_PERSONA)

    result = main(["validate-persona", persona_path, "--pack", "nonexistent"])

    assert result == 1
    err = capsys.readouterr().err
    assert "nonexistent" in err
    assert "spt_metals" in err  # a real registered pack, named as a hint


def test_pack_file_checks_a_draft_unregistered_pack(capsys):
    """The persona names a field this pack doesn't register for its doc_type -
    proves --pack-file is actually loading and checking against it, not
    silently behaving like no pack was given."""
    result = main([
        "validate-persona", "tests/fixtures/packs/northstar/personas/dtss.json",
        "--pack-file", "tests/fixtures/packs/acme_freight/pack.json",
    ])

    assert result == 1
    assert "not a registered field" in capsys.readouterr().err


def test_a_missing_pack_file_fails_cleanly(tmp_path, capsys):
    persona_path = _write(tmp_path, "persona.json", _GOOD_PERSONA)

    result = main([
        "validate-persona", persona_path, "--pack-file", str(tmp_path / "nope.json"),
    ])

    assert result == 1
    assert "could not load pack file" in capsys.readouterr().err


def test_pack_file_warns_about_a_field_that_can_silently_disappear(tmp_path, capsys):
    """acme_freight's standard_invoice declares invoice_number, but this persona
    covers everything else and leaves it with no selector, not required, and
    supplied by no op - exactly the authoring gap `undeclared_risk_fields`
    exists to surface. Must still exit 0: this is a warning, not a failure."""
    persona = {
        "sender_fingerprint": "acmefreight.example|acme freight services",
        "doc_type": "standard_invoice",
        "rule_version": 1,
        "status": "active",
        "field_selectors": [
            {"field": "bill_to_name", "region": "top-left", "pattern": "text"},
            {"field": "vendor_name", "region": "header-block", "pattern": "text"},
            {"field": "invoice_date", "anchor": "Date", "region": "near-anchor", "pattern": "date"},
            {"field": "total_printed", "anchor": "Total", "region": "near-anchor", "pattern": "currency"},
            # invoice_number has NO selector at all
        ],
    }
    persona_path = _write(tmp_path, "persona.json", persona)

    result = main([
        "validate-persona", persona_path,
        "--pack-file", "tests/fixtures/packs/acme_freight/pack.json",
    ])

    assert result == 0
    captured = capsys.readouterr()
    assert "pack 'acme_freight'" in captured.out
    assert "warning:" in captured.err
    assert "invoice_number" in captured.err


def test_pack_and_pack_file_are_mutually_exclusive(tmp_path, capsys):
    persona_path = _write(tmp_path, "persona.json", _GOOD_PERSONA)

    with pytest.raises(SystemExit) as exc_info:
        main([
            "validate-persona", persona_path, "--pack", "northstar", "--pack-file", "x.json",
        ])

    assert exc_info.value.code == 2  # argparse's own usage-error exit code
