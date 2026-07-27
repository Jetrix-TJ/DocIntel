"""Stage 2: worth processing, or politely skipped? Never silently drop.

Also where the document's text is read for the first time (F2): once a file
clears the allowlist and exists, `normalize.load_document` decides native vs.
OCR and the result is stashed on the context so nothing downstream re-reads
the PDF or re-runs OCR.

Two more page-level facts are settled here, right after load, because both
depend only on `pages`/`page_meta` and both gate what later stages are
allowed to do with a page:

- `pageroles.assign` (F10) labels every page `primary` or `supporting` so a
  later extraction stage can restrict field capture to `primary` pages
  without losing reference-pattern matching on the rest. `page_meta` on the
  context is *replaced* with the assigned tuple, never mutated in place —
  `assign` hands back new `PageMeta` instances precisely so the memoized
  tuple `load_document` returned is left untouched for the next caller.
- `annotations.detect_flattened` (F3) sets the `has_flattened_annotations`
  tag when a page's markup was baked into its raster image rather than kept
  as a stripped PDF annotation layer. That tag forces review unconditionally
  further down the pipeline (s7); this stage's only job is to raise it.
"""

from __future__ import annotations

import os

from docintel.core.models import JobContext
from docintel.extract import annotations, pageroles
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
        ctx.page_meta = pageroles.assign(pages, page_meta)
        ctx.text_source = text_source

        if annotations.detect_flattened(ctx.source_path, pages, page_meta):
            ctx.add_tag("has_flattened_annotations")

        return ctx
