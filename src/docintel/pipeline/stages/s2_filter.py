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
  When `assign` had to fall all the way back to "page 1, last resort"
  (no page carried an identity anchor or a totals label), it says so via
  its second return value, and this stage turns that into the
  `page_role_fallback` tag — a page-role guess that blind must be visible
  on the record, not just in a log nobody is watching.
- `annotations.detect_flattened` (F3) sets the `has_flattened_annotations`
  tag when a page's markup was baked into its raster image rather than kept
  as a stripped PDF annotation layer. That tag forces review unconditionally
  further down the pipeline (s7); this stage's only job is to raise it.

**Non-PDF formats.** An image or an Office document is converted to a real
PDF right here, before either of the two facts above is computed - so
`load_document` and `detect_flattened` never learn a document arrived as
anything other than a PDF, and neither needed a single change to accept one.
See `extract.convert` for why this is a conversion at the boundary rather
than a second, parallel extraction path. A conversion failure
(`PermanentError`/`TransientError`) is raised, not caught here - the same
discipline `load_document`'s own OCR failures already follow, letting the
`Runner`'s existing retry/dead-letter machinery decide, rather than a second,
inconsistent copy of that decision living in this stage too.
"""

from __future__ import annotations

import os

from docintel.core.models import JobContext
from docintel.extract import annotations, convert, pageroles
from docintel.extract.normalize import load_document

ALLOWED_SUFFIXES = convert.ACCEPTED_SUFFIXES


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

        path = ctx.source_path
        if suffix in convert.IMAGE_SUFFIXES:
            path = convert.convert_image_to_pdf(path)
        elif suffix in convert.OFFICE_SUFFIXES:
            path = convert.convert_office_to_pdf(path)
        if path != ctx.source_path:
            ctx.readable_path = path

        pages, page_meta, text_source = load_document(path)
        ctx.pages = pages
        ctx.page_meta, used_last_resort_role_fallback = pageroles.assign(pages, page_meta)
        ctx.text_source = text_source

        if used_last_resort_role_fallback:
            ctx.add_tag("page_role_fallback")

        if annotations.detect_flattened(path, pages, page_meta):
            ctx.add_tag("has_flattened_annotations")

        return ctx
