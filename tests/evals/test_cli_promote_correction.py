"""`docintel promote-correction` through the real CLI - real file writes, just
sandboxed to a temp working directory so nothing touches the real
`docs/corpus/`.
"""

from __future__ import annotations

import json
import os

from docintel.cli import main
from docintel.evals.corrections import CorrectionStore


def _seed_correction(tmp_path, corrected_fields=None, document_id="doc-1"):
    """A correction plus its retained source PDF, laid out exactly the way a
    real webui escalation + /correct submission would leave them."""
    corrections_db = tmp_path / "corrections.sqlite3"
    store = CorrectionStore(corrections_db)

    retained_dir = tmp_path / "var" / "eval_corrections"
    retained_dir.mkdir(parents=True)
    (retained_dir / f"{document_id}.pdf").write_bytes(b"%PDF-1.4 fake bytes")

    correction_id = store.add(
        document_id=document_id,
        source_path=str(tmp_path / "gone-temp-path.pdf"),  # already deleted, like a real webui temp file
        original_record={
            "sender_fingerprint": "newvendor|newvendor",
            "classification": {
                "doc_type": "invoice", "tags": [], "text_source": "native",
                "page_count": 1, "page_roles": ["primary"],
            },
            "fields": {"vendor_name": None, "total_printed": "640.50"},
            "derived": {},
        },
        corrected_fields=(
            corrected_fields if corrected_fields is not None else {"vendor_name": "Acme Corp"}
        ),
        corrected_by="alice",
    )
    return correction_id, str(corrections_db)


def test_promote_correction_writes_a_gold_fixture_and_copies_the_retained_pdf(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    correction_id, corrections_db = _seed_correction(tmp_path)

    exit_code = main([
        "promote-correction", str(correction_id),
        "--gold-id", "test-fixture-1",
        "--corrections-db", corrections_db,
    ])

    assert exit_code == 0
    gold_path = tmp_path / "docs" / "corpus" / "gold" / "test-fixture-1.json"
    assert gold_path.exists()
    fixture = json.loads(gold_path.read_text())
    assert fixture["fields"] == {"vendor_name": "Acme Corp", "total_printed": "640.50"}
    assert fixture["gold_id"] == "test-fixture-1"
    assert fixture["pack"] == "newvendor"

    dest_pdf = tmp_path / "docs" / "corpus" / "newvendor" / "test-fixture-1.pdf"
    assert dest_pdf.exists()
    assert dest_pdf.read_bytes() == b"%PDF-1.4 fake bytes"
    assert fixture["source_file"] == "corpus/newvendor/test-fixture-1.pdf"

    out = capsys.readouterr().out
    assert "vendor_name: None -> 'Acme Corp'" in out
    assert "total_printed" in out  # listed as untouched, not as a correction


def test_promote_correction_marks_the_correction_promoted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    correction_id, corrections_db = _seed_correction(tmp_path)

    main([
        "promote-correction", str(correction_id),
        "--gold-id", "test-fixture-1", "--corrections-db", corrections_db,
    ])

    store = CorrectionStore(corrections_db)
    assert store.get(correction_id).status == "promoted"
    assert store.list_pending() == []


def test_promote_correction_defaults_the_gold_id_to_the_document_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    correction_id, corrections_db = _seed_correction(tmp_path, document_id="webui-abc123")

    main(["promote-correction", str(correction_id), "--corrections-db", corrections_db])

    assert (tmp_path / "docs" / "corpus" / "gold" / "correction-webui-abc123.json").exists()


def test_promote_correction_fails_cleanly_for_an_unknown_id(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    corrections_db = tmp_path / "corrections.sqlite3"
    CorrectionStore(corrections_db)  # create an empty store

    exit_code = main([
        "promote-correction", "999", "--corrections-db", str(corrections_db),
    ])

    assert exit_code == 1
    assert "No correction #999" in capsys.readouterr().err


def test_promote_correction_fails_cleanly_when_no_source_pdf_exists_anywhere(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    corrections_db = tmp_path / "corrections.sqlite3"
    store = CorrectionStore(corrections_db)
    correction_id = store.add(
        document_id="doc-missing", source_path=str(tmp_path / "never-existed.pdf"),
        original_record={"fields": {}}, corrected_fields={}, corrected_by="alice",
    )

    exit_code = main([
        "promote-correction", str(correction_id), "--corrections-db", str(corrections_db),
    ])

    assert exit_code == 1
    assert "No source PDF found" in capsys.readouterr().err


def test_a_confirmed_clean_correction_promotes_with_no_diff_section(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    correction_id, corrections_db = _seed_correction(tmp_path, corrected_fields={})

    main([
        "promote-correction", str(correction_id),
        "--gold-id", "clean-1", "--corrections-db", corrections_db,
    ])

    out = capsys.readouterr().out
    assert "Corrected (human-verified) fields" not in out
    fixture = json.loads((tmp_path / "docs" / "corpus" / "gold" / "clean-1.json").read_text())
    assert fixture["fields"] == {"vendor_name": None, "total_printed": "640.50"}


def test_promote_correction_refuses_to_re_promote_by_default(tmp_path, monkeypatch, capsys):
    """A re-run must not silently clobber a human's manual follow-up edit to
    the gold file it already wrote (e.g. filling in expected_routing.lane,
    which this command's own printed reminder tells them to do by hand)."""
    monkeypatch.chdir(tmp_path)
    correction_id, corrections_db = _seed_correction(tmp_path)

    first = main([
        "promote-correction", str(correction_id),
        "--gold-id", "test-fixture-1", "--corrections-db", corrections_db,
    ])
    assert first == 0

    gold_path = tmp_path / "docs" / "corpus" / "gold" / "test-fixture-1.json"
    # Simulate the human editing the fixture by hand after promotion, exactly
    # as the tool's own reminder tells them to.
    fixture = json.loads(gold_path.read_text())
    fixture["expected_routing"]["lane"] = "low"
    gold_path.write_text(json.dumps(fixture))

    second = main([
        "promote-correction", str(correction_id),
        "--gold-id", "test-fixture-1", "--corrections-db", corrections_db,
    ])

    assert second == 1
    assert "already promoted" in capsys.readouterr().err
    # The human's manual edit must have survived.
    assert json.loads(gold_path.read_text())["expected_routing"]["lane"] == "low"


def test_promote_correction_force_overwrites_an_already_promoted_fixture(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    correction_id, corrections_db = _seed_correction(tmp_path)

    main([
        "promote-correction", str(correction_id),
        "--gold-id", "test-fixture-1", "--corrections-db", corrections_db,
    ])
    exit_code = main([
        "promote-correction", str(correction_id), "--force",
        "--gold-id", "test-fixture-1", "--corrections-db", corrections_db,
    ])

    assert exit_code == 0
