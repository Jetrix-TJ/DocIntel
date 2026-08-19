"""Stage 5c: `AgentEscalation` in isolation.

Never had its own file before - only exercised indirectly through routing
tests (`test_stages_skeleton.py`) and the wiring assertion that `build_pipeline`
passes the same `jobs` object to it. This file is the direct unit contract:
when does it queue a `persona_authoring` job, and when does it deliberately not.
"""

from __future__ import annotations

from docintel.core.models import new_context
from docintel.pipeline.stages.s5c_agent import WEAK, AgentEscalation


class _SpyJobs:
    """Records every `enqueue_once` call instead of touching a real store."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def enqueue_once(self, sender_fingerprint, doc_type, kind, context=None):
        self.calls.append((sender_fingerprint, doc_type, kind, context))
        return True


def _ctx(persona_status: str | None, **confidences: float):
    ctx = new_context("d1", "/x.pdf", sender_fingerprint="acme|acme", doc_type="invoice")
    ctx.persona_status = persona_status
    for name, quality in confidences.items():
        ctx.extracted.set(name, "some-value", quality)
    return ctx


def test_a_persona_hit_never_escalates():
    jobs = _SpyJobs()
    out = AgentEscalation(jobs=jobs).run(_ctx("hit", total_printed=0.30))
    assert jobs.calls == []
    assert out.review_flag is False


def test_a_soft_miss_never_escalates():
    """Only s5c owns hard_miss; soft_miss routes through 5a/5b instead."""
    jobs = _SpyJobs()
    out = AgentEscalation(jobs=jobs).run(_ctx("soft_miss", total_printed=0.30))
    assert jobs.calls == []
    assert out.review_flag is False


def test_a_hard_miss_with_no_confidences_at_all_escalates():
    """No persona AND nothing was even attempted - the clearest case."""
    jobs = _SpyJobs()
    out = AgentEscalation(jobs=jobs).run(_ctx("hard_miss"))
    assert len(jobs.calls) == 1
    assert out.review_flag is True


def test_a_hard_miss_with_weak_confidence_escalates():
    jobs = _SpyJobs()
    out = AgentEscalation(jobs=jobs).run(_ctx("hard_miss", total_printed=WEAK - 0.01))
    assert len(jobs.calls) == 1
    assert out.review_flag is True


def test_a_hard_miss_with_confidence_exactly_at_the_weak_floor_does_not_escalate():
    """`>= WEAK` is the boundary - documents this exact edge rather than leaving
    it to whichever way a future refactor happens to round."""
    jobs = _SpyJobs()
    out = AgentEscalation(jobs=jobs).run(_ctx("hard_miss", total_printed=WEAK))
    assert jobs.calls == []
    assert out.review_flag is False


def test_a_hard_miss_with_good_confidence_does_not_escalate():
    """A hard miss whose one-shot result is trustworthy anyway needs no queue
    entry - see the docstring on WEAK for why 'no persona' and 'no confidence'
    are not the same fact."""
    jobs = _SpyJobs()
    out = AgentEscalation(jobs=jobs).run(_ctx("hard_miss", total_printed=0.95))
    assert jobs.calls == []
    assert out.review_flag is False


def test_the_weakest_of_several_fields_governs_the_decision():
    jobs = _SpyJobs()
    out = AgentEscalation(jobs=jobs).run(
        _ctx("hard_miss", total_printed=0.95, vendor_name=WEAK - 0.01)
    )
    assert len(jobs.calls) == 1
    assert out.review_flag is True


def test_the_job_carries_the_sender_fingerprint_doc_type_and_persona_authoring_kind():
    jobs = _SpyJobs()
    AgentEscalation(jobs=jobs).run(_ctx("hard_miss"))
    sender_fingerprint, doc_type, kind, context = jobs.calls[0]
    assert sender_fingerprint == "acme|acme"
    assert doc_type == "invoice"
    assert kind == "persona_authoring"
    assert context is not None
    assert "record_snapshot" in context


def test_the_job_context_carries_a_record_snapshot_a_reviewer_can_correct_against():
    """The whole point of Phase 2: a job with nothing to correct against is
    just a note-taking exercise. This snapshot is what `/review/<id>/correct`
    later renders as editable fields."""
    jobs = _SpyJobs()
    out = AgentEscalation(jobs=jobs).run(
        _ctx("hard_miss", total_printed=WEAK - 0.01, vendor_name=WEAK - 0.01)
    )
    _, _, _, context = jobs.calls[0]
    snapshot = context["record_snapshot"]
    assert snapshot["document_id"] == out.document_id
    assert snapshot["source_path"] == out.source_path
    assert snapshot["sender_fingerprint"] == "acme|acme"
    assert snapshot["classification"]["doc_type"] == "invoice"
    assert snapshot["fields"] == {"total_printed": "some-value", "vendor_name": "some-value"}
    assert snapshot["derived"] == {}


def test_the_record_snapshot_survives_a_decimal_field_value(tmp_path):
    """`fields`/`derived` can hold `Decimal` amounts, which `json.dumps` (the
    job queue's own storage format) cannot serialize directly - this must not
    raise when the job actually gets enqueued into a real `SQLiteJobQueue`."""
    from decimal import Decimal

    from docintel.jobs.store import SQLiteJobQueue

    ctx = _ctx("hard_miss", total_printed=WEAK - 0.01)
    ctx.extracted.set("total_printed", Decimal("123.45"), WEAK - 0.01)
    ctx.derived.set("amount_payable", Decimal("123.45"))

    jobs = SQLiteJobQueue(tmp_path / "jobs.sqlite3")
    AgentEscalation(jobs=jobs).run(ctx)

    job = jobs.list_open("persona_authoring")[0]
    snapshot = job.context["record_snapshot"]
    assert snapshot["fields"]["total_printed"] == "123.45"
    assert snapshot["derived"]["amount_payable"] == "123.45"


def test_jobs_none_is_a_safe_no_op():
    """The default - a hard miss must still set review_flag even with nowhere
    to enqueue into, exactly like it did before this queue existed."""
    out = AgentEscalation().run(_ctx("hard_miss"))
    assert out.review_flag is True


def test_escalation_happens_at_most_once_per_document():
    jobs = _SpyJobs()
    AgentEscalation(jobs=jobs).run(_ctx("hard_miss"))
    assert len(jobs.calls) == 1
