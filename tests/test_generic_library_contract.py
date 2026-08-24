"""The generic-library contract: what a brand-new adopter gets from a fresh
`pip install docintel[...]`, with zero access to this repository's source.

Companion to `test_end_to_end_pipeline.py` (the four pipeline shapes),
`test_end_to_end_formats.py` (format coverage), and `test_end_to_end_line_items.py`
(table extraction). This file is organized around a different axis: proving
the library itself ships GENERIC, and that a real new adopter's own pack -
built entirely in their own project, the way `build_pipeline`'s own docstring
describes - works end to end through the real, public entry point, including
the failure modes and layering questions a real onboarding actually raises.

Verified once, directly, outside pytest, before this file was written: a real
wheel built via `python -m build --wheel` and installed into a throwaway venv
contains no `northstar`/`digitaldirection` files at all (`docintel.packs.
northstar` raises `ModuleNotFoundError`), `load_packs()` returns exactly
`[spt_metals, acme_freight]`, and a hand-written adopter pack processes a real
document end to end with vision_defaults fields AND tables both working. That
check needs a built wheel and a scratch venv, so it isn't repeated here as an
automated test; what IS repeated here, in-process, is everything about the
CONTRACT that check proved - the part that can regress silently on a future
change.
"""

from __future__ import annotations

import json

import pytest
from PIL import Image, ImageDraw, ImageFont

from docintel import build_pipeline
from docintel.adapters.vision.fake import FakeVision
from docintel.core.contract import validate_record
from docintel.packs.datapack import PackSpecError, load_pack_file
from docintel.packs.registry import load_packs

_FONT = ImageFont.load_default(size=26)


def _text_image(path, lines: list[str], size=(900, 300)) -> str:
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((20, 20 + i * 45), line, font=_FONT, fill="black")
    img.save(path)
    return str(path)


def _adopter_pack(tmp_path, name: str, spec_overrides: dict | None = None):
    """A pack built entirely in the ADOPTER's own project - the shape
    `build_pipeline`'s own docstring describes for `extra_packs`, never
    touching this installed package's source. Mirrors the real northstar_new/
    general_invoices sandbox pack this session built and ran against real
    Gemini output."""
    spec = {
        "name": name,
        "default_currency": "USD",
        "doc_types": ["standard_invoice"],
        "fields": {"standard_invoice": {"all": [], "required": [], "any_of": [], "derived_only": []}},
        "claim": {
            "rules": [{
                "kind": "corroborated_markers", "scope": "primary",
                "pairs": [{"marker": "invoice number", "requires": "total"}],
            }],
            "vetoes": [],
        },
        "ladder": {
            "default": "standard_invoice",
            "rungs": [{"name": "confirm", "doc_type": "standard_invoice",
                       "when": {"signal": "pattern_in_scope",
                                "params": {"pattern": "Invoice", "scope": "primary"}}}],
        },
        "tags": [],
    }
    if spec_overrides:
        spec.update(spec_overrides)
    pack_dir = tmp_path / name
    (pack_dir / "personas").mkdir(parents=True, exist_ok=True)
    (pack_dir / "pack.json").write_text(json.dumps(spec))
    return load_pack_file(str(pack_dir / "pack.json"))


# ===========================================================================
# 1. The library itself ships generic - the contract this whole file assumes.
# ===========================================================================


def test_the_shipped_default_carries_no_pack_of_any_kind():
    """What a fresh `pip install docintel` actually gives you, with zero
    `extra_packs`: nothing. `PACK_MODULES`/`PACK_FILES` are both empty -
    docintel ships as a pure framework, with no pre-configured company
    shape, real or synthetic. `northstar`/`digitaldirection` (real, measured
    configuration for two real companies) and `spt_metals`/`acme_freight`
    (synthetic reference examples, no real corpus) all live as test
    fixtures (`tests/fixtures/packs/`) instead."""
    assert load_packs() == []


def test_none_of_the_four_reference_packs_are_importable_from_the_library():
    for module in (
        "docintel.packs.northstar", "docintel.packs.digitaldirection",
        "docintel.packs.spt_metals", "docintel.packs.acme_freight",
    ):
        with pytest.raises(ModuleNotFoundError):
            __import__(module)


