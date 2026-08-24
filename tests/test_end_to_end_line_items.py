"""Line-item/table extraction, end to end, through the real, public
`build_pipeline()` entry point - the same one `docintel process` uses.

Companion to `test_end_to_end_pipeline.py` (the four pipeline SHAPES) and
`test_end_to_end_formats.py` (format coverage). This file is organized around
the "Gemini Vision line-item/array support" plan's own four-tier resolution
order for tables (constructor override -> known persona's row_group ->
matched pack's vision_defaults -> nothing), plus the real-world failure modes
a table response can hit (a model-invented column, a malformed row, a
transient API failure, a cassette round trip) and the one composition risk
unique to a stateless, shared `VisionOneShot` instance: two different
documents in the same batch resolving to two different table requests must
never leak into each other.

Only `FakeVision`/`CassetteVision` stand in for the real model - every pack,
persona, claim rule, and pipeline stage here is real.
"""

from __future__ import annotations

import json

import pytest
from PIL import Image, ImageDraw, ImageFont

from docintel import build_pipeline
from docintel.adapters.vision.fake import FakeVision
from docintel.adapters.vision.cassette import CassetteVision
from docintel.core.contract import validate_record
from docintel.core.errors import TransientError
from docintel.packs.datapack import load_pack_file

_FONT = ImageFont.load_default(size=26)


def _text_image(path, lines: list[str], size=(900, 260)) -> str:
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((20, 20 + i * 45), line, font=_FONT, fill="black")
    img.save(path)
    return str(path)


def _write_pack(tmp_path, name: str, spec: dict, persona: dict | None = None):
    """A minimal, real, on-disk `DataPack` - pack.json plus an optional
    single persona - loaded through the same `load_pack_file` a real
    onboarding session uses, never a duck-typed stand-in."""
    pack_dir = tmp_path / name
    (pack_dir / "personas").mkdir(parents=True, exist_ok=True)
    (pack_dir / "pack.json").write_text(json.dumps(spec))
    if persona is not None:
        (pack_dir / "personas" / f"{name}.json").write_text(json.dumps(persona))
    return load_pack_file(str(pack_dir / "pack.json"))


def _accept_any_invoice_pack(tmp_path, name: str, vision_defaults: dict) -> object:
    """The `northstar_new`/`general_invoices` shape from this session's own
    sandbox work: content-based claim, no persona, a `vision_defaults` block
    instead."""
    return _write_pack(tmp_path, name, {
        "name": name,
        "default_currency": "USD",
        "doc_types": ["standard_invoice"],
        "fields": {"standard_invoice": {"all": [], "required": [], "any_of": [], "derived_only": []}},
        "claim": {
            "rules": [{
                "kind": "corroborated_markers", "scope": "primary",
                "pairs": [{"marker": "invoice", "requires": "total"}],
            }],
            "vetoes": [],
        },
        "ladder": {
            "default": "standard_invoice",
            "rungs": [{"name": "confirm", "doc_type": "standard_invoice",
                       "when": {"signal": "pattern_in_scope",
                                "params": {"pattern": "Invoice", "scope": "primary"}}}],
        },
        "vision_defaults": vision_defaults,
        "tags": [],
    })


# ===========================================================================
# Tier 3: a pack's own `vision_defaults` - the 1000-unknown-vendor case,
# zero personas, zero Python bypass.
# ===========================================================================


def test_a_pack_s_vision_defaults_requests_fields_and_multiple_tables_together(tmp_path):
    """One real vision call must carry BOTH scalar fields and more than one
    table, all declared on the same pack, none of them requiring a persona."""
    pack = _accept_any_invoice_pack(tmp_path, "genericpack", {
        "standard_invoice": {
            "fields": {"account_number": "text", "total_printed": "currency"},
            "tables": {
                "line_items": {"date": "date", "description": "text", "amount": "currency"},
                "charges": {"label": "text", "amount": "currency"},
            },
        }
    })
    png = _text_image(tmp_path / "doc.png", ["Invoice Number 1", "Total 100.00"])
    vision = FakeVision(
        {"account_number": "ACCT-1", "total_printed": "100.00"},
        canned_tables={
            "line_items": [{"date": "1/1/25", "description": "A", "amount": "50.00"}],
            "charges": [{"label": "TAX", "amount": "5.00"}],
        },
    )
    pipeline = build_pipeline(vision=vision, extra_packs=[pack])

    record = pipeline.process(document_id="tier3-multi", source_path=png)
    validate_record(record)

    assert record["extraction_route"] == "5b_vision"
    assert record["fields"]["account_number"] == "ACCT-1"
    assert record["line_items"] == [{"date": "1/1/25", "description": "A", "amount": "50.00"}]
    assert record["charges"] == [{"label": "TAX", "amount": "5.00"}]


