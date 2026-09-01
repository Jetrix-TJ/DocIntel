"""Task 10 (alpha-hardening): byte/page/pixel ceilings at intake.

Before this, no ceiling existed anywhere between "a file was handed to
intake" and "it gets rasterized" - a 500-page, 5MB PDF measured 42.2s and
2,969MB on one thread, and `PIL.Image.MAX_IMAGE_PIXELS` was never set, so
Pillow's own decompression-bomb guard sat unused. This file covers the two
guards that landed for it: the `MAX_PAGES` ceiling in `s2_filter.py` (this
module) and the `Image.MAX_IMAGE_PIXELS` setting in `docintel/__init__.py`.
"""

from __future__ import annotations

import pytest

from docintel.adapters.vision.fake import FakeVision
from docintel.core.errors import PermanentError
from docintel.core.models import new_context
from docintel.pipeline.hooks import HookRegistry
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_default_stages
from docintel.pipeline.stages.s2_filter import MAX_PAGES, AttachmentFilter

# Same small real-world corpus PDF `test_stages_skeleton.py` uses, kept as a
# literal here rather than imported across test modules - this is the "any
# real invoice must be completely unaffected" control case.
CORPUS = "docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf"


def _runner() -> Runner:
    return Runner(stages=build_default_stages(vision=FakeVision()), hooks=HookRegistry())


def _make_pdf_with_n_pages(tmp_path, n: int) -> str:
    """A real, N-page PDF - built to be cheap for `load_document` to read,
    not just cheap to write.

    Every page shares ONE small Helvetica content stream and ONE font object
    (each added to the writer exactly once, then referenced by every page,
    not duplicated N times) - so building the file itself is fast even for
    hundreds of pages. More importantly, that shared text is deliberately
    longer than `extract.normalize`'s "starved page" threshold (~29 chars),
    so every page reads as real, native text instead of a blank/near-blank
    one - which keeps `load_document` on its fast native-text path rather
    than falling back to OCRing every page. Measured while writing this
    test: an all-blank 751-page PDF took `load_document` ~75s (it fell to
    OCR); this one, ~2.5s.

    Uses `pypdf` only (already a declared dependency via the `vision`
    extra - no new dependency added just for this test). `PdfWriter.
    _add_object` is a private method, but there is no public equivalent in
    the installed pypdf version for "add a shared, reusable indirect
    object"; acceptable for a test-only helper.
    """
    import pypdf
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = pypdf.PdfWriter()

    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)

    content = DecodedStreamObject()
    content.set_data(
        b"BT /F1 12 Tf 10 100 Td "
        b"(Invoice filler text, deliberately past the starved-page threshold) Tj ET"
    )
    content_ref = writer._add_object(content)

    for _ in range(n):
        page = writer.add_blank_page(width=200, height=200)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
        )
        page[NameObject("/Contents")] = content_ref

    path = tmp_path / f"n{n}-pages.pdf"
    with open(path, "wb") as fh:
        writer.write(fh)
    return str(path)


def test_a_pdf_past_the_page_ceiling_dead_letters_with_a_clear_reason(tmp_path):
    huge_pdf = _make_pdf_with_n_pages(tmp_path, MAX_PAGES + 1)

    rec = _runner().process("d-huge", huge_pdf)

    assert rec["disposition"] == "dead_letter"
    assert "page" in rec["reason"].lower()


def test_attachment_filter_itself_raises_permanent_error_over_the_ceiling(tmp_path):
    """Unit-level: the raise itself, not just the `Runner`'s generic
    catch-all that turns any exception into a dead letter (proven above, and
    already proven generically for every other Stage 2 rejection in this
    file's sibling tests)."""
    huge_pdf = _make_pdf_with_n_pages(tmp_path, MAX_PAGES + 1)
    ctx = new_context(document_id="d-huge", source_path=huge_pdf)

    with pytest.raises(PermanentError, match="page"):
        AttachmentFilter().run(ctx)


def test_a_document_exactly_at_the_page_ceiling_is_not_rejected(tmp_path):
    """Off-by-one discipline: MAX_PAGES itself is still within bounds, only
    strictly-more trips the ceiling."""
    at_ceiling_pdf = _make_pdf_with_n_pages(tmp_path, MAX_PAGES)
    ctx = new_context(document_id="d-at-ceiling", source_path=at_ceiling_pdf)

    out = AttachmentFilter().run(ctx)

    assert len(out.pages) == MAX_PAGES


def test_a_normal_sized_real_invoice_is_completely_unaffected_by_the_ceiling():
    """The ceiling must be invisible to any real invoice - 750 is generous
    relative to anything this pipeline actually processes."""
    rec = _runner().process("d-normal", CORPUS)
    assert rec["disposition"] != "dead_letter"


def test_max_image_pixels_is_set_to_guard_against_decompression_bombs():
    """A 200x200-inch page inside a modest upload rasterizes to roughly
    4.8GB if Pillow's own decompression-bomb guard is left unset (the
    default). Importing `docintel` must set a sane, documented ceiling."""
    from PIL import Image

    import docintel  # noqa: F401 - importing the package must have set this

    assert Image.MAX_IMAGE_PIXELS is not None
    assert Image.MAX_IMAGE_PIXELS < 500_000_000