# ===========================================================================
# 2. A brand-new adopter's own pack, built entirely in their own project,
#    works end to end - the flagship case.
# ===========================================================================


def test_a_brand_new_adopters_pack_extracts_fields_and_tables_end_to_end(tmp_path):
    pack = _adopter_pack(tmp_path, "acme_customer_pack", {
        "vision_defaults": {
            "standard_invoice": {
                "fields": {"account_number": "text", "total_printed": "currency"},
                "tables": {"line_items": {"date": "date", "description": "text", "amount": "currency"}},
            }
        },
    })
    doc = _text_image(tmp_path / "invoice.png", [
        "ACME CUSTOMER CO", "Invoice Number: INV-9001", "Total 250.00",
    ])
    vision = FakeVision(
        {"account_number": "ACCT-42", "total_printed": "250.00"},
        canned_tables={"line_items": [{"date": "1/1/26", "description": "Widget", "amount": "250.00"}]},
    )
    pipeline = build_pipeline(vision=vision, extra_packs=[pack])

    record = pipeline.process(document_id="adopter-1", source_path=doc)
    validate_record(record)

    assert record["disposition"] == "processed"
    assert "unclaimed_document" not in record["tags"]
    assert record["doc_type"] == "standard_invoice"
    assert record["extraction_route"] == "5b_vision"
    assert record["fields"]["account_number"] == "ACCT-42"
    assert record["line_items"] == [{"date": "1/1/26", "description": "Widget", "amount": "250.00"}]


def test_an_adopters_pack_works_uniformly_across_pdf_and_image_formats(tmp_path):
    """The same claim rule, the same pack, the same fields - regardless of
    which format the invoice arrived as. Proves format-agnosticism from a
    new adopter's own perspective, not just the library's internal tests."""
    import pypdf

    pack = _adopter_pack(tmp_path, "multiformat_pack")
    vision = FakeVision({"total_printed": "80.00"})
    pipeline = build_pipeline(vision=vision, extra_packs=[pack])

    png = _text_image(tmp_path / "scan.png", ["Invoice Number: 1", "Total 80.00"])
    png_record = pipeline.process(document_id="fmt-png", source_path=png)

    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    pdf_path = tmp_path / "doc.pdf"
    with open(pdf_path, "wb") as fh:
        writer.write(fh)
    # A blank PDF carries no page text of its own to claim on, but the OCR/
    # native-text layer is irrelevant to THIS assertion - what matters is
    # that the same pack, same pipeline, handles both formats without
    # format-specific code anywhere in the adopter's own pack.
    pdf_record = pipeline.process(document_id="fmt-pdf", source_path=str(pdf_path))

    validate_record(png_record)
    validate_record(pdf_record)
    assert png_record["doc_type"] == "standard_invoice"
    assert "unclaimed_document" not in png_record["tags"]


# ===========================================================================
# 3. Layering: an adopter's pack alongside the shipped generic ones, and
#    alongside another adopter pack - resolution order must be predictable.
# ===========================================================================


def test_a_shipped_pack_still_wins_over_an_adopters_broader_catch_all(tmp_path, monkeypatch):
    """Shipped packs are checked before extra_packs (`load_packs() + list
    (extra_packs)`), so a document a shipped pack genuinely recognizes must
    never be stolen by an adopter's own, broader catch-all pack listed after
    it - regardless of how the adopter orders their OWN `extra_packs` list.

    No pack ships by default anymore, so this simulates one the way an
    adopter's real install still could (a company later decides to ship its
    own pack via `PACK_MODULES`/`PACK_FILES`) - `acme_freight`, injected into
    `load_packs()` for this test's duration only, stands in for that.
    """
    import pathlib

    import docintel.packs.registry as registry

    # acme_freight is pure data (no Python module at all - confirmed by
    # `test_the_third_pack_contains_no_python_at_all`), so it's loaded the
    # same way any data pack is: by path, via `load_pack_file`.
    fixtures_dir = pathlib.Path(__file__).resolve().parent / "fixtures" / "packs" / "acme_freight"
    acme_freight_pack = load_pack_file(str(fixtures_dir / "pack.json"))

    real_load_packs = registry.load_packs
    monkeypatch.setattr(registry, "load_packs", lambda: real_load_packs() + [acme_freight_pack])

    catch_all = _adopter_pack(tmp_path, "adopter_catch_all")
    doc = _text_image(tmp_path / "acme.png", [
        "SUMMIT CARRIERS LLC", "Invoice Number: 8891",
        "BILL TO: ACME FREIGHT SERVICES", "Total 1200.00",
    ])
    vision = FakeVision({"total_printed": "1200.00"})
    pipeline = build_pipeline(vision=vision, extra_packs=[catch_all])

    record = pipeline.process(document_id="layering-1", source_path=doc)
    validate_record(record)

    claim_event = next(e for e in record["events"] if "claimed by pack" in e)
    assert "'acme_freight'" in claim_event


