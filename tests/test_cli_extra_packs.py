"""`docintel process --extra-packs` / `DOCINTEL_EXTRA_PACKS`: the CLI path to
`build_pipeline(extra_packs=[...])` (already a library API - see CLAUDE.md's
"Two ways to add vendor data" section) for an adopter who finished writing and
validating their own `pack.json` but had no way to actually run `docintel
process` against it.

`Runner` does not expose a `packs` attribute - the registered packs live on
the `Classify` stage (`runner.stages`, the stage named `"classify"`, whose
`.packs` is the exact list `build_pipeline` built from `load_packs() +
extra_packs`; see `tests/pipeline/test_stages_skeleton.py`'s
`test_build_pipeline_appends_extra_packs_to_the_shipped_ones` for the
established pattern this file follows for the unit-level checks. The final
test in this file additionally proves the loaded pack is genuinely usable -
not just present in a list - by running a real document through `docintel
process --extra-packs` end to end and confirming it gets claimed and
classified by the adopter's own pack rather than falling through as an
unclaimed generic document.
"""

from __future__ import annotations

import argparse
import json
import os

from PIL import Image, ImageDraw, ImageFont

from docintel.cli import _build_runner, main

_FONT = ImageFont.load_default(size=26)

# A synthetic, structurally valid pack, kept minimal - only what
# grammar/schema validation and Classify actually need. Mirrors
# `tests/fixtures/packs/acme_freight/pack.json` in shape.
_PACK_NAME = "adopter_widgets"


def _pack_spec(name: str = _PACK_NAME) -> dict:
    return {
        "name": name,
        "default_currency": "USD",
        "doc_types": ["standard_invoice"],
        "fields": {
            "standard_invoice": {"all": [], "required": [], "any_of": [], "derived_only": []}
        },
        "claim": {
            "rules": [{
                "kind": "corroborated_markers", "scope": "primary",
                "pairs": [{"marker": "invoice number", "requires": "total"}],
            }],
            "vetoes": [],
        },
        "ladder": {
            "default": "standard_invoice",
            "rungs": [{
                "name": "confirm", "doc_type": "standard_invoice",
                "when": {"signal": "pattern_in_scope", "params": {"pattern": "Invoice", "scope": "primary"}},
            }],
        },
        "tags": [],
    }


def _write_pack(tmp_path, name: str = _PACK_NAME):
    pack_dir = tmp_path / name
    (pack_dir / "personas").mkdir(parents=True, exist_ok=True)
    pack_path = pack_dir / "pack.json"
    pack_path.write_text(json.dumps(_pack_spec(name)))
    return pack_path


def _classify_stage(runner):
    return next(s for s in runner.stages if s.name == "classify")


# ===========================================================================
# `_build_runner`: the flag and the env-var fallback actually reach
# `build_pipeline(extra_packs=[...])`.
# ===========================================================================


def test_extra_packs_flag_loads_a_pack_file_into_the_runners_classifier(tmp_path):
    pack_path = _write_pack(tmp_path)

    args = argparse.Namespace(vision=None, cassette=None, extra_packs=[str(pack_path)])
    runner = _build_runner(args)

    classify = _classify_stage(runner)
    assert any(p.name == _PACK_NAME for p in classify.packs)


def test_extra_packs_flag_accepts_more_than_one_path(tmp_path):
    a = _write_pack(tmp_path, "adopter_a")
    b = _write_pack(tmp_path, "adopter_b")

    args = argparse.Namespace(vision=None, cassette=None, extra_packs=[str(a), str(b)])
    runner = _build_runner(args)

    names = {p.name for p in _classify_stage(runner).packs}
    assert {"adopter_a", "adopter_b"} <= names


def test_no_extra_packs_given_leaves_the_pack_list_unchanged():
    """Omitting `--extra-packs` entirely (the CLI's real default) must not
    error and must not add anything - purely additive, same discipline as
    `build_pipeline`'s own `extra_packs=None` default."""
    args = argparse.Namespace(vision=None, cassette=None, extra_packs=None)
    runner = _build_runner(args)

    assert _classify_stage(runner).packs == []


def test_env_var_fallback_used_when_the_flag_is_not_given(tmp_path, monkeypatch):
    pack_path = _write_pack(tmp_path, "env_pack")
    monkeypatch.setenv("DOCINTEL_EXTRA_PACKS", str(pack_path))

    args = argparse.Namespace(vision=None, cassette=None, extra_packs=None)
    runner = _build_runner(args)

    assert any(p.name == "env_pack" for p in _classify_stage(runner).packs)


