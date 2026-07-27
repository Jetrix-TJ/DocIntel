"""Stage 4: have we seen this sender and doc type before?"""

from __future__ import annotations

from docintel.core.models import JobContext


class PersonaLookup:
    name = "persona_lookup"

    def __init__(self, store: object | None = None) -> None:
        self.store = store

    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("s4: persona_lookup")
        if ctx.sender_fingerprint is None:
            ctx.sender_fingerprint = "unknown|unknown"
        if self.store is None:
            ctx.persona_status = "hard_miss"
            return ctx
        persona = self.store.lookup(ctx.sender_fingerprint, ctx.doc_type)  # type: ignore[attr-defined]
        ctx.persona = persona
        ctx.persona_status = "hard_miss" if persona is None else "hit"
        if persona is not None:
            ctx.extraction_rule_version = persona.rule_version
        return ctx