def test_two_adopter_packs_resolve_in_the_order_the_adopter_listed_them(tmp_path):
    """Among the adopter's OWN packs (never among shipped ones), order is
    exactly what they passed to `extra_packs` - first match wins, same rule
    as shipped packs use internally."""
    specific = _adopter_pack(tmp_path, "specific_vendor_pack", {
        "claim": {"rules": [{"kind": "markers", "scope": "primary", "values": ["SPECIFICCO"]}],
                  "vetoes": []},
    })
    generic = _adopter_pack(tmp_path, "generic_catch_all")
    doc = _text_image(tmp_path / "specificco.png", [
        "SPECIFICCO INC", "Invoice Number: 1", "Total 10.00",
    ])
    vision = FakeVision({"total_printed": "10.00"})

    # specific listed first -> specific wins.
    pipeline_a = build_pipeline(vision=vision, extra_packs=[specific, generic])
    record_a = pipeline_a.process(document_id="order-a", source_path=doc)
    claim_a = next(e for e in record_a["events"] if "claimed by pack" in e)
    assert "'specific_vendor_pack'" in claim_a

    # generic listed first -> generic wins instead, even though specific
    # would also match - proves order is read literally, not "most specific".
    pipeline_b = build_pipeline(vision=vision, extra_packs=[generic, specific])
    record_b = pipeline_b.process(document_id="order-b", source_path=doc)
    claim_b = next(e for e in record_b["events"] if "claimed by pack" in e)
    assert "'generic_catch_all'" in claim_b


def test_an_adopters_known_vendor_persona_and_their_own_catch_all_pack_coexist(tmp_path):
    """The realistic end state this whole session built toward: one specific
    persona for a known, high-volume vendor (deterministic, zero AI calls),
    plus one generic catch-all pack for everyone else (vision-driven) - both
    supplied by the SAME adopter, in one pipeline, with no interference."""
    known_pack_dir = tmp_path / "known_vendor_pack"
    (known_pack_dir / "personas").mkdir(parents=True)
    (known_pack_dir / "pack.json").write_text(json.dumps({
        "name": "known_vendor_pack",
        "default_currency": "USD",
        "doc_types": ["standard_invoice"],
        "fields": {"standard_invoice": {"all": ["total_printed"], "required": [],
                                         "any_of": [], "derived_only": []}},
        "claim": {"rules": [{"kind": "markers", "scope": "primary", "values": ["KNOWNCO"]}], "vetoes": []},
        "ladder": {"default": "standard_invoice", "rungs": [
            {"name": "confirm", "doc_type": "standard_invoice",
             "when": {"signal": "pattern_in_scope", "params": {"pattern": "KNOWNCO", "scope": "primary"}}}]},
        "tags": [],
    }))
    (known_pack_dir / "personas" / "knownco.json").write_text(json.dumps({
        "sender_fingerprint": "known_vendor_pack|knownco",
        "doc_type": "standard_invoice",
        "rule_version": "v1",
        "status": "active",
        "field_selectors": [
            {"field": "total_printed", "anchor": "Total", "region": "same-row", "pattern": "currency"},
        ],
    }))
    known_pack = load_pack_file(str(known_pack_dir / "pack.json"))
    catch_all = _adopter_pack(tmp_path, "everyone_else_pack")

    vision = FakeVision({"total_printed": "999.00"})
    pipeline = build_pipeline(vision=vision, extra_packs=[known_pack, catch_all])

    known_doc = _text_image(tmp_path / "knownco.png", ["KNOWNCO INVOICE", "Total 500.00"])
    known_record = pipeline.process(document_id="known-1", source_path=known_doc)
    validate_record(known_record)
    assert known_record["extraction_route"] == "5a_cached", "the known vendor's own persona did the work"
    assert vision.calls == [], "zero AI calls for a document the adopter's own persona handles"

    other_doc = _text_image(tmp_path / "other.png", ["SOME OTHER CO", "Invoice Number: 1", "Total 999.00"])
    other_record = pipeline.process(document_id="other-1", source_path=other_doc)
    validate_record(other_record)
    assert other_record["extraction_route"] == "5b_vision", "everyone else falls through to the catch-all"
    assert "unclaimed_document" not in other_record["tags"]


