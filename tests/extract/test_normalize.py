from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from docintel.core.errors import PermanentError
from docintel.extract import ocr
from docintel.extract.normalize import load_document

NATIVE = [
    ("docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf", 1),
    ("docs/_AP Invoice 715-33905296    Veritiv Operating Company 4908.00000.pdf", 1),
    ("docs/CANADIAN WITHOUT NOTES U- PAK 4378107 (1).pdf", 5),
    ("docs/Centracom_0384043574_01012026_BILL.pdf", 10),
    ("docs/Comcast_8495 44 462 0365242_12092025_BILL.pdf", 6),
    ("docs/EDCO 77087APR25 current charges can be misleading, paying $69.62.pdf", 1),
    ("docs/Lumen - 5-QXH7QKM7.pdf", 6),
    ("docs/Windstream_041069076_07222025_BILL.pdf", 4),
]
IMAGE_ONLY = [
    ("docs/_AP Invoice 32930 Complete Beverage Destruction 1177.70000.pdf", 4),
    ("docs/CONTRA ONLY Everything already on AR Federal Recycling 1330123.pdf", 1),
]


@pytest.mark.parametrize("path,pages", NATIVE)
def test_native_documents_use_the_text_layer(path, pages):
    got_pages, meta, source = load_document(path)
    assert source == "native"
    assert len(got_pages) == pages


@pytest.mark.parametrize("path,pages", IMAGE_ONLY)
def test_image_only_documents_route_to_ocr(path, pages):
    """20% of the corpus has zero text layer, and both render crisply (F2)."""
    got_pages, meta, source = load_document(path)
    assert source == "ocr"
    assert len(got_pages) == pages
    assert sum(len(p.words) for p in got_pages) > 0


def test_ocr_output_has_the_same_shape_as_native():
    """The seam that makes the grammar executor blind to source."""
    native, _, _ = load_document(NATIVE[0][0])
    ocr, _, _ = load_document(IMAGE_ONLY[1][0])
    assert type(native[0]) is type(ocr[0])
    for page in ocr:
        assert page.source == "ocr"
        assert all(w.x1 >= w.x0 for w in page.words)


def test_edco_current_charges_survives_extraction():
    """The F1 trap must be reachable: 69.62 distinguishable from 367.96."""
    pages, _, _ = load_document(
        "docs/EDCO 77087APR25 current charges can be misleading, paying $69.62.pdf"
    )
    text = pages[0].text
    assert "CURRENT CHARGES" in text
    assert "69.62" in text
    assert "298.34" in text


def test_upak_total_is_on_the_last_page_not_the_first():
    """F9: page 1's Please Pay cell is blank."""
    pages, _, _ = load_document("docs/CANADIAN WITHOUT NOTES U- PAK 4378107 (1).pdf")
    assert "14740.85" in pages[-1].text.replace(",", "")
    assert "14740.85" not in pages[0].text.replace(",", "")


# --- Synthetic mixed-document fixture -------------------------------------
#
# No corpus document is mixed (all ten are 0 chars/page or 500+, per F2), so
# a per-page-routing regression can only be caught by a document this
# project has never actually seen. Building it for real - rather than
# faking a "scanned" page as a text page with a handful of characters -
# is the point: only a genuine image-only page (no text-drawing operator in
# its content stream at all) exercises the same code path a real scanned
# attachment does, and only a genuine embedded, legible raster image proves
# OCR can still read words off it.
#
# No PDF-writing library is a project dependency (only pdfplumber,
# pytesseract and Pillow are - see pyproject.toml), so this hand-rolls just
# enough of the PDF object model - objects, an image XObject stream, a
# content stream, and a classic xref table - to produce a file pdfplumber
# (via pdfium) opens like any real PDF.

_PAGE_W = 612  # US Letter, points
_PAGE_H = 792
_IMG_RESOLUTION = 200  # dpi - matches ocr.RESOLUTION so the render stays crisp
_IMG_W = int(_PAGE_W * _IMG_RESOLUTION / 72)
_IMG_H = int(_PAGE_H * _IMG_RESOLUTION / 72)

_FILLER = (
    "Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod "
    "tempor incididunt ut labore et dolore magna aliqua invoice attachment "
)


