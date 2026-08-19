from docintel.adapters.vision.fake import FakeVision
from docintel.core.contract import validate_record
from docintel.core.models import new_context
from docintel.pipeline.hooks import HookRegistry
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_default_stages, build_pipeline

CORPUS = "docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf"


def _runner():
    return Runner(stages=build_default_stages(vision=FakeVision()), hooks=HookRegistry())


def test_every_stage_runs_and_is_logged():
    rec = _runner().process("d1", CORPUS)
    validate_record(rec)


def test_the_default_sequence_is_eleven_modules_in_pipeline_order():
    names = [s.name for s in build_default_stages(vision=FakeVision())]
    assert names == [
        "intake", "attachment_filter", "classify", "persona_lookup",
        "resolve_processing_profile", "apply_cached_rules", "vision_one_shot",
        "agent_escalation", "capture_fields", "confidence_gate", "emit_record",
    ]


def test_every_stage_records_that_it_ran():
    """'Pass any PDF and it traverses all 8 stages' must be OBSERVABLY true.

    Asserts on the event log itself, which is the only evidence a stage ran.
    5a is absent by design here: no persona exists, so the document is a hard
    miss and routes to 5b.
    """
    captured = {}

    class Spy:
        name = "spy"

        def run(self, ctx):
            captured["events"] = list(ctx.events)
            return ctx

    stages = build_default_stages(vision=FakeVision())
    stages.append(Spy())
    Runner(stages=stages, hooks=HookRegistry()).process("d1", CORPUS)

    log = " ".join(captured["events"])
    for marker in ("s1:", "s2:", "s3:", "s4:", "s5b:", "s6:", "s7:", "s8:"):
        assert marker in log, f"no evidence stage {marker} ran; log was {log!r}"


def test_hard_miss_routes_to_vision_not_cached_rules():
    """Skeleton has no personas, so every document is a hard miss -> 5b."""
    rec = _runner().process("d1", CORPUS)
    assert rec["extraction_route"] == "5b_vision"


class _StubPersona:
    rule_version = "v14"


class _StubStore:
    """Stands in for the Persona DB, which arrives in cluster C7."""

    def __init__(self, persona: object | None) -> None:
        self.persona = persona

    def lookup(self, fingerprint: str, doc_type: str | None) -> object | None:
        return self.persona


class _StubExecutor:
    """Stands in for the grammar executor, which arrives in cluster C2."""

    def __init__(self, quality: float) -> None:
        self.quality = quality

    def apply(self, ctx):
        ctx.extracted.set("invoice_number", "AC-002561", self.quality)
        ctx.extracted.set("total_printed", "1284.50", self.quality)
        return ctx


def _routing_runner(persona, quality, vision):
    """A stage list wired for one specific stage-5 routing path."""
    from docintel.pipeline.stages.s1_intake import Intake
    from docintel.pipeline.stages.s2_filter import AttachmentFilter
    from docintel.pipeline.stages.s3_classify import Classify
    from docintel.pipeline.stages.s4_persona import PersonaLookup
    from docintel.pipeline.stages.s5a_cached import ApplyCachedRules
    from docintel.pipeline.stages.s5b_vision import VisionOneShot
    from docintel.pipeline.stages.s5c_agent import AgentEscalation
    from docintel.pipeline.stages.s6_capture import CaptureFields
    from docintel.pipeline.stages.s7_gate import ConfidenceGate
    from docintel.pipeline.stages.s8_emit import EmitRecord

    return Runner(
        stages=[
            Intake(), AttachmentFilter(), Classify(),
            PersonaLookup(store=_StubStore(persona)),
            ApplyCachedRules(executor_factory=lambda persona: _StubExecutor(quality)),
            VisionOneShot(vision=vision), AgentEscalation(),
            CaptureFields(), ConfidenceGate(), EmitRecord(),
        ],
        hooks=HookRegistry(),
    )


def test_persona_hit_with_good_confidence_takes_the_fast_lane_with_zero_vision_calls():
    """The economics of the whole design: a persona hit must cost no AI call."""
    vision = FakeVision()
    rec = _routing_runner(_StubPersona(), quality=0.95, vision=vision).process("d1", CORPUS)
    assert rec["extraction_route"] == "5a_cached"
    assert vision.calls == [], "the fast lane must make ZERO vision calls"
    assert rec["extraction_rule_version"] == "v14"


def test_persona_hit_whose_rules_collapse_falls_back_to_vision():
    """Old selectors against a redesigned template: emit trustworthy values anyway."""
    vision = FakeVision()
    rec = _routing_runner(_StubPersona(), quality=0.10, vision=vision).process("d1", CORPUS)
    assert vision.calls != [], "a collapsed persona must fall back to the vision one-shot"
    assert rec["extraction_route"] == "5b_vision"


def test_soft_miss_still_runs_the_cached_rules_first():
    """Layout drift is usually cosmetic, so try the rules before paying for vision."""
    from docintel.pipeline.stages.s5a_cached import ApplyCachedRules

    ctx = new_context(document_id="d1", source_path=CORPUS)
    ctx.persona_status = "soft_miss"
    ctx.persona = _StubPersona()
    out = ApplyCachedRules(
        executor_factory=lambda persona: _StubExecutor(0.95)
    ).run(ctx)
    assert out.extraction_route == "5a_cached"
    assert out.extracted.get("invoice_number") == "AC-002561"


