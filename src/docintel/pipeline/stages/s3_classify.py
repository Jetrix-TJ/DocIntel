"""Stage 3: what kind of document? Content only, never the filename."""

from __future__ import annotations

from docintel.core.models import JobContext


class Classify:
    name = "classify"

    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("s3: classify")
        # Pack signal ladders arrive at the classifySignals socket in cluster C5.
        # Until then every document takes the default branch below.
        if ctx.doc_type is None:
            ctx.doc_type = "standard_invoice"
            ctx.signal_that_fired = "default"
            ctx.classification_confidence = 0.50
        return ctx
