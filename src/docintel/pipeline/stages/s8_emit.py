"""Stage 8: the hard contract. Reached by every intaken document."""

from __future__ import annotations

from docintel.core.models import JobContext


class EmitRecord:
    name = "emit_record"

    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("s8: emit_record")
        if ctx.extraction_rule_version is None:
            ctx.extraction_rule_version = "none"
        return ctx