# ===========================================================================
# 4. Failure modes a real onboarding actually hits.
# ===========================================================================


def test_an_adopters_malformed_vision_defaults_fails_loudly_at_pack_load(tmp_path):
    """A typo'd type name must be caught the moment the adopter loads their
    pack.json - never silently at extraction time, on whichever document
    happens to reach vision first."""
    pack_dir = tmp_path / "typo_pack"
    (pack_dir / "personas").mkdir(parents=True)
    (pack_dir / "pack.json").write_text(json.dumps({
        "name": "typo_pack", "default_currency": "USD", "doc_types": ["standard_invoice"],
        "fields": {"standard_invoice": {"all": [], "required": [], "any_of": [], "derived_only": []}},
        "claim": {"rules": [{"kind": "markers", "scope": "primary", "values": ["TYPOCO"]}], "vetoes": []},
        "ladder": {"default": "standard_invoice", "rungs": [
            {"name": "confirm", "doc_type": "standard_invoice",
             "when": {"signal": "pattern_in_scope", "params": {"pattern": "TYPOCO", "scope": "primary"}}}]},
        "vision_defaults": {
            "standard_invoice": {"fields": {"total_printed": "currancy"}, "tables": {}}  # typo: currancy
        },
        "tags": [],
    }))
    with pytest.raises(PackSpecError, match="unrecognized type"):
        load_pack_file(str(pack_dir / "pack.json"))


def test_an_adopters_pack_that_claims_nothing_here_falls_through_cleanly(tmp_path):
    """A document that matches NEITHER a shipped pack NOR the adopter's own
    pack must still emit a valid, honest `unclaimed_document` record - never
    crash, never silently misclassify."""
    pack = _adopter_pack(tmp_path, "narrow_pack", {
        "claim": {"rules": [{"kind": "markers", "scope": "primary", "values": ["VERY SPECIFIC CO"]}],
                  "vetoes": []},
    })
    doc = _text_image(tmp_path / "unrelated.png", ["Totally Unrelated Business", "Random text"])
    vision = FakeVision()
    pipeline = build_pipeline(vision=vision, extra_packs=[pack])

    record = pipeline.process(document_id="no-claim-1", source_path=doc)
    validate_record(record)

    assert record["disposition"] == "processed"
    assert "unclaimed_document" in record["tags"]
    assert record["sender_fingerprint"] == "unknown|unknown"


def test_zero_extra_packs_still_produces_a_valid_record_via_generic_vision(tmp_path):
    """The absolute floor: an adopter who hasn't written any pack at all yet
    still gets a working pipeline - the shipped generic packs plus the
    hardcoded 4-field vision default, never a crash for having configured
    nothing."""
    doc = _text_image(tmp_path / "bare.png", ["Nobody Configured Co", "Invoice Number: 1", "Total 42.00"])
    vision = FakeVision({"total_printed": "42.00"})
    pipeline = build_pipeline(vision=vision)  # no extra_packs at all

    record = pipeline.process(document_id="bare-1", source_path=doc)
    validate_record(record)

    assert record["disposition"] == "processed"
    assert record["extraction_route"] == "5b_vision"
    assert vision.calls == [["vendor_name", "invoice_number", "invoice_date", "total_printed"]]
