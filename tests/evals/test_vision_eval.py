"""`replay_vision` in two layers: a spy test proving Stage 5a never runs (so
the vision call is genuinely forced, not incidentally triggered by a real
collapse), and a real-pipeline integration test against the gold corpus.
"""

from __future__ import annotations

from docintel.adapters.vision.fake import FakeVision
from docintel.evals.vision_eval import replay_vision
from docintel.pipeline.runner import Runner


class _SpyStage:
    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self._calls = calls

    def run(self, ctx):
        self._calls.append(self.name)
        return ctx


def test_replay_vision_never_runs_apply_cached_rules(monkeypatch):
    """Stage 5a sets `extraction_route = "5a_cached"`, which is the ONE thing
    that could make `VisionOneShot.run()` skip the call again - excluding 5a
    from the slice is what makes this suite's vision call genuinely forced."""
    calls: list[str] = []
    stage_names = [
        "intake", "attachment_filter", "classify", "persona_lookup",
        "apply_cached_rules", "agent_escalation", "capture_fields",
        "confidence_gate", "emit_record",
    ]

    def runner_factory():
        from docintel.pipeline.hooks import HookRegistry

        return Runner(
            stages=[_SpyStage(name, calls) for name in stage_names],
            hooks=HookRegistry(),
        )

    monkeypatch.setattr(
        "docintel.evals.vision_eval.load_gold",
        lambda: [{"gold_id": "fake-1", "source_file": "fake.pdf", "fields": {}}],
    )

    replay_vision(runner_factory, vision=FakeVision())

    assert calls == ["intake", "attachment_filter", "classify", "persona_lookup"]
    assert "apply_cached_rules" not in calls


def test_replay_vision_only_ever_scores_default_fields(monkeypatch):
    calls: list[str] = []

    def runner_factory():
        from docintel.pipeline.hooks import HookRegistry

        return Runner(stages=[_SpyStage("intake", calls)], hooks=HookRegistry())

    monkeypatch.setattr(
        "docintel.evals.vision_eval.load_gold",
        lambda: [{
            "gold_id": "fake-1", "source_file": "fake.pdf",
            "fields": {"vendor_name": "Acme", "total_printed": 10.0, "tax_id": "should-not-appear"},
        }],
    )

    card = replay_vision(runner_factory, vision=FakeVision())

    scored_names = {a["name"] for a in card["documents"][0]["assertions"]}
    assert scored_names == {"vendor_name", "invoice_number", "invoice_date", "total_printed"}


def test_a_stage_exception_upstream_of_vision_does_not_crash_the_rest(monkeypatch):
    """A missing/corrupt source file, or a pack hook throwing, inside
    intake/attachment_filter/classify/persona_lookup - BEFORE vision is even
    called - must not take down every other document's score either. This is
    a distinct failure point from the vision-call try/except below: this one
    guards `_run_through_persona_lookup` itself."""

    class _ExplodingStage:
        name = "intake"

        def run(self, ctx):
            raise FileNotFoundError("no such file")

    def runner_factory():
        from docintel.pipeline.hooks import HookRegistry

        return Runner(stages=[_ExplodingStage()], hooks=HookRegistry())

    monkeypatch.setattr(
        "docintel.evals.vision_eval.load_gold",
        lambda: [
            {"gold_id": "doc-a", "source_file": "a.pdf", "fields": {"vendor_name": "Acme"}},
            {"gold_id": "doc-b", "source_file": "b.pdf", "fields": {"vendor_name": "Widgets"}},
        ],
    )

    card = replay_vision(runner_factory, vision=FakeVision())

    assert card["summary"]["total"] == 2
    assert card["documents"][0]["passed"] is False
    assert "<error:" in card["documents"][0]["assertions"][0]["actual"]
    assert card["documents"][1]["passed"] is False
    assert "<error:" in card["documents"][1]["assertions"][0]["actual"]


def test_a_vision_error_on_one_document_does_not_crash_the_rest(monkeypatch):
    """`CassetteVision` in replay mode raises loudly on a cache miss (Bug 5:
    the shipped cassette has zero entries) - one document's miss must not
    take down every other document's score, the same discipline
    `scorecard.replay_gold` already has for a single assertion's getter."""

    class _ExplodingVision:
        def extract(self, pages, field_names, *, source_path=None, field_hints=None):
            raise KeyError("no cassette entry for this document")

    def runner_factory():
        from docintel.pipeline.hooks import HookRegistry

        return Runner(stages=[_SpyStage("intake", [])], hooks=HookRegistry())

    monkeypatch.setattr(
        "docintel.evals.vision_eval.load_gold",
        lambda: [
            {"gold_id": "doc-a", "source_file": "a.pdf", "fields": {"vendor_name": "Acme"}},
            {"gold_id": "doc-b", "source_file": "b.pdf", "fields": {"vendor_name": "Widgets Co"}},
        ],
    )

    card = replay_vision(runner_factory, vision=_ExplodingVision())

    assert card["summary"]["total"] == 2
    assert card["documents"][0]["passed"] is False
    assert "<error:" in card["documents"][0]["assertions"][0]["actual"]
    # The second document gets its own independent, equally-degraded score -
    # not skipped, not crashed past.
    assert card["documents"][1]["passed"] is False
    assert "<error:" in card["documents"][1]["assertions"][0]["actual"]


def test_replay_vision_scores_the_real_gold_corpus_without_crashing():
    """Integration proof against every real gold document - an honest, mostly
    empty report with `--vision fake`, not a fabricated one."""
    from docintel.pipeline.stages import build_pipeline

    card = replay_vision(
        runner_factory=lambda: build_pipeline(vision=FakeVision()), vision=FakeVision(),
    )

    assert card["summary"]["total"] > 0
    for doc in card["documents"]:
        assert doc["total_count"] in (0, 4)
