"""`docintel`: turn a document into a confidence-scored structured record.

The library surface, for an external service embedding this rather than
shelling out to the `docintel` CLI:

    from docintel import build_pipeline, Runner, load_packs
    from docintel.adapters.vision.fake import FakeVision  # or a real adapter

    packs = load_packs()
    pipeline = build_pipeline(vision=FakeVision())
    record = pipeline.process(document_id="d1", source_path="invoice.pdf")

Before this, every real entry point (`build_pipeline`, `Runner`,
`load_packs`) lived three different submodules deep - `docintel.pipeline.
stages`, `docintel.pipeline.runner`, `docintel.packs.registry` - which is
exactly what `webui/app.py` (the one existing "as a library" caller) still
has to reach into. Re-exported here so a new caller has one import instead of
three, without moving or duplicating any of the underlying code - `cli.py`
and `webui/app.py` are intentionally NOT changed to use this facade instead
of their own direct imports, since neither had a real problem this solves.

For a caller that processes documents as they arrive in real time (a webhook
receiver, an inbox poller - `docintel` deliberately includes neither; that's
the caller's own infrastructure, not this library's job) and wants to know the
instant a document needs a human, register a `beforeEmit` hook and pass it to
`build_pipeline`:

    from docintel import build_pipeline, HookRegistry

    def notify_if_needs_review(ctx, nxt):
        ctx = nxt(ctx)  # let the pipeline finish deciding lane/review_flag first
        if ctx.review_flag or ctx.lane == "low":
            my_own_notifier(ctx.document_id, ctx.lane)  # your Slack/email/webhook
        return ctx

    hooks = HookRegistry()
    hooks.register("beforeEmit", notify_if_needs_review, pack="my_integration")
    pipeline = build_pipeline(vision=FakeVision(), hooks=hooks)
"""

from __future__ import annotations

from docintel.packs.registry import load_packs
from docintel.pipeline.hooks import HookRegistry
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_default_stages, build_pipeline

__version__ = "0.1.0"

__all__ = ["HookRegistry", "Runner", "build_default_stages", "build_pipeline", "load_packs"]
