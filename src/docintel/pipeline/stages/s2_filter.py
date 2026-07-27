"""Stage 2: worth processing, or politely skipped? Never silently drop.

Also where the document's text is read for the first time (F2): once a file
clears the allowlist and exists, `normalize.load_document` decides native vs.
OCR and the result is stashed on the context so nothing downstream re-reads
the PDF or re-runs OCR.
"""

from __future__ import annotations

import os

from docintel.core.models import JobContext
from docintel.extract.normalize import load_document

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

        pages, page_meta, text_source = load_document(ctx.source_path)
        ctx.pages = pages
        ctx.page_meta = page_meta
        ctx.text_source = text_source
        return ctx