def _scanned_page_jpeg(page_index: int) -> bytes:
    """A grayscale page image with real, legible, OCR-able text and no text layer."""
    img = Image.new("L", (_IMG_W, _IMG_H), color=255)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=90)
    draw.text((100, 100), f"SCANNED ATTACHMENT PAGE {page_index}", font=font, fill=0)
    draw.text((100, 260), "REFERENCE COPY NOT AN ORIGINAL", font=font, fill=0)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


class _PDFObjects:
    """Minimal writer for a flat, uncompressed, single-xref-section PDF."""

    def __init__(self) -> None:
        self._bodies: dict[int, bytes] = {}
        self._next = 1

    def reserve(self) -> int:
        n = self._next
        self._next += 1
        return n

    def put(self, num: int, body: bytes) -> None:
        self._bodies[num] = body

    def build(self) -> bytes:
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: dict[int, int] = {}
        for num in sorted(self._bodies):
            offsets[num] = len(out)
            out += f"{num} 0 obj\n".encode()
            out += self._bodies[num]
            out += b"\nendobj\n"
        xref_offset = len(out)
        count = self._next
        out += f"xref\n0 {count}\n".encode()
        out += b"0000000000 65535 f \n"
        for num in range(1, count):
            off = offsets.get(num, 0)
            out += f"{off:010d} 00000 n \n".encode()
        out += b"trailer\n"
        out += f"<< /Size {count} /Root 1 0 R >>\n".encode()
        out += b"startxref\n"
        out += f"{xref_offset}\n".encode()
        out += b"%%EOF"
        return bytes(out)


