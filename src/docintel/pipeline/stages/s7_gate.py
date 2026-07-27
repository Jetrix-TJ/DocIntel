"""Stage 7: three exits, but every document leaves."""

from __future__ import annotations

import random

from docintel.core.models import JobContext

DEFAULT_THRESHOLD = 0.90
VERY_LOW_SHARE = 0.60


class ConfidenceGate:
    name = "confidence_gate"

    def __init__(
        self,
        thresholds: dict[str, float] | None = None,
        audit_rate: float = 0.0,
        rng: random.Random | None = None,
    ) -> None:
        self.thresholds = thresholds or {}
        self.audit_rate = audit_rate
        self.rng = rng or random.Random(0)

    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("s7: confidence_gate")
        if not ctx.confidence:
            ctx.lane = "low"
            ctx.review_flag = True
            return ctx

        short = [
            name for name, score in ctx.confidence.items()
            if score < self.thresholds.get(name, DEFAULT_THRESHOLD)
        ]
        share = len(short) / len(ctx.confidence)

        if not short:
            ctx.lane = "high"
            if self.audit_rate and self.rng.random() < self.audit_rate:
                ctx.audit_sample = True
                ctx.review_flag = True
        elif share >= VERY_LOW_SHARE:
            ctx.lane = "low"
            ctx.regen_flag = True
            ctx.review_flag = True
        else:
            ctx.lane = "medium"
            ctx.review_flag = True
        return ctx