def test_hard_miss_sets_review_not_regen():
    """A first-time sender has no rules, so regen_flag would be meaningless."""
    rec = _runner().process("d1", CORPUS)
    assert rec["review_flag"] is True
    assert rec["regen_flag"] is False, (
        "regen_flag means 'the rules are wrong'; a hard miss has no rules. "
        "Stage 7 is the sole writer of regen_flag."
    )


def test_unsupported_file_type_is_skipped_with_a_reason_never_dropped():
    rec = _runner().process("d2", "/tmp/notes.txt")
    validate_record(rec)
    assert rec["disposition"] == "skipped"
    assert rec["reason"]


def test_a_scanned_image_is_no_longer_skipped_and_reads_via_ocr(tmp_path):
    """The Stage 2 gap this closes: before `extract.convert` existed, this
    exact PNG would have hit the same `not in ALLOWED_SUFFIXES` branch as
    `.txt` above. Now it converts, and the wrapped page - no text layer at
    all - takes the OCR path exactly like a scanned PDF always has."""
    from PIL import Image

    png = tmp_path / "scan.png"
    Image.new("RGB", (850, 1100), (255, 255, 255)).save(png)

    rec = _runner().process("d-img", str(png))

    validate_record(rec)
    assert rec["disposition"] != "skipped"
    assert rec["text_source"] == "ocr"


def test_an_office_document_reaches_the_office_converter_not_the_allowlist_gate(
    tmp_path, monkeypatch
):
    """Proves the WIRING - that a `.docx` now reaches
    `convert.convert_office_to_pdf` instead of being rejected at the
    allowlist - without needing a real LibreOffice install. The converter
    itself is proven separately, exhaustively, in `tests/extract/test_convert.py`."""
    from docintel.extract import convert

    calls = []

    def fake_convert(path):
        calls.append(path)
        # Hand back a real, tiny PDF so the rest of the pipeline has
        # something legitimate to read.
        import pdfplumber  # noqa: F401  (import proves the fixture path exists)

        out = tmp_path / "converted.pdf"
        from PIL import Image

        Image.new("RGB", (100, 100)).save(out, "PDF")
        return str(out)

    monkeypatch.setattr(convert, "convert_office_to_pdf", fake_convert)

    docx = tmp_path / "invoice.docx"
    docx.write_bytes(b"not a real docx - the converter is faked for this test")

    rec = _runner().process("d-docx", str(docx))

    validate_record(rec)
    assert rec["disposition"] != "skipped"
    assert calls == [str(docx)]


def test_document_id_is_stable_for_the_same_source():
    r = _runner()
    a = r.process("stable-id", CORPUS)
    b = r.process("stable-id", CORPUS)
    assert a["document_id"] == b["document_id"] == "stable-id"


def test_build_pipeline_wires_one_shared_jobs_object_into_both_escalation_stages():
    """`AgentEscalation` (a hard-miss sender) and `ConfidenceGate` (an unknown
    prior_balance_basis) enqueue two different kinds of job from two different
    points in the pipeline - both must write into the SAME queue instance, or
    a reviewer's /review page would only ever see half of what's pending.
    """
    jobs = object()
    runner = build_pipeline(vision=FakeVision(), jobs=jobs)
    escalation = next(s for s in runner.stages if s.name == "agent_escalation")
    gate = next(s for s in runner.stages if s.name == "confidence_gate")
    assert escalation.jobs is jobs
    assert gate.jobs is jobs


def test_build_pipeline_defaults_jobs_to_none_not_a_real_queue():
    """`jobs` must stay a safe no-op by default, exactly like `vision`/`store`
    elsewhere in this module - a function used from tests, the CLI, and the
    web UI is the wrong place for a surprising disk side effect (a real,
    shared `var/jobs.sqlite3` opened just because a caller omitted `jobs=`).
    """
    runner = build_pipeline(vision=FakeVision())
    escalation = next(s for s in runner.stages if s.name == "agent_escalation")
    gate = next(s for s in runner.stages if s.name == "confidence_gate")
    assert escalation.jobs is None
    assert gate.jobs is None


def test_build_pipeline_preserves_a_caller_supplied_hooks_registry():
    """A real-time integrator registers a `beforeEmit` hook BEFORE calling
    `build_pipeline` to get notified the instant a document needs a human
    (`ctx.review_flag`/`ctx.lane`, both set by Stage 7 before `beforeEmit`
    fires) - that hook must survive `build_pipeline`'s own wiring rather than
    being silently discarded in favor of a fresh registry.
    """
    hooks = HookRegistry()
    seen: list[tuple[str, bool, str | None]] = []

    def notify_if_needs_review(ctx, nxt):
        ctx = nxt(ctx)
        seen.append((ctx.document_id, ctx.review_flag, ctx.lane))
        return ctx

    hooks.register("beforeEmit", notify_if_needs_review, pack="my_integration")
    runner = build_pipeline(vision=FakeVision(), hooks=hooks)

    runner.process("d1", CORPUS)

    assert len(seen) == 1
    assert seen[0][0] == "d1"


def test_build_pipeline_still_registers_pack_hooks_alongside_a_caller_supplied_registry():
    """The domain packs' own hooks (`register_all`) must still land on the SAME
    registry a caller passed in - not skipped just because the registry wasn't
    freshly created here.
    """
    hooks = HookRegistry()
    build_pipeline(vision=FakeVision(), hooks=hooks)

    assert hooks.registered("classifySignals") != []


def test_build_pipeline_without_hooks_reproduces_old_behavior():
    """Omitting `hooks` must still process a document exactly as before -
    the new parameter is purely additive."""
    runner = build_pipeline(vision=FakeVision())
    rec = runner.process("d1", CORPUS)
    validate_record(rec)