def test_vision_defaults_are_scoped_per_doc_type_not_pack_wide(tmp_path):
    """A pack that declares `vision_defaults` for one doc_type must NOT leak
    a table request into a document that classifies as a different doc_type
    under the same pack."""
    pack = _write_pack(tmp_path, "twotypes", {
        "name": "twotypes",
        "default_currency": "USD",
        "doc_types": ["standard_invoice", "credit_memo"],
        "fields": {
            "standard_invoice": {"all": [], "required": [], "any_of": [], "derived_only": []},
            "credit_memo": {"all": [], "required": [], "any_of": [], "derived_only": []},
        },
        "claim": {"rules": [{"kind": "markers", "scope": "primary", "values": ["TWOTYPES CO"]}], "vetoes": []},
        "ladder": {
            "default": "standard_invoice",
            "rungs": [
                {"name": "credit", "doc_type": "credit_memo",
                 "when": {"signal": "pattern_in_scope",
                          "params": {"pattern": "CREDIT MEMO", "scope": "primary"}}},
            ],
        },
        "vision_defaults": {
            "standard_invoice": {"fields": {}, "tables": {"line_items": {"amount": "currency"}}},
        },
        "tags": [],
    })
    png = _text_image(tmp_path / "credit.png", ["TWOTYPES CO", "CREDIT MEMO", "Total -50.00"])
    vision = FakeVision({"total_printed": "-50.00"})
    pipeline = build_pipeline(vision=vision, extra_packs=[pack])

    record = pipeline.process(document_id="tier3-scoped", source_path=png)
    validate_record(record)

    assert record["doc_type"] == "credit_memo"
    assert vision.table_calls == [{}]
    assert record["line_items"] == []


# ===========================================================================
# Tier 2: a known vendor's own `row_group` persona - no new authoring, the
# SAME selector the grammar engine already uses also drives the vision
# fallback when the deterministic read collapses.
# ===========================================================================


def _knownco_pack(tmp_path):
    return _write_pack(
        tmp_path, "knownco_pack",
        spec={
            "name": "knownco_pack",
            "default_currency": "USD",
            "doc_types": ["standard_invoice"],
            "fields": {"standard_invoice": {"all": ["vendor_name", "total_printed"],
                                             "required": [], "any_of": [], "derived_only": []}},
            "claim": {"rules": [{"kind": "markers", "scope": "primary", "values": ["KNOWNCO"]}], "vetoes": []},
            "ladder": {
                "default": "standard_invoice",
                "rungs": [{"name": "confirm", "doc_type": "standard_invoice",
                           "when": {"signal": "pattern_in_scope",
                                    "params": {"pattern": "KNOWNCO", "scope": "primary"}}}],
            },
            "tags": [],
        },
        persona={
            "sender_fingerprint": "knownco_pack|knownco",
            "doc_type": "standard_invoice",
            "rule_version": "v1",
            "status": "active",
            "field_selectors": [
                # Anchors that cannot match anything on the real page below -
                # guarantees a full collapse (`ctx.extracted.match_quality`
                # stays empty), not a partial one, so the vision retry is
                # certain to fire.
                {"field": "vendor_name", "anchor": "NEVER_PRESENT_LABEL_1",
                 "region": "near-anchor", "pattern": "text"},
                {"row_group": "line_items", "table_anchor": "NEVER_PRESENT_LABEL_2",
                 "columns": {"description": "text", "amount": "currency"},
                 "column_headers": {"description": "DESCRIPTION", "amount": "AMOUNT"}},
            ],
        },
    )


