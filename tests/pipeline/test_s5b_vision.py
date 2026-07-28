"""Stage 5b: when vision runs, what it is handed, and what its output may do."""

from __future__ import annotations

import json

import pytest

from docintel.adapters.vision.cassette import CassetteVision
from docintel.adapters.vision.fake import FakeVision
from docintel.core.models import JobContext, PageText, Word
from docintel.pipeline.stages.s5b_vision import VisionOneShot


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


def test_two_weak_fields_count_as_collapse():
    ctx = _ctx(extraction_route="5a_cached")
    ctx.extracted.set("total_printed", "1.00", 0.20)
    ctx.extracted.set("vendor_name", "A", 0.20)
    fake = FakeVision({"total_printed": "9.99"})

    VisionOneShot(vision=fake).run(ctx)

    assert ctx.extraction_route == "5b_vision"


# -- what the adapter is handed -------------------------------------------


def test_the_adapter_receives_the_source_path():
    """Without it the adapter can only see the text layer, which on the documents
    that need vision is the OCR output we are trying to check."""
    ctx = _ctx(source_path="/corpus/federal.pdf")
    fake = FakeVision()

    VisionOneShot(vision=fake).run(ctx)

    assert fake.sources == ["/corpus/federal.pdf"]


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
