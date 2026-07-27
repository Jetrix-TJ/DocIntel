"""Stage 5a: run the saved selectors. Zero AI calls. The high-volume fast lane."""

from __future__ import annotations

from docintel.core.models import JobContext


class ApplyCachedRules:
    name = "apply_cached_rules"

    def __init__(self, executor: object | None = None) -> None:
        self.executor = executor

    def run(self, ctx: JobContext) -> JobContext:
        if ctx.persona_status not in ("hit", "soft_miss"):
            return ctx
        ctx.log("s5a: apply_cached_rules")
        if self.executor is None:
            return ctx
        ctx = self.executor.apply(ctx)  # type: ignore[attr-defined]
        ctx.extraction_route = "5a_cached"
        return ctx
