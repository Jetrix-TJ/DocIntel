import pytest
from docintel.core.contract import validate_record
from docintel.core.errors import PackError, PermanentError, TransientError
from docintel.core.models import JobContext
from docintel.grammar.ops.derive import derive_document_identity
from docintel.pipeline.hooks import HookRegistry
from docintel.pipeline.runner import Runner


def _classified(ctx: JobContext) -> JobContext:
    """Stand in for the stages every real run performs before emit.

    validate_record requires a non-empty doc_type on a record whose disposition
    is "processed". A stage double that never classifies would therefore
    (correctly) degrade to dead_letter, so these doubles set it the way the real
    Classify stage does.

    Since C3 the same is true of `document_identity` / `identity_basis`: a
    processed record must carry both, because downstream dedup needs them for the
    documents that print no invoice number (F6). Stage 6 always derives them, so
    a double that skips Stage 6 stands in for it here rather than these tests
    asserting a contract violation they are not about.
    """
    if ctx.doc_type is None:
        ctx.doc_type = "standard_invoice"
    derive_document_identity(ctx)
    return ctx


class Ok:
    name = "ok"

    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("ok")
        return _classified(ctx)


class Boom:
    name = "boom"

    def __init__(self, exc):
        self.exc = exc

    def run(self, ctx: JobContext) -> JobContext:
        raise self.exc


def _runner(stages):
    return Runner(stages=stages, hooks=HookRegistry())


def test_happy_path_emits_a_valid_record():
    r = _runner([Ok(), Ok()])
    rec = r.process("d1", "/tmp/a.pdf")
    validate_record(rec)
    assert rec["disposition"] == "processed"
    assert r.stats == {"intaken": 1, "emitted": 1}


@pytest.mark.parametrize("exc", [
    PermanentError("corrupt"),
    PackError("pack blew up"),
    RuntimeError("unexpected"),
    ValueError("nonsense"),
])
def test_any_stage_failure_still_emits_a_dead_letter(exc):
    """The one failure mode this design refuses is silence."""
    r = _runner([Ok(), Boom(exc), Ok()])
    rec = r.process("d1", "/tmp/a.pdf")
    validate_record(rec)
    assert rec["disposition"] == "dead_letter"
    assert r.stats == {"intaken": 1, "emitted": 1}


def test_transient_error_is_retried_then_dead_lettered():
    class Flaky:
        name = "flaky"

        def __init__(self):
            self.calls = 0

        def run(self, ctx):
            self.calls += 1
            raise TransientError("timeout")

    flaky = Flaky()
    r = Runner(stages=[flaky], hooks=HookRegistry(), max_retries=2)
    rec = r.process("d1", "/tmp/a.pdf")
    assert flaky.calls == 3            # initial + 2 retries
    assert rec["disposition"] == "dead_letter"
    assert r.stats == {"intaken": 1, "emitted": 1}


def test_transient_error_that_recovers_emits_processed():
    class Flaky:
        name = "flaky"

        def __init__(self):
            self.calls = 0

        def run(self, ctx):
            self.calls += 1
            if self.calls < 2:
                raise TransientError("timeout")
            return _classified(ctx)

    r = Runner(stages=[Flaky()], hooks=HookRegistry(), max_retries=2)
    rec = r.process("d1", "/tmp/a.pdf")
    validate_record(rec)
    assert rec["disposition"] == "processed"
    assert r.stats == {"intaken": 1, "emitted": 1}


def test_the_invariant_holds_over_a_burst_with_mixed_failures():
    """count(intaken) == count(emitted), the alertable promise from spec Stage 8."""
    r = _runner([Ok(), Boom(RuntimeError("x")), Ok()])
    records = [r.process(f"d{i}", f"/tmp/{i}.pdf") for i in range(50)]
    assert len(records) == 50
    assert r.stats["intaken"] == r.stats["emitted"] == 50
    for rec in records:
        validate_record(rec)


