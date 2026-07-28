"""Stage 3: what kind of document? Content only, never the filename.

Two things happen here, in this order:

1. **A pack claims the document**, or none does. The claim is the bill-to guard -
   is this invoice addressed to the pack's organization? - and it must come first,
   because the ladder that classifies the document is the pack's.
2. **The `classifySignals` chain runs.** A pack ladder sets `doc_type` and calls
   `next`; the default below fires only if nothing did.

Never the filename. Three of the six Northstar filenames state the answer outright
(`CONTRA ONLY ...`, `CANADIAN WITHOUT NOTES ...`, `... paying $69.62`), and a
classifier that read them would score well on this corpus and teach nothing.
"""

from __future__ import annotations

from docintel.core.models import JobContext
from docintel.packs.registry import Pack, load_packs, resolve_pack
from docintel.pipeline.hooks import HookRegistry

DEFAULT_DOC_TYPE = "standard_invoice"


class Classify:
    name = "classify"

    def __init__(
        self,
        hooks: HookRegistry | None = None,
        packs: list[Pack] | None = None,
    ) -> None:
        self.hooks = hooks
        # Loaded once at construction, not once per document: `load_packs`
        # imports modules, and a per-document import would be paid on every
        # invoice in a batch of thousands.
        self.packs = load_packs() if packs is None else packs

    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("s3: classify")

        ctx.pack = resolve_pack(ctx, self.packs)
        if ctx.pack is None:
            # Not addressed to any known organization. Emitted and flagged rather
            # than dropped: an invoice in the wrong inbox is a real event that
            # somebody needs to see.
            ctx.add_tag("unclaimed_document")
            ctx.log("s3: no pack claimed this document")
        else:
            ctx.log(f"s3: claimed by pack {ctx.pack.name!r}")

        if self.hooks is not None:
            ctx = self.hooks.run("classifySignals", ctx)

        if ctx.doc_type is None:
            ctx.doc_type = DEFAULT_DOC_TYPE
            ctx.signal_that_fired = "default"
            ctx.classification_confidence = 0.50
        return ctx
