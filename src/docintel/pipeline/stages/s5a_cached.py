"""Stage 5a: run the saved selectors. Zero AI calls. The high-volume fast lane.

Holds an executor **factory**, not an executor. A `grammar.Executor` is bound to
one persona, and the persona is looked up per document at Stage 4 - so a single
long-lived executor instance would either be stale or belong to whichever
document happened to arrive first. The factory is also the test seam: a stub
factory can return anything with an `apply`, which is how the routing tests
drive a specific match quality without authoring a real persona.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from docintel.core.models import JobContext
from docintel.grammar.executor import Executor


class SupportsApply(Protocol):
    def apply(self, ctx: JobContext) -> JobContext: ...


ExecutorFactory = Callable[[Any], SupportsApply]


class ApplyCachedRules:
    name = "apply_cached_rules"

    def __init__(self, executor_factory: ExecutorFactory | None = None) -> None:
        self._factory: ExecutorFactory = executor_factory or Executor

    def run(self, ctx: JobContext) -> JobContext:
        if ctx.persona_status not in ("hit", "soft_miss"):
            return ctx
        ctx.log("s5a: apply_cached_rules")
        if ctx.persona is None:
            # A persona status without a persona means Stage 4 is still a stub
            # (it becomes real in C7). Nothing to run, and no route to claim.
            return ctx
        ctx = self._factory(ctx.persona).apply(ctx)
        ctx.extraction_route = "5a_cached"
        return ctx
