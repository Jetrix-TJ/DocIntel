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

**Non-PDF formats — four different treatments, not one.** An Office document
is converted to a real PDF right here, before either of the two facts above
is computed: `grammar/regions.py`'s selectors need measured page geometry a
flow-layout format doesn't have until it is rendered, so
`extract.convert.convert_office_to_pdf` is a genuine requirement, not a
convenience (see `extract.convert`'s own docstring) — for DOCX, always, and
for XLSX, whenever `convert.soffice_available()` says LibreOffice is present.
When it isn't, an XLSX takes a fourth, LibreOffice-free path instead:
`extract.office_fallback.xlsx_to_html` walks the workbook directly and emits
a real `.html` table, read by the SAME unmodified
`extract.plaintext.load_document` a real `.html` file already uses;
`convert_office_to_pdf` is never called for that document at all.
`ctx.readable_path` stays unset on purpose in that branch —
`pipeline.stages.s5b_vision._vision_source_path` reads that absence together
with `ctx.source_format == "xlsx"` as the signal that this fallback tier was
taken, and lazily renders a real image from the original workbook
(`extract.office_render.xlsx_to_image`) if vision is ever reached. A raster
image (`extract.convert.IMAGE_SUFFIXES`) is **never** converted here —
`normalize.load_image_document`/`annotations.detect_flattened_image` read the
source bytes directly, because OCR and annotation detection are format-
agnostic (they only ever needed a rasterizable page, and an image already is
one) and Gemini (Stage 5b) understands JPEG/PNG natively. TXT/CSV/HTML
(`extract.convert.TEXT_SUFFIXES`) are **also never converted or OCR'd** —
`extract.plaintext.load_document` reads them directly into the same
`PageText`/`PageMeta` shape, since none of the three carries visual/layout
signal a render or a vision model could add. `ctx.source_format` records
which treatment a document took, so a later stage (Stage 5b, specifically)
can tell "already a raster, nothing to convert for OCR purposes" apart from
"already a PDF" without re-deriving it from a path extension. A conversion
failure (`PermanentError`/`TransientError`) is raised, not caught here - the
same discipline `load_document`'s own OCR failures already follow, letting
the `Runner`'s existing retry/dead-letter machinery decide, rather than a
second, inconsistent copy of that decision living in this stage too.
"""

from __future__ import annotations

import os

from docintel.core.errors import PermanentError
from docintel.core.models import JobContext
from docintel.extract import (
    annotations,
    convert,
    office_fallback,
    pageroles,
    plaintext,
    xlsx_hidden,
)
from docintel.extract.normalize import load_document, load_image_document

ALLOWED_SUFFIXES = convert.ACCEPTED_SUFFIXES

# A page-count ceiling, checked once every format branch below has settled on
# a final `pages` tuple - generous relative to any real invoice (a 500-page,
# 5MB PDF already measured 42.2s/2,969MB on one thread well under this), so
# crossing it is itself evidence this was never a real invoice/bill. Raising
# `PermanentError` here, rather than catching it locally, matches every other
# Stage 2 rejection in this file (see the module docstring): the `Runner`'s
# existing catch-all in `process()` turns it into `disposition = "dead_letter"`.
MAX_PAGES = 750


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

        if suffix in convert.IMAGE_SUFFIXES:
            # A raster image is never converted to PDF here: OCR and
            # annotation detection both work directly off the source bytes
            # (see `extract.ocr.ocr_image`/`extract.annotations.
            # detect_flattened_image`), and Gemini (Stage 5b) understands
            # JPEG/PNG natively too. `readable_path`/`temp_dirs` stay unset -
            # there is no converted file to clean up. TIFF/BMP/GIF are not
            # Gemini-native MIME types, so for those three suffixes only,
            # Stage 5b converts lazily, once, if and when vision is actually
            # reached - never here.
            ctx.source_format = "image"
            pages, page_meta, text_source = load_image_document(ctx.source_path)
            has_flattened = annotations.detect_flattened_image(ctx.source_path)
        elif suffix in convert.TEXT_SUFFIXES:
            # TXT/CSV/HTML are already text, with no visual/layout signal a
            # render or a vision model could add (see `extract.plaintext`'s
            # module docstring) - never converted, never OCR'd, never sent to
            # vision. `.htm` is just an alias for `.html`.
            ctx.source_format = "html" if suffix in (".html", ".htm") else suffix.lstrip(".")
            pages, page_meta, text_source = plaintext.load_document(ctx.source_path, suffix)
            has_flattened = False  # no raster/annotation layer possible in these formats
        elif suffix == ".xlsx" and not convert.soffice_available():
            # LibreOffice isn't installed - fall through to the LibreOffice-
            # free tier-1 fallback (`extract.office_fallback.xlsx_to_html`):
            # walk the workbook directly and emit a real `.html` table, read
            # by the SAME unmodified `extract.plaintext.load_document` a real
            # `.html` file already uses. `ctx.readable_path` stays unset on
            # purpose - `pipeline.stages.s5b_vision._vision_source_path`
            # reads that absence together with `ctx.source_format == "xlsx"`
            # as the signal that Stage 2 took this fallback tier, and lazily
            # renders a real image from the original workbook if vision is
            # ever reached.
            ctx.source_format = "xlsx"
            html_path = office_fallback.xlsx_to_html(ctx.source_path)
            ctx.temp_dirs.append(os.path.dirname(html_path))
            pages, page_meta, text_source = plaintext.load_document(html_path, ".html")
            has_flattened = False
            if xlsx_hidden.has_hidden_content(ctx.source_path):
                # Same hidden-content signal as the LibreOffice path below -
                # detected against the ORIGINAL workbook either way, since
                # hidden content is exactly what neither render carries
                # forward.
                ctx.add_tag("xlsx_hidden_content_present")
        else:
            path = ctx.source_path
            if suffix in convert.OFFICE_SUFFIXES:
                ctx.source_format = suffix.lstrip(".")
                # Cache-checked: a cache hit skips LibreOffice entirely and
                # returns a long-lived path under `extract.convert_cache`,
                # which must NEVER be registered in `ctx.temp_dirs` (the
                # Runner unconditionally removes everything there after this
                # document) - `temp_dir` is `None` on a hit for exactly that
                # reason, and only a genuine miss's fresh `mkdtemp()` output
                # gets registered below.
                path, temp_dir = convert.convert_to_pdf_cached(path, suffix)
                ctx.readable_path = path
                if temp_dir is not None:
                    ctx.temp_dirs.append(temp_dir)
                if suffix == ".xlsx" and xlsx_hidden.has_hidden_content(ctx.source_path):
                    # Structurally invisible to the render this document just
                    # went through - see `extract.xlsx_hidden`'s module
                    # docstring. Detected against the ORIGINAL workbook, not
                    # the rendered PDF, since hidden content is exactly what
                    # the render never carried forward.
                    ctx.add_tag("xlsx_hidden_content_present")

            pages, page_meta, text_source = load_document(path)
            has_flattened = annotations.detect_flattened(path, pages, page_meta)

        if len(pages) > MAX_PAGES:
            # Checked once here, after every format branch above has settled
            # on a final `pages` tuple, rather than duplicated per-branch -
            # a PDF/Office document is the realistic attack surface (the
            # measured 500-page case), but an image/plaintext/XLSX-fallback
            # document past the ceiling is just as clearly not a real
            # invoice/bill.
            raise PermanentError(
                f"{len(pages)} pages exceeds the {MAX_PAGES}-page ceiling - "
                f"this is almost certainly not a real invoice/bill"
            )

        ctx.pages = pages
        ctx.page_meta, used_last_resort_role_fallback = pageroles.assign(pages, page_meta)
        ctx.text_source = text_source

        if used_last_resort_role_fallback:
            ctx.add_tag("page_role_fallback")

        if has_flattened:
            ctx.add_tag("has_flattened_annotations")

        return ctx
