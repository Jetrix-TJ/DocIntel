"""Stage 2: worth processing, or politely skipped? Never silently drop."""

from __future__ import annotations

import os

from docintel.core.models import JobContext

ALLOWED_SUFFIXES = {".pdf"}


class AttachmentFilter:
    name = "attachment_filter"

    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("s2: attachment_filter")
        suffix = os.path.splitext(ctx.source_path)[1].lower()
        if suffix not in ALLOWED_SUFFIXES:
            ctx.disposition = "skipped"
            ctx.skip_reason = f"file type {suffix or '(none)'} not in allowlist"
            return ctx
        if not os.path.exists(ctx.source_path):
            ctx.disposition = "skipped"
            ctx.skip_reason = "source file does not exist"
            return ctx
        return ctx