def test_a_known_persona_s_collapsed_read_derives_both_fields_and_table_for_the_retry(tmp_path):
    pack = _knownco_pack(tmp_path)
    png = _text_image(tmp_path / "knownco.png", ["KNOWNCO INVOICE", "Total 250.00"])
    vision = FakeVision(
        {"vendor_name": "KnownCo Inc.", "total_printed": "250.00"},
        canned_tables={"line_items": [{"description": "WIDGET", "amount": "250.00"}]},
    )
    pipeline = build_pipeline(vision=vision, extra_packs=[pack])

    record = pipeline.process(document_id="tier2-collapsed", source_path=png)
    validate_record(record)

    assert record["sender_fingerprint"] == "knownco_pack|knownco"
    assert record["extraction_route"] == "5b_vision"
    # Derived from the SAME persona's own scalar selector - not the generic
    # 4-field default, and not the pack's vision_defaults (this pack has none).
    assert vision.calls == [["vendor_name"]]
    assert vision.table_calls == [{"line_items": ["description", "amount"]}]
    assert record["line_items"] == [{"description": "WIDGET", "amount": "250.00"}]


DTSS_PDF = "docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf"


def test_a_known_vendor_whose_deterministic_read_succeeds_never_calls_vision_at_all():
    """The composition guarantee this whole plan depends on: DTSS is a real,
    currently-passing gold document whose shipped persona already extracts
    `line_items` via the grammar engine alone. None of this session's changes
    may cost it a single vision call.

    `northstar` is a test fixture (`tests/fixtures/packs/`), not a shipped
    pack - passed explicitly here since this test needs its real persona.
    """
    from northstar import PACK as NORTHSTAR_PACK

    vision = FakeVision()
    pipeline = build_pipeline(vision=vision, extra_packs=[NORTHSTAR_PACK])

    record = pipeline.process(document_id="tier1-real-dtss", source_path=DTSS_PDF)
    validate_record(record)

    assert record["extraction_route"] == "5a_cached"
    assert vision.calls == [] and vision.table_calls == []
    assert len(record["line_items"]) > 0


# ===========================================================================
# Tier 4: nothing declares a table at all - the honest default.
# ===========================================================================


def test_a_fully_unclaimed_document_gets_no_table_request_and_an_empty_line_items(tmp_path):
    png = _text_image(tmp_path / "nobody-claims-this.png", ["Some Random Company", "Total 12.00"])
    vision = FakeVision({"total_printed": "12.00"})
    pipeline = build_pipeline(vision=vision)  # no extra_packs at all

    record = pipeline.process(document_id="tier4-unclaimed", source_path=png)
    validate_record(record)

    assert "unclaimed_document" in record["tags"]
    assert vision.table_calls == [{}]
    assert record["line_items"] == []


# ===========================================================================
# Real-world response shapes: a model that doesn't follow instructions
# exactly, and infrastructure failures around the call.
# ===========================================================================


def test_an_unrequested_column_and_a_malformed_row_are_sanitized_not_fatal(tmp_path):
    """Proves this end to end, not just at the `policy.sanitize` unit level:
    a real pipeline run must still `process` cleanly when the model returns
    more (or worse) than it was asked for."""
    pack = _accept_any_invoice_pack(tmp_path, "messyvendor", {
        "standard_invoice": {"fields": {}, "tables": {"line_items": {"amount": "currency"}}}
    })
    png = _text_image(tmp_path / "messy.png", ["Invoice Number 9", "Total 10.00"])

    class _MessyVision:
        """A `VisionExtractor` double that ignores the allowlist entirely -
        exactly what `policy.sanitize` exists to defend against."""

        def extract(self, pages, field_names, *, source_path=None, field_hints=None,
                    table_requests=None, table_hints=None):
            from docintel.adapters.vision.policy import sanitize
            from docintel.adapters.vision.port import VisionResult

            raw = VisionResult(
                fields={"total_printed": "10.00"},
                confidence={"total_printed": 0.9},
                row_groups={"line_items": [
                    "not even a row",
                    {"amount": "10.00", "notes": "the model invented this column"},
                ]},
            )
            return sanitize(raw, field_names, table_requests)

    pipeline = build_pipeline(vision=_MessyVision(), extra_packs=[pack])
    record = pipeline.process(document_id="messy-row", source_path=png)
    validate_record(record)

    assert record["disposition"] == "processed"
    assert record["line_items"] == [{"amount": "10.00"}]


