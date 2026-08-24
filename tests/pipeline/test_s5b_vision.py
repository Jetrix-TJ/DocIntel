"""Stage 5b: when vision runs, what it is handed, and what its output may do."""

from __future__ import annotations

import json

import pytest

from docintel.adapters.vision.cassette import CassetteVision
from docintel.adapters.vision.fake import FakeVision
from docintel.core.models import JobContext, PageText, Word
from docintel.grammar.schema import FieldSelector
from docintel.pipeline.stages.s5b_vision import VisionOneShot


class _Persona:
    """Stands in for a real `Persona` - only `field_selectors` is read by
    `core.coverage.assess`, so this is the minimal shape that exercises it."""

    def __init__(self, field_selectors):
        self.field_selectors = field_selectors


def _selector(field: str, required: bool = True) -> FieldSelector:
    return FieldSelector(field=field, pattern="text", region="near-anchor", required=required)


class _RowGroup:
    """Minimal stand-in for a `RowGroupSelector` - only the attributes
    `hints.py`'s table functions read."""

    def __init__(self, row_group, columns):
        self.row_group = row_group
        self.columns = columns
        self.column_headers = {}


class _Pack:
    """Minimal stand-in for a matched `Pack` - only `vision_defaults` is
    read here."""

    def __init__(self, vision_defaults):
        self._vision_defaults = vision_defaults

    def vision_defaults(self, doc_type):
        return self._vision_defaults.get(doc_type, ({}, {}))


class _PackWithNoVisionDefaults:
    """A pack that simply doesn't implement `vision_defaults` at all - the
    two shipped module packs (northstar, digitaldirection) today."""

    pass


def _ctx(source_path: str = "/corpus/x.pdf", **kw) -> JobContext:
    words = (Word(text="TOTAL", x0=10.0, y0=100.0, x1=50.0, y1=110.0),)
    return JobContext(
        document_id="d1",
        source_path=source_path,
        pages=(PageText(page_number=1, words=words, width=612.0, height=792.0,
                        source="native"),),
        **kw,
    )


# -- when it runs ----------------------------------------------------------


def test_a_healthy_cached_extraction_is_left_alone():
    ctx = _ctx(extraction_route="5a_cached")
    ctx.extracted.set("total_printed", "1.00", 0.95)
    fake = FakeVision({"total_printed": "9.99"})

    VisionOneShot(vision=fake).run(ctx)

    assert fake.calls == []
    assert ctx.extracted.get("total_printed") == "1.00"


def test_no_persona_at_all_routes_to_vision():
    ctx = _ctx()
    fake = FakeVision({"total_printed": "9.99"})

    VisionOneShot(vision=fake).run(ctx)

    assert ctx.extraction_route == "5b_vision"
    assert ctx.extracted.get("total_printed") == "9.99"


@pytest.mark.parametrize("source_format", ["txt", "csv", "html"])
def test_text_native_formats_never_reach_vision_even_with_no_persona(source_format):
    """Real bug this test pins: before this fix, a persona-less TXT/CSV/HTML
    document reached `vision.extract(...)` exactly like an unknown-vendor PDF
    would - harmless with `FakeVision`, but the REAL Gemini adapter's
    `_read_document` raises `PermanentError` for any suffix that is neither
    `.pdf` nor a Gemini-native image MIME type, so this would have dead-
    lettered every unrecognized TXT/CSV/HTML document in production. None of
    these formats carries visual content vision could add anything by
    looking at, and Gemini does not accept them as document input at all -
    so this stage must be a no-op for them, not merely lucky with a fake."""
    ctx = _ctx(source_format=source_format)
    fake = FakeVision({"total_printed": "9.99"})

    result = VisionOneShot(vision=fake).run(ctx)

    assert fake.calls == []
    assert result.extraction_route is None
    assert result.extracted.get("total_printed") is None


def test_two_weak_fields_count_as_collapse():
    ctx = _ctx(extraction_route="5a_cached")
    ctx.extracted.set("total_printed", "1.00", 0.20)
    ctx.extracted.set("vendor_name", "A", 0.20)
    fake = FakeVision({"total_printed": "9.99"})

    VisionOneShot(vision=fake).run(ctx)

    assert ctx.extraction_route == "5b_vision"


def test_mostly_empty_declared_fields_escalate_even_though_the_few_matches_are_confident():
    """The bug this guards: a persona with 12 of 14 declared fields returning
    nothing has failed just as completely as one with weak values - but
    `match_quality` only ever records a field that DID produce a value, so
    confidence alone can never see the other 12. Coverage is what sees them."""
    persona = _Persona([_selector(f"field_{i}") for i in range(14)])
    ctx = _ctx(extraction_route="5a_cached", persona=persona)
    ctx.extracted.set("field_0", "A", 0.95)
    ctx.extracted.set("field_1", "B", 0.95)
    fake = FakeVision({"total_printed": "9.99"})

    VisionOneShot(vision=fake).run(ctx)

    assert ctx.extraction_route == "5b_vision"


