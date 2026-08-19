"""`replay_gate` in two layers: a spy-stage unit test proving it never runs
past Stage 3, and a real-pipeline integration test proving it scores the
actual gold corpus without touching `build_record`/`validate_record`.
"""

from __future__ import annotations

from docintel.evals.gate_eval import replay_gate
from docintel.pipeline.runner import Runner


class _SpyStage:
    """Records that it ran; never touches `ctx` beyond that, so any real
    field asserted on (`doc_type`, `tags`, `disposition`) proves nothing was
    silently satisfied by a stage this suite is supposed to exclude."""

    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self._calls = calls

    def run(self, ctx):
        self._calls.append(self.name)
        return ctx


def test_replay_gate_never_invokes_a_stage_past_classify(monkeypatch):
    calls: list[str] = []
    stage_names = [
        "intake", "attachment_filter", "classify", "persona_lookup",
        "apply_cached_rules", "vision_one_shot", "agent_escalation",
        "capture_fields", "confidence_gate", "emit_record",
    ]

    def runner_factory():
        from docintel.pipeline.hooks import HookRegistry

        return Runner(
            stages=[_SpyStage(name, calls) for name in stage_names],
            hooks=HookRegistry(),
        )

    monkeypatch.setattr(
        "docintel.evals.gate_eval.load_gold",
        lambda: [{
            "gold_id": "fake-1", "source_file": "fake.pdf",
            "classification": {"doc_type": "x", "tags": [], "text_source": "native"},
        }],
    )

    replay_gate(runner_factory)

    assert calls == ["intake", "attachment_filter", "classify"]


def test_a_stage_exception_on_one_document_does_not_crash_the_rest(monkeypatch):
    """A missing/corrupt source file, or a pack hook throwing, must not take
    down every other document's score - the stage-running call itself needs
    the same per-document degradation `evals.vision_eval` needs, one layer
    below its own vision-call try/except."""

    class _ExplodingStage:
        name = "intake"

        def run(self, ctx):
            raise FileNotFoundError("no such file")

    def runner_factory():
        from docintel.pipeline.hooks import HookRegistry

        return Runner(stages=[_ExplodingStage()], hooks=HookRegistry())

    monkeypatch.setattr(
        "docintel.evals.gate_eval.load_gold",
        lambda: [
            {"gold_id": "doc-a", "source_file": "a.pdf", "classification": {}},
            {"gold_id": "doc-b", "source_file": "b.pdf", "classification": {}},
        ],
    )

    card = replay_gate(runner_factory)

    assert card["summary"]["total"] == 2
    assert card["documents"][0]["passed"] is False
    assert "<error:" in card["documents"][0]["assertions"][0]["actual"]
    assert card["documents"][1]["passed"] is False
    assert "<error:" in card["documents"][1]["assertions"][0]["actual"]


def test_replay_gate_scores_the_real_gold_corpus_without_crashing():
    """Integration proof: the real pipeline's own Intake/AttachmentFilter/
    Classify stages, run against every real gold document, produce a
    coherent card - not a fabricated one, and no KeyError from a gold file
    missing an optional key."""
    from docintel.adapters.vision.fake import FakeVision
    from docintel.pipeline.stages import build_pipeline

    card = replay_gate(runner_factory=lambda: build_pipeline(vision=FakeVision()))

    assert card["summary"]["total"] > 0
    assert card["summary"]["assertions_total"] == card["summary"]["total"] * 4
    assert card["summary"]["skip_detection"] == {
        "total": 0, "passed": 0,
        "note": "no gold fixture yet represents a should-be-filtered document",
    }
    # Every real gold document is meant to be processed, not filtered out -
    # a regression here (Stage 2 wrongly skipping a real document) would be
    # exactly the kind of bug this suite exists to catch.
    for doc in card["documents"]:
        disposition_check = next(a for a in doc["assertions"] if a["name"] == "disposition")
        assert disposition_check["passed"] is True, doc["gold_id"]