def test_a_transient_vision_failure_is_retried_and_line_items_land_intact(tmp_path):
    pack = _accept_any_invoice_pack(tmp_path, "flakyvendor", {
        "standard_invoice": {"fields": {}, "tables": {"line_items": {"amount": "currency"}}}
    })
    png = _text_image(tmp_path / "flaky.png", ["Invoice Number 5", "Total 20.00"])

    class _FlakyOnceVision:
        def __init__(self, inner) -> None:
            self.inner = inner
            self.attempts = 0

        def extract(self, *args, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise TransientError("simulated one-time transient failure")
            return self.inner.extract(*args, **kwargs)

    inner = FakeVision({"total_printed": "20.00"}, canned_tables={"line_items": [{"amount": "20.00"}]})
    flaky = _FlakyOnceVision(inner)
    pipeline = build_pipeline(vision=flaky, extra_packs=[pack])  # default max_retries=2

    record = pipeline.process(document_id="flaky-vision", source_path=png)
    validate_record(record)

    assert record["disposition"] == "processed"
    assert flaky.attempts == 2
    assert record["line_items"] == [{"amount": "20.00"}]  # exactly one copy, not duplicated


def test_a_recorded_cassette_replays_its_table_rows_identically(tmp_path):
    """The offline, deterministic path `docintel replay-gold`/eval tooling
    depends on: record once against a real (here, fake) model, then replay
    from disk with no model involved at all."""
    pack = _accept_any_invoice_pack(tmp_path, "cassettevendor", {
        "standard_invoice": {"fields": {}, "tables": {"line_items": {"amount": "currency"}}}
    })
    png = _text_image(tmp_path / "cassette.png", ["Invoice Number 7", "Total 30.00"])
    cassette_path = tmp_path / "c.json"

    inner = FakeVision({"total_printed": "30.00"}, canned_tables={"line_items": [{"amount": "30.00"}]})
    recorder = CassetteVision(inner=inner, path=str(cassette_path), mode="record")
    recorded = build_pipeline(vision=recorder, extra_packs=[pack]).process(
        document_id="cassette-record", source_path=png
    )
    validate_record(recorded)
    assert recorded["line_items"] == [{"amount": "30.00"}]

    replay = CassetteVision(inner=None, path=str(cassette_path), mode="replay")
    replayed = build_pipeline(vision=replay, extra_packs=[pack]).process(
        document_id="cassette-replay", source_path=png
    )
    validate_record(replayed)
    assert replayed["line_items"] == recorded["line_items"]


# ===========================================================================
# Mixed batch: one Runner, three documents, three different table
# resolutions - the composition risk unique to a stateless, shared
# `VisionOneShot` instance reused across an entire run.
# ===========================================================================


def test_a_mixed_batch_never_leaks_one_document_s_table_request_into_another(tmp_path):
    known_pack = _knownco_pack(tmp_path)
    generic_pack = _accept_any_invoice_pack(tmp_path, "genericbatch", {
        "standard_invoice": {"fields": {}, "tables": {"charges": {"amount": "currency"}}}
    })

    known_png = _text_image(tmp_path / "known.png", ["KNOWNCO INVOICE", "Total 1.00"])
    generic_png = _text_image(tmp_path / "generic.png", ["Invoice Number 2", "Total 2.00"])
    bare_png = _text_image(tmp_path / "bare.png", ["Nothing Claims This", "Total 3.00"])

    vision = FakeVision(
        {"vendor_name": "KnownCo Inc.", "total_printed": "1.00"},
        canned_tables={
            "line_items": [{"description": "A", "amount": "1.00"}],
            "charges": [{"amount": "2.00"}],
        },
    )
    pipeline = build_pipeline(vision=vision, extra_packs=[known_pack, generic_pack])

    known_record = pipeline.process(document_id="batch-known", source_path=known_png)
    generic_record = pipeline.process(document_id="batch-generic", source_path=generic_png)
    bare_record = pipeline.process(document_id="batch-bare", source_path=bare_png)

    for record in (known_record, generic_record, bare_record):
        validate_record(record)

    assert known_record["line_items"] == [{"description": "A", "amount": "1.00"}]
    assert known_record["charges"] == []  # this vendor's persona never declared "charges"

    assert generic_record["charges"] == [{"amount": "2.00"}]
    assert generic_record["line_items"] == []  # this pack's vision_defaults never declared it

    assert bare_record["line_items"] == [] and bare_record["charges"] == []

    # And the exact per-document requests actually sent, in order - proof
    # there was no bleed-through between calls on the shared instance.
    assert vision.table_calls == [
        {"line_items": ["description", "amount"]},
        {"charges": ["amount"]},
        {},
    ]
