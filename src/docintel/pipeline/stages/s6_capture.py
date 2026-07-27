"""Stage 6: per-field confidence, adjust ops, arithmetic cross-checks."""

from __future__ import annotations

from docintel.core.confidence import apply_modifiers
from docintel.core.models import JobContext


class CaptureFields:
    name = "capture_fields"

    def __init__(self, ops: list[object] | None = None) -> None:
        self.ops = ops or []

    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("s6: capture_fields")
        if ctx.text_source == "ocr":
            ctx.add_modifier("ocr_source")
        for op in self.ops:
            ctx = op(ctx)  # type: ignore[operator]
        for name, quality in ctx.extracted.match_quality.items():
            ctx.confidence[name] = apply_modifiers(quality, ctx.modifiers)
        return ctx
