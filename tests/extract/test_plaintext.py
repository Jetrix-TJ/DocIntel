"""`extract.plaintext`: TXT/CSV/HTML read directly into `PageText`/`PageMeta`,
no OCR, no rendering, no vision - ever."""

from __future__ import annotations

from docintel.extract import plaintext


def _write(path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


# -- TXT ----------------------------------------------------------------


def test_txt_preserves_each_source_line_as_its_own_page_line(tmp_path):
    path = _write(
        tmp_path / "invoice.txt",
        "Invoice Number: INV-58291\nTotal Due: 1204.50\nAccount: 00457-KL\n",
    )
    pages, meta, text_source = plaintext.load_document(path, ".txt")

    assert text_source == "native"
    assert len(pages) == 1
    lines = pages[0].text.splitlines()
    assert lines == [
        "Invoice Number: INV-58291",
        "Total Due: 1204.50",
        "Account: 00457-KL",
    ]


def test_txt_char_count_and_zero_image_annot_count(tmp_path):
    path = _write(tmp_path / "a.txt", "hello world")
    pages, meta, _ = plaintext.load_document(path, ".txt")
    assert meta[0].char_count == len(pages[0].text)
    assert meta[0].image_count == 0
    assert meta[0].annot_count == 0


def test_an_empty_txt_file_is_a_valid_zero_word_page(tmp_path):
    path = _write(tmp_path / "empty.txt", "")
    pages, meta, text_source = plaintext.load_document(path, ".txt")
    assert text_source == "native"
    assert pages[0].words == ()
    assert pages[0].text == ""


def test_txt_survives_non_utf8_bytes_without_raising(tmp_path):
    path = tmp_path / "latin1.txt"
    path.write_bytes("café invoice: 100 total".encode("latin-1"))
    pages, meta, _ = plaintext.load_document(str(path), ".txt")
    # errors="replace" must never raise - the exact replacement characters
    # are not the point, only that a real non-UTF-8 file degrades instead of
    # crashing the pipeline.
    assert pages[0].words


# -- CSV ------------------------------------------------------------------


def test_csv_row_becomes_one_page_line(tmp_path):
    path = _write(
        tmp_path / "invoice.csv",
        "Vendor,Invoice Number,Total\nACME Utilities,INV-58292,450.00\n",
    )
    pages, meta, text_source = plaintext.load_document(path, ".csv")

    assert text_source == "native"
    lines = pages[0].text.splitlines()
    assert len(lines) == 2
    assert "ACME" in lines[1] and "INV-58292" in lines[1] and "450.00" in lines[1]


def test_csv_quoting_with_embedded_commas_is_handled_by_the_csv_module(tmp_path):
    """A quoted cell containing a comma must stay one cell's worth of
    content, not fracture into extra columns - proving this module defers to
    the real `csv` reader rather than a naive `line.split(",")`."""
    path = _write(
        tmp_path / "quoted.csv",
        'Description,Amount\n"Base Service, Tier 2",850.00\n',
    )
    pages, meta, _ = plaintext.load_document(path, ".csv")
    lines = pages[0].text.splitlines()
    assert "Base Service, Tier 2" in lines[1] or "Base Service Tier 2" in lines[1].replace(",", "")
    assert "850.00" in lines[1]


def test_an_empty_csv_file_is_a_valid_zero_row_page(tmp_path):
    path = _write(tmp_path / "empty.csv", "")
    pages, meta, text_source = plaintext.load_document(path, ".csv")
    assert text_source == "native"
    assert pages[0].words == ()


# -- HTML -------------------------------------------------------------------


def test_html_strips_tags_and_keeps_block_boundaries_as_lines(tmp_path):
    html = (
        "<html><body>"
        "<h1>ACME UTILITIES</h1>"
        "<p>Invoice Number: INV-58293</p>"
        "</body></html>"
    )
    path = _write(tmp_path / "invoice.html", html)
    pages, meta, text_source = plaintext.load_document(path, ".html")

    assert text_source == "native"
    lines = [ln for ln in pages[0].text.splitlines() if ln.strip()]
    assert lines == ["ACME UTILITIES", "Invoice Number: INV-58293"]


def test_html_table_cells_are_space_separated_not_glued(tmp_path):
    """A real bug caught by manual testing: adjacent `<td>` cells with no
    text between them must not concatenate into one unreadable token."""
    html = "<table><tr><td>Total</td><td>900.00</td></tr></table>"
    path = _write(tmp_path / "table.html", html)
    pages, meta, _ = plaintext.load_document(path, ".html")
    assert "Total900.00" not in pages[0].text
    assert "Total" in pages[0].text and "900.00" in pages[0].text


def test_html_script_and_style_bodies_are_never_extracted_as_text(tmp_path):
    html = (
        "<html><body>"
        "<p>Real content</p>"
        "<script>var total = 999999;</script>"
        "<style>.total { color: red; }</style>"
        "</body></html>"
    )
    path = _write(tmp_path / "with-script.html", html)
    pages, meta, _ = plaintext.load_document(path, ".html")
    assert "999999" not in pages[0].text
    assert "color" not in pages[0].text
    assert "Real content" in pages[0].text


def test_htm_suffix_is_an_alias_for_html(tmp_path):
    html = "<p>Invoice Number: INV-58299</p>"
    path = _write(tmp_path / "invoice.htm", html)
    pages, meta, text_source = plaintext.load_document(path, ".htm")
    assert text_source == "native"
    assert "INV-58299" in pages[0].text


def test_an_empty_html_file_is_a_valid_zero_word_page(tmp_path):
    path = _write(tmp_path / "empty.html", "")
    pages, meta, text_source = plaintext.load_document(path, ".html")
    assert text_source == "native"
    assert pages[0].words == ()


def test_malformed_html_does_not_raise(tmp_path):
    """`html.parser.HTMLParser` is deliberately lenient - a real-world file
    with unclosed tags must degrade to best-effort text, not crash Stage 2."""
    path = _write(tmp_path / "broken.html", "<p>Unclosed paragraph <b>bold text")
    pages, meta, _ = plaintext.load_document(path, ".html")
    assert "Unclosed paragraph" in pages[0].text
    assert "bold text" in pages[0].text
