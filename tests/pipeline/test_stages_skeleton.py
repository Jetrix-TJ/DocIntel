from docintel.adapters.vision.fake import FakeVision
from docintel.core.contract import validate_record
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