def test_a_small_fully_populated_persona_does_not_escalate():
    """The negative case: few declared fields, all confidently populated, must
    not spuriously trigger just because `miss_share` swings hard per field on
    a small persona."""
    persona = _Persona([_selector("total_printed"), _selector("vendor_name")])
    ctx = _ctx(extraction_route="5a_cached", persona=persona)
    ctx.extracted.set("total_printed", "1.00", 0.95)
    ctx.extracted.set("vendor_name", "A", 0.95)
    fake = FakeVision({"total_printed": "9.99"})

    VisionOneShot(vision=fake).run(ctx)

    assert ctx.extraction_route == "5a_cached"
    assert fake.calls == []


# -- what the adapter is handed -------------------------------------------


def test_the_adapter_receives_the_source_path():
    """Without it the adapter can only see the text layer, which on the documents
    that need vision is the OCR output we are trying to check."""
    ctx = _ctx(source_path="/corpus/federal.pdf")
    fake = FakeVision()

    VisionOneShot(vision=fake).run(ctx)

    assert fake.sources == ["/corpus/federal.pdf"]


def test_no_persona_at_all_still_asks_for_only_the_generic_default():
    """A genuinely first-time vendor has no field list to draw on - it must
    still get exactly the old 4-field generic ask, with no hints."""
    ctx = _ctx()
    fake = FakeVision({"total_printed": "9.99"})

    VisionOneShot(vision=fake).run(ctx)

    assert fake.calls == [["vendor_name", "invoice_number", "invoice_date", "total_printed"]]
    assert fake.hints == [{}]


def test_a_known_but_collapsed_persona_asks_for_its_own_field_list_with_hints():
    """The gap this closes: before this, a KNOWN vendor whose regex read
    collapsed still only got asked the generic 4-field default - discarding
    the one thing that could recover the rest of what the persona knows."""
    persona = _Persona([_selector("total_printed"), _selector("vendor_account_number")])
    ctx = _ctx(extraction_route="5a_cached", persona=persona)
    ctx.extracted.set("total_printed", "1.00", 0.10)  # weak -> collapse
    ctx.extracted.set("vendor_account_number", "2.00", 0.10)
    fake = FakeVision({"total_printed": "9.99"})

    VisionOneShot(vision=fake).run(ctx)

    assert fake.calls == [["total_printed", "vendor_account_number"]]
    assert fake.hints == [{
        "total_printed": "just below or beside that label",
        "vendor_account_number": "just below or beside that label",
    }]


def test_an_explicit_field_names_override_always_wins_and_carries_no_hints():
    """The isolated vision eval's own contract: a caller that constructs this
    stage with its own list gets exactly that list, never the persona's,
    regardless of whether a persona is known."""
    persona = _Persona([_selector(f"field_{i}") for i in range(14)])
    ctx = _ctx(extraction_route="5a_cached", persona=persona)
    ctx.extracted.set("field_0", "A", 0.95)
    ctx.extracted.set("field_1", "B", 0.95)  # 12 of 14 missing -> collapse
    fake = FakeVision({"total_printed": "9.99"})

    VisionOneShot(vision=fake, field_names=["total_printed"]).run(ctx)

    assert fake.calls == [["total_printed"]]
    assert fake.hints == [{}]


def test_a_persona_with_no_scalar_fields_falls_back_to_the_generic_default():
    """An edge case rather than a real vendor - a persona that declares
    nothing vision could ask for has no more to offer than no persona at all."""
    ctx = _ctx()
    ctx.persona = _Persona([])
    fake = FakeVision()

    VisionOneShot(vision=fake).run(ctx)

    assert fake.calls == [["vendor_name", "invoice_number", "invoice_date", "total_printed"]]
    assert fake.hints == [{}]


# -- tables: four resolution tiers, mirroring the scalar-field tiers above --


def test_no_table_is_asked_for_when_nothing_declares_one():
    """The baseline: neither a constructor override, a persona row_group, nor
    a pack vision_defaults table - so no table is requested at all, not every
    document has one."""
    ctx = _ctx()
    fake = FakeVision({"total_printed": "9.99"})

    VisionOneShot(vision=fake).run(ctx)

    assert fake.table_calls == [{}]


def test_tier1_an_explicit_table_requests_override_always_wins():
    persona = _Persona([_RowGroup("line_items", {"amount": "currency"})])
    ctx = _ctx(persona=persona, doc_type="standard_invoice")
    fake = FakeVision({"total_printed": "9.99"})

    VisionOneShot(vision=fake, table_requests={"charges": ["amount"]}).run(ctx)

    assert fake.table_calls == [{"charges": ["amount"]}]


def test_tier2_a_known_persona_s_row_group_is_derived_automatically():
    """No new authoring: the SAME `row_group` selector a real vendor persona
    already declares for the grammar/5a path also drives the vision table
    request, with hints built from its own columns/column_headers."""
    persona = _Persona([_RowGroup("line_items", {"date": "date", "amount": "currency"})])
    ctx = _ctx(persona=persona, doc_type="standard_invoice")
    fake = FakeVision({"total_printed": "9.99"})

    VisionOneShot(vision=fake).run(ctx)

    assert fake.table_calls == [{"line_items": ["date", "amount"]}]


