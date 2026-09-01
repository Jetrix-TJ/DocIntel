"""Task 10 (alpha-hardening): byte/page/pixel ceilings at intake.

Before this, no ceiling existed anywhere between "a file was handed to
intake" and "it gets rasterized" - a 500-page, 5MB PDF measured 42.2s and
2,969MB on one thread. This file covers the `MAX_PAGES` ceiling in
`s2_filter.py` (enforced both cheaply pre-load for PDFs and as a post-load
backstop for every other branch), plus a regression guard that importing
`docintel` never LOOSENS Pillow's own decompression-bomb default - which,
contrary to the original Task 10 belief, was never unset.
"""

from __future__ import annotations

import pytest

from docintel.adapters.vision.fake import FakeVision
from docintel.core.errors import PermanentError
from docintel.core.models import PageText, new_context
from docintel.pipeline.hooks import HookRegistry
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_default_stages
from docintel.pipeline.stages import s2_filter
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


def test_an_over_ceiling_pdf_is_rejected_before_load_document_is_ever_called(tmp_path, monkeypatch):
    """The point of the ceiling, not just its wording.

    Checking `len(pages)` after `load_document` returns bounds the RECORD but
    not the resource burn: the measured 500-page case spent 42.2s/2,969MB
    inside `load_document` itself, so a hostile 751-page document would still
    pay all of it before being rejected. `_reject_past_page_ceiling` counts
    pages with `pdfplumber` first (page tree only - no text extraction, no
    rasterization, no OCR).

    Proven by making `load_document` itself fail the test if it is reached at
    all, rather than by timing, which would be flaky.
    """
    huge_pdf = _make_pdf_with_n_pages(tmp_path, MAX_PAGES + 1)

    def must_not_be_called(*args, **kwargs):
        raise AssertionError(
            "load_document was called on an over-ceiling PDF - the page ceiling "
            "ran after the expensive work instead of before it"
        )

    monkeypatch.setattr(s2_filter, "load_document", must_not_be_called)
    ctx = new_context(document_id="d-huge", source_path=huge_pdf)

    with pytest.raises(PermanentError, match="page"):
        AttachmentFilter().run(ctx)


def test_the_post_load_ceiling_survives_as_the_backstop_for_non_pdf_branches(tmp_path, monkeypatch):
    """The pre-check is PDF-only (that is the branch where the load is
    expensive), so the original post-`load_document` check must stay reachable
    for the image/plaintext/XLSX-fallback branches. Exercised here through the
    plaintext branch: a `.csv` never touches `_reject_past_page_ceiling`, so
    only the backstop can reject it.
    """
    csv_path = tmp_path / "many-pages.csv"
    csv_path.write_text("a,b\n1,2\n", encoding="utf-8")

    over_ceiling_pages = tuple(
        PageText(
            page_number=i + 1, words=(), width=612.0, height=792.0, source="native"
        )
        for i in range(MAX_PAGES + 1)
    )
    monkeypatch.setattr(
        s2_filter.plaintext,
        "load_document",
        lambda path, suffix: (over_ceiling_pages, tuple(), "native"),
    )
    ctx = new_context(document_id="d-csv", source_path=str(csv_path))

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


# Pillow's own shipped default: `1024*1024*1024 // 4 // 3`. Pillow warns above
# this and raises above 2x it. Spelled out as an expression, not just the
# literal, so the relationship stays legible if Pillow ever changes it.
PILLOW_DEFAULT_MAX_IMAGE_PIXELS = 1024 * 1024 * 1024 // 4 // 3  # 89,478,485


def test_max_image_pixels_is_no_looser_than_pillows_own_default():
    """The decompression-bomb ceiling must never be RAISED by importing us.

    Pillow's default is not unset - it is ~89.5M pixels, already ~10x a real
    300 DPI Letter page (~8.5M). An earlier version of `docintel/__init__.py`
    set 400,000,000 believing the default was unset, which loosened the guard
    4.47x; the assertion that caught nothing was `< 500_000_000`, which the
    untouched default satisfies too. Asserting against the real default is
    what makes this test able to fail.
    """
    from PIL import Image

    import docintel  # noqa: F401 - importing the package must not have loosened this

    assert Image.MAX_IMAGE_PIXELS is not None
    assert Image.MAX_IMAGE_PIXELS <= PILLOW_DEFAULT_MAX_IMAGE_PIXELS
