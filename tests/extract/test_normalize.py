import pytest

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