def _pdf_with_page_char_counts(tmp_path: Path, char_counts: list[int]) -> Path:
    """Build a PDF whose pages carry the given approximate character counts.

    A count of 0 builds a genuinely scanned-style page: an embedded raster
    image with real, OCR-legible text and NO text-drawing operators in its
    content stream, so pdfplumber's text-layer extraction reads exactly ""
    from it (char_count == 0) - the same shape as the corpus's image-only
    invoices. A nonzero count builds a native text page: one Tj run of
    filler text truncated to that many characters, so pdfplumber's text
    layer reads real words directly, no rendering required.
    """
    pdf = _PDFObjects()
    catalog_num = pdf.reserve()
    pages_num = pdf.reserve()
    font_num = pdf.reserve()

    kids: list[int] = []
    page_bodies: list[tuple[int, bytes]] = []

    for i, count in enumerate(char_counts, start=1):
        page_num = pdf.reserve()
        content_num = pdf.reserve()
        kids.append(page_num)

        if count == 0:
            image_num = pdf.reserve()
            jpeg_bytes = _scanned_page_jpeg(i)
            pdf.put(
                image_num,
                (
                    f"<< /Type /XObject /Subtype /Image /Width {_IMG_W} "
                    f"/Height {_IMG_H} /ColorSpace /DeviceGray "
                    f"/BitsPerComponent 8 /Filter /DCTDecode "
                    f"/Length {len(jpeg_bytes)} >>\nstream\n"
                ).encode()
                + jpeg_bytes
                + b"\nendstream",
            )
            content = f"q {_PAGE_W} 0 0 {_PAGE_H} 0 0 cm /Im0 Do Q".encode()
            pdf.put(
                content_num,
                f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
            )
            page_dict = (
                f"<< /Type /Page /Parent {pages_num} 0 R "
                f"/MediaBox [0 0 {_PAGE_W} {_PAGE_H}] "
                f"/Resources << /XObject << /Im0 {image_num} 0 R >> >> "
                f"/Contents {content_num} 0 R >>"
            ).encode()
        else:
            text = (_FILLER * (count // len(_FILLER) + 1))[:count]
            escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            content = f"BT /F1 10 Tf 50 700 Td ({escaped}) Tj ET".encode()
            pdf.put(
                content_num,
                f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
            )
            page_dict = (
                f"<< /Type /Page /Parent {pages_num} 0 R "
                f"/MediaBox [0 0 {_PAGE_W} {_PAGE_H}] "
                f"/Resources << /Font << /F1 {font_num} 0 R >> >> "
                f"/Contents {content_num} 0 R >>"
            ).encode()

        page_bodies.append((page_num, page_dict))

    for num, body in page_bodies:
        pdf.put(num, body)

    kids_str = " ".join(f"{k} 0 R" for k in kids)
    pdf.put(catalog_num, f"<< /Type /Catalog /Pages {pages_num} 0 R >>".encode())
    pdf.put(
        pages_num,
        f"<< /Type /Pages /Kids [{kids_str}] /Count {len(kids)} >>".encode(),
    )
    pdf.put(font_num, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    path = tmp_path / "mixed.pdf"
    path.write_bytes(pdf.build())
    return path


def test_a_mixed_document_ocrs_only_the_starved_pages(tmp_path) -> None:
    """A native invoice with scanned attachment pages.

    No corpus document has this shape - all ten are 0 chars/page or 500+ - so
    this fixture is synthetic on purpose: corpus-only tests cannot detect the
    gap they do not contain.
    """
    path = _pdf_with_page_char_counts(tmp_path, [2343, 0, 0, 0])
    pages, meta, text_source = load_document(str(path))
    assert [p.source for p in pages] == ["native", "ocr", "ocr", "ocr"]
    assert all(p.words for p in pages), "an OCR'd page must not come back wordless"


def test_any_starved_page_makes_the_document_ocr_sourced(tmp_path) -> None:
    """Deliberately conservative, and it is the reason "mixed" was rejected.

    `s6_capture` applies the `ocr_source` confidence penalty on
    `text_source == "ocr"`, and the Northstar ladder keys `ocr_only` and its
    handwriting check off the same value. A third value would have skipped all
    three on exactly the document whose text we trust least.
    """
    path = _pdf_with_page_char_counts(tmp_path, [2343, 0, 0, 0])
    _, _, text_source = load_document(str(path))
    assert text_source == "ocr"


def test_an_all_native_document_still_reports_native(tmp_path) -> None:
    path = _pdf_with_page_char_counts(tmp_path, [2343, 1800])
    _, _, text_source = load_document(str(path))
    assert text_source == "native"


def test_an_all_scanned_document_still_reports_ocr(tmp_path) -> None:
    path = _pdf_with_page_char_counts(tmp_path, [0, 0])
    _, _, text_source = load_document(str(path))
    assert text_source == "ocr"


def test_only_the_starved_pages_are_sent_to_tesseract(tmp_path, monkeypatch) -> None:
    """The whole point of the change: OCR is the expensive step. A four-page
    document with one native page must OCR three pages, not four.
    """
    seen: list[list[int]] = []
    real = ocr.ocr_pages
    monkeypatch.setattr(ocr, "ocr_pages", lambda p, n: seen.append(n) or real(p, n))
    path = _pdf_with_page_char_counts(tmp_path, [2343, 0, 0, 0])
    load_document(str(path))
    assert seen == [[2, 3, 4]]


def test_ocr_returning_a_short_result_raises_permanent_not_silently_falls_back(
    tmp_path, monkeypatch
) -> None:
    """Step 3's critical-gap check: if OCR comes back missing a requested page,
    falling back to the native page for it would silently return the wordless
    native page - no error, no tag, no visibility. Raising instead turns that
    into a dead letter, with the reason on the record.

    `PermanentError`, not `TransientError`: the one reachable trigger is a
    deterministic mismatch between `pdf.read_meta` and `pdfplumber.pages`, so
    a retry gets the identical answer - worse, `ocr.ocr_pages` has already
    written the short result to its on-disk cache by the time this is raised,
    so a retry (or a later run) reads the same incomplete result back from
    cache rather than re-OCRing. `_run_one` only retries `TransientError`, so
    this dead-letters on the first attempt rather than wasting `max_retries`
    on a failure retrying cannot fix.
    """
    path = _pdf_with_page_char_counts(tmp_path, [2343, 0, 0, 0])
    real = ocr.ocr_pages
    monkeypatch.setattr(ocr, "ocr_pages", lambda p, n: real(p, n)[:1])
    with pytest.raises(PermanentError):
        load_document(str(path))


def test_the_all_scanned_branch_also_enforces_completeness(tmp_path, monkeypatch) -> None:
    """The invariant - one `PageText` per `PageMeta` - holds on the all-scanned
    branch too, not only on the mixed branch. Not reachable via any corpus
    document today (all ten either OCR nothing or OCR everything cleanly),
    but the same completeness check now runs on both `ocr`-returning paths.
    """
    path = _pdf_with_page_char_counts(tmp_path, [0, 0, 0])
    real = ocr.ocr_pages
    monkeypatch.setattr(ocr, "ocr_pages", lambda p, n: real(p, n)[:1])
    with pytest.raises(PermanentError):
        load_document(str(path))
