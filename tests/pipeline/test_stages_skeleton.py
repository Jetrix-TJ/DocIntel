from docintel.adapters.vision.fake import FakeVision
from docintel.core.contract import validate_record
from docintel.core.models import new_context
from docintel.pipeline.hooks import HookRegistry
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_default_stages

CORPUS = "docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf"


def _runner():
    return Runner(stages=build_default_stages(vision=FakeVision()), hooks=HookRegistry())


def test_every_stage_runs_and_is_logged():
    rec = _runner().process("d1", CORPUS)
    validate_record(rec)


def test_the_default_sequence_is_ten_modules_in_pipeline_order():
    names = [s.name for s in build_default_stages(vision=FakeVision())]
    assert names == [
        "intake", "attachment_filter", "classify", "persona_lookup",
        "apply_cached_rules", "vision_one_shot", "agent_escalation",
        "capture_fields", "confidence_gate", "emit_record",
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
            ApplyCachedRules(executor=_StubExecutor(quality)),
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
    out = ApplyCachedRules(executor=_StubExecutor(0.95)).run(ctx)
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


def test_document_id_is_stable_for_the_same_source():
    r = _runner()
    a = r.process("stable-id", CORPUS)
    b = r.process("stable-id", CORPUS)
    assert a["document_id"] == b["document_id"] == "stable-id"