def test_tier3_a_pack_s_vision_defaults_table_is_used_when_there_is_no_persona():
    """The 1000-unknown-vendor case: no persona exists and none ever will,
    but the matched pack declares a generic table shape for this doc_type -
    zero Python bypass needed, straight through the pack's own declaration."""
    pack = _Pack({"standard_invoice": ({}, {"line_items": {"date": "date", "amount": "currency"}})})
    ctx = _ctx(pack=pack, doc_type="standard_invoice")
    fake = FakeVision({"total_printed": "9.99"})

    VisionOneShot(vision=fake).run(ctx)

    assert fake.table_calls == [{"line_items": ["date", "amount"]}]


def test_tier4_a_pack_with_no_vision_defaults_method_falls_through_cleanly():
    """`getattr(ctx.pack, "vision_defaults", None)` must not raise on a pack
    that simply doesn't implement it - the two shipped module packs today."""
    ctx = _ctx(pack=_PackWithNoVisionDefaults(), doc_type="standard_invoice")
    fake = FakeVision({"total_printed": "9.99"})

    VisionOneShot(vision=fake).run(ctx)

    assert fake.table_calls == [{}]


def test_a_known_persona_s_row_group_wins_over_the_pack_s_vision_defaults():
    """Tier 2 (persona) is checked before tier 3 (pack) - a known vendor's own
    declared table is a strictly better request than the pack's generic one."""
    persona = _Persona([_RowGroup("line_items", {"amount": "currency"})])
    pack = _Pack({"standard_invoice": ({}, {"charges": {"amount": "currency"}})})
    ctx = _ctx(persona=persona, pack=pack, doc_type="standard_invoice")
    fake = FakeVision({"total_printed": "9.99"})

    VisionOneShot(vision=fake).run(ctx)

    assert fake.table_calls == [{"line_items": ["amount"]}]


def test_vision_derived_rows_land_in_ctx_row_groups():
    """This is what makes `record["line_items"]` populate through the vision
    path: `core.contract.build_record`'s existing promotion of
    `ctx.row_groups` picks this up unconditionally, regardless of which
    stage wrote it."""
    ctx = _ctx(doc_type="standard_invoice")
    rows = [{"date": "07/01/25", "amount": "402.00"}]
    fake = FakeVision(
        {"total_printed": "9.99"},
        canned_tables={"line_items": rows},
    )

    VisionOneShot(vision=fake, table_requests={"line_items": ["date", "amount"]}).run(ctx)

    assert ctx.row_groups["line_items"] == rows


# -- what the output may do ----------------------------------------------


def test_an_observable_irregularity_becomes_a_priced_modifier():
    """Filing it as a tag would put the observation on the record and leave every
    field's confidence untouched - honoured in appearance only."""
    ctx = _ctx()
    fake = FakeVision({"total_printed": "1.00"}, irregularities=["handwriting_detected"])

    VisionOneShot(vision=fake).run(ctx)

    assert "handwriting_detected" in ctx.modifiers
    assert "handwriting_detected" not in ctx.tags


def test_a_flag_with_no_defined_price_stays_a_tag():
    ctx = _ctx()
    fake = FakeVision({"total_printed": "1.00"}, irregularities=["something_odd"])

    VisionOneShot(vision=fake).run(ctx)

    assert ctx.tags == ["something_odd"]
    assert ctx.modifiers == []


# -- the cassette in the pipeline ----------------------------------------


def test_a_recorded_cassette_drives_the_stage_end_to_end(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 body")
    cassette = tmp_path / "c.json"
    ctx = _ctx(source_path=str(pdf))
    replay = CassetteVision(inner=None, path=str(cassette), mode="replay")
    key = replay.key(ctx.pages, ["total_printed"], str(pdf))
    cassette.write_text(json.dumps({key: {
        "provenance": "authored",
        "fields": {"total_printed": "1,177.70"},
        "confidence": {"total_printed": 0.82},
        "irregularities": ["handwriting_detected"],
    }}), encoding="utf-8")

    VisionOneShot(vision=replay, field_names=["total_printed"]).run(ctx)

    assert ctx.extracted.get("total_printed") == "1,177.70"
    assert ctx.extracted.match_quality["total_printed"] == pytest.approx(0.82)
    assert "handwriting_detected" in ctx.modifiers


def test_a_cassette_miss_dead_letters_one_document_and_still_emits(tmp_path):
    """The emit-always invariant is what makes a loud miss affordable. A replay
    miss must cost one document, not the run."""
    from docintel.pipeline.hooks import HookRegistry
    from docintel.pipeline.runner import Runner

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 body")
    empty = tmp_path / "c.json"
    empty.write_text("{}", encoding="utf-8")
    runner = Runner(
        stages=[VisionOneShot(
            vision=CassetteVision(inner=None, path=str(empty), mode="replay")
        )],
        hooks=HookRegistry(),
    )

    record = runner.process(document_id="d1", source_path=str(pdf))

    assert record["disposition"] == "dead_letter"
    assert "no cassette entry" in (record.get("reason") or "")
    assert "--vision record" in (record.get("reason") or "")  # actionable, not just loud
    assert runner.stats == {"intaken": 1, "emitted": 1}