def test_a_throwing_pack_hook_still_emits_a_dead_letter():
    """The docstring's claim that a pack hook is a guarded escape route, made real.

    A hook registered by a third-party pack raises. The document must still emit.
    """
    hooks = HookRegistry()

    def boom(ctx, nxt):
        raise RuntimeError("pack bug")

    hooks.register("afterFilter", boom, pack="northstar")

    class Filter:
        name = "attachment_filter"

        def run(self, ctx: JobContext) -> JobContext:
            return _classified(ctx)

    r = Runner(stages=[Filter()], hooks=hooks)
    rec = r.process("d1", "/tmp/a.pdf")
    validate_record(rec)
    assert rec["disposition"] == "dead_letter"
    assert "northstar" in rec["reason"]
    assert r.stats == {"intaken": 1, "emitted": 1}


def test_hooks_fire_at_their_declared_boundaries():
    """Each boundary socket the runner owns must actually be dispatched."""
    hooks = HookRegistry()
    fired: list[str] = []

    for socket in ("beforeIntake", "afterFilter", "beforePersonaLookup",
                   "afterExtraction", "beforeConfidenceGate", "beforeEmit"):
        hooks.register(
            socket,
            (lambda s: lambda ctx, nxt: (fired.append(s), nxt(ctx))[1])(socket),
            pack="probe",
        )

    class Named:
        def __init__(self, name: str) -> None:
            self.name = name

        def run(self, ctx: JobContext) -> JobContext:
            return _classified(ctx)

    stages = [Named(n) for n in ("intake", "attachment_filter", "persona_lookup",
                                "capture_fields", "confidence_gate", "emit_record")]
    Runner(stages=stages, hooks=hooks).process("d1", "/tmp/a.pdf")
    assert fired == ["beforeIntake", "afterFilter", "beforePersonaLookup",
                     "afterExtraction", "beforeConfidenceGate", "beforeEmit"]


def test_beforeEmit_fires_even_for_a_skipped_document():
    """Skipped documents never reach the emit stage, but they DO emit a record."""
    hooks = HookRegistry()
    fired: list[str] = []
    hooks.register("beforeEmit", lambda ctx, nxt: (fired.append("x"), nxt(ctx))[1],
                   pack="probe")

    class Skipper:
        name = "attachment_filter"

        def run(self, ctx: JobContext) -> JobContext:
            ctx.disposition = "skipped"
            ctx.skip_reason = "not in allowlist"
            return ctx

    rec = Runner(stages=[Skipper()], hooks=hooks).process("d1", "/tmp/a.png")
    assert rec["disposition"] == "skipped"
    assert fired == ["x"], "beforeEmit must reach every emitted record"


def test_a_record_that_fails_validation_degrades_instead_of_raising():
    """The invariant must survive its own enforcement machinery failing.

    If validate_record raised out of process(), the caller would get an
    exception instead of a record while the emitted counter had already been
    bumped — so stats would claim a document was emitted when none was.
    """
    class Corrupt:
        name = "corrupt"

        def run(self, ctx: JobContext) -> JobContext:
            ctx.doc_type = None          # illegal on a processed record (see _classified)
            ctx.confidence["x"] = 99.0   # illegal: outside [0, 0.99]
            return ctx

    r = _runner([Corrupt()])
    rec = r.process("d1", "/tmp/a.pdf")
    validate_record(rec)                 # the returned record is itself valid
    assert rec["disposition"] == "dead_letter"
    assert "contract validation failed" in rec["reason"]
    assert r.stats == {"intaken": 1, "emitted": 1}


def test_a_stage_that_returns_none_is_a_programming_error_not_silent_data_loss():
    class Bad:
        name = "bad"

        def run(self, ctx):
            return None

    rec = _runner([Bad()]).process("d1", "/tmp/a.pdf")
    assert rec["disposition"] == "dead_letter"
    assert "must return a JobContext" in rec["reason"]
