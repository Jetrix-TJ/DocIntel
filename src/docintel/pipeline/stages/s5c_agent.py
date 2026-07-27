"""Stage 5c: escalate. Enqueue ONE rule-writing job per persona key, async.

Rule authoring is deliberately out of scope for this build; the job record and
its single-flight guarantee are real, so the seam is honest.
"""

from __future__ import annotations

from docintel.core.models import JobContext

WEAK = 0.60


class AgentEscalation:
    name = "agent_escalation"

    def __init__(self, jobs: object | None = None) -> None:
        self.jobs = jobs

    def run(self, ctx: JobContext) -> JobContext:
        if ctx.persona_status != "hard_miss":
            return ctx
        confidences = list(ctx.extracted.match_quality.values())
        if confidences and min(confidences) >= WEAK:
            return ctx
        ctx.log("s5c: agent_escalation (job queued, authoring deferred)")
        if self.jobs is not None:
            self.jobs.enqueue_once(ctx.sender_fingerprint, ctx.doc_type)  # type: ignore[attr-defined]
        # A review flag, NOT a regen flag. Spec Part 3 "First-time": a hard miss
        # "emits anyway with the one-shot result and a review flag". regen_flag
        # means "the rules are wrong" (Stage 7, Very Low lane) — but a first-time
        # sender has no rules yet, so a regen flag here would send a downstream
        # consumer looking for a regeneration that cannot exist. Stage 7 is the
        # sole writer of regen_flag, so the two never disagree.
        ctx.review_flag = True
        return ctx
