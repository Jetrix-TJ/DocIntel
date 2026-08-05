"""count(intaken) == count(emitted) under burst load with injected failures.

If this test ever fails, "nothing is ever dropped" has stopped being true - the
one failure mode the design refuses.
"""

import pytest
from docintel.adapters.vision.fake import FakeVision
from docintel.core.contract import validate_record
from docintel.core.errors import PermanentError, TransientError
from docintel.core.models import JobContext
from docintel.pipeline.hooks import HookRegistry
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_default_stages

CORPUS_DIR = "docs"
INJECTED = [
    PermanentError("corrupt PDF"),
    TransientError("vision timeout"),
    RuntimeError("unexpected"),
    MemoryError("resource exhausted"),
]


def _stages_with_failure_at(index: int, exc: Exception) -> list:
    stages = build_default_stages(vision=FakeVision())

    class Saboteur:
        name = f"saboteur_{index}"

        def run(self, ctx: JobContext) -> JobContext:
            raise exc

    stages.insert(index, Saboteur())
    return stages


@pytest.mark.parametrize("index", range(10))
@pytest.mark.parametrize("exc", INJECTED)
def test_invariant_holds_with_a_failure_injected_at_every_stage(index, exc):
    runner = Runner(stages=_stages_with_failure_at(index, exc), hooks=HookRegistry())
    records = [runner.process(f"d{i}", "docs/Lumen - 5-QXH7QKM7.pdf") for i in range(10)]
    assert len(records) == 10
    assert runner.stats["intaken"] == runner.stats["emitted"] == 10
    for rec in records:
        validate_record(rec)
        assert rec["disposition"] == "dead_letter"


@pytest.mark.parametrize("socket", [
    "beforeIntake", "afterFilter", "beforePersonaLookup",
    "afterExtraction", "beforeConfidenceGate", "beforeEmit",
])
def test_the_invariant_holds_when_a_pack_hook_throws_at_any_socket(socket):
    """End-to-end, not just at the registry.

    The runner dispatches all six boundary sockets, so a third-party pack bug at
    any of them must still produce a record. This is the guarantee that lets an
    operator install an unreviewed pack without risking silent document loss.
    """
    hooks = HookRegistry()

    def boom(ctx, nxt):
        raise RuntimeError("pack bug")

    hooks.register(socket, boom, pack="northstar")
    runner = Runner(stages=build_default_stages(vision=FakeVision()), hooks=hooks)
    records = [runner.process(f"d{i}", "docs/Lumen - 5-QXH7QKM7.pdf") for i in range(5)]

    assert len(records) == 5
    assert runner.stats["intaken"] == runner.stats["emitted"] == 5
    for rec in records:
        validate_record(rec)
        assert rec["disposition"] == "dead_letter"
        assert "northstar" in rec["reason"]


def test_baseexception_escapes_by_design_and_the_counters_report_the_gap():
    """The invariant covers Exception-class failures, NOT BaseException.

    KeyboardInterrupt and SystemExit must propagate: catching them would make a
    runaway pipeline un-interruptible and would swallow interpreter shutdown.
    When one does escape, intaken > emitted — and that is the CORRECT signal, not
    a false alarm: a document entered and produced no record, which is exactly
    what the operator needs to know.

    This test exists so nobody "fixes" the runner to catch BaseException.
    """
    class Interrupt:
        name = "interrupt"

        def run(self, ctx: JobContext) -> JobContext:
            raise KeyboardInterrupt()

    runner = Runner(stages=[Interrupt()], hooks=HookRegistry())
    with pytest.raises(KeyboardInterrupt):
        runner.process("d1", "/tmp/a.pdf")
    assert runner.stats == {"intaken": 1, "emitted": 0}
    assert runner.stats["intaken"] > runner.stats["emitted"]


def test_invariant_holds_across_the_whole_corpus():
    """CORPUS_DIR is a live, growing pool of real samples, not a fixed-size

    fixture — new real documents land here over time (see docs/superpowers/plans/
    2026-08-03-generalization-findings-and-next-tasks.md). The invariant this test
    protects is relative (intaken == emitted == what's really there), not that the
    pool happens to be any particular size.
    """
    runner = Runner(stages=build_default_stages(vision=FakeVision()), hooks=HookRegistry())
    from docintel.adapters.intake.filesystem import FilesystemIntake
    items = list(FilesystemIntake([CORPUS_DIR]).items())
    assert len(items) > 0, "corpus directory should not be empty"
    for item in items:
        runner.process(item.document_id, item.source_path)
    assert runner.stats["intaken"] == runner.stats["emitted"] == len(items)