def test_env_var_fallback_is_os_pathsep_separated(tmp_path, monkeypatch):
    a = _write_pack(tmp_path, "env_pack_a")
    b = _write_pack(tmp_path, "env_pack_b")
    monkeypatch.setenv("DOCINTEL_EXTRA_PACKS", os.pathsep.join([str(a), str(b)]))

    args = argparse.Namespace(vision=None, cassette=None, extra_packs=None)
    runner = _build_runner(args)

    names = {p.name for p in _classify_stage(runner).packs}
    assert {"env_pack_a", "env_pack_b"} <= names


def test_explicit_flag_takes_precedence_over_the_env_var(tmp_path, monkeypatch):
    """An operator who can pass CLI flags gets exactly what they asked for -
    the env var is a fallback for a caller who *can't* pass flags, not a
    second source that merges in behind their back."""
    env_pack = _write_pack(tmp_path, "env_pack")
    flag_pack = _write_pack(tmp_path, "flag_pack")
    monkeypatch.setenv("DOCINTEL_EXTRA_PACKS", str(env_pack))

    args = argparse.Namespace(vision=None, cassette=None, extra_packs=[str(flag_pack)])
    runner = _build_runner(args)

    names = {p.name for p in _classify_stage(runner).packs}
    assert "flag_pack" in names
    assert "env_pack" not in names


# ===========================================================================
# The real CLI arg parser: `--extra-packs` is actually wired onto `process`.
# ===========================================================================


def test_process_subcommand_accepts_the_extra_packs_flag(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("DOCINTEL_JOBS_DB", str(tmp_path / "jobs.sqlite3"))
    monkeypatch.setenv("DOCINTEL_TELEMETRY_LOG", str(tmp_path / "telemetry.jsonl"))
    pack_path = _write_pack(tmp_path)

    exit_code = main([
        "process", "/nope/missing.pdf",
        "--extra-packs", str(pack_path),
        "--vision", "fake",
        "--json",
    ])

    assert exit_code == 0
    rec = json.loads(capsys.readouterr().out)
    assert rec["disposition"] == "skipped"  # proves the flag parsed and the run completed


# ===========================================================================
# End to end: the loaded pack is genuinely USABLE by the pipeline, not just
# present in a list - a real document only the adopter's own pack recognizes
# gets claimed and classified by it when run through `docintel process
# --extra-packs`, the same way `test_generic_library_contract.py` proves the
# library-level `build_pipeline(extra_packs=[...])` API works end to end.
# ===========================================================================


def _text_image(path, lines: list[str], size=(900, 300)) -> str:
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((20, 20 + i * 45), line, font=_FONT, fill="black")
    img.save(path)
    return str(path)


def test_a_document_only_the_extra_pack_claims_is_processed_end_to_end(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("DOCINTEL_JOBS_DB", str(tmp_path / "jobs.sqlite3"))
    monkeypatch.setenv("DOCINTEL_TELEMETRY_LOG", str(tmp_path / "telemetry.jsonl"))
    pack_path = _write_pack(tmp_path)
    doc = _text_image(tmp_path / "invoice.png", [
        "ADOPTER WIDGETS CO", "Invoice Number: INV-9001", "Total 250.00",
    ])

    assert main([
        "process", doc,
        "--extra-packs", str(pack_path),
        "--vision", "fake",
        "--json",
    ]) == 0

    rec = json.loads(capsys.readouterr().out)
    assert rec["disposition"] == "processed"
    assert "unclaimed_document" not in rec["tags"]
    assert rec["doc_type"] == "standard_invoice"


def test_the_same_document_is_unclaimed_without_extra_packs(tmp_path, capsys, monkeypatch):
    """Control for the previous test: without `--extra-packs`, the exact same
    document falls through as unclaimed - proving the claim above is really
    coming from the adopter's pack, not some other default behavior."""
    monkeypatch.setenv("DOCINTEL_JOBS_DB", str(tmp_path / "jobs.sqlite3"))
    monkeypatch.setenv("DOCINTEL_TELEMETRY_LOG", str(tmp_path / "telemetry.jsonl"))
    doc = _text_image(tmp_path / "invoice.png", [
        "ADOPTER WIDGETS CO", "Invoice Number: INV-9001", "Total 250.00",
    ])

    assert main(["process", doc, "--vision", "fake", "--json"]) == 0

    rec = json.loads(capsys.readouterr().out)
    assert "unclaimed_document" in rec["tags"]
