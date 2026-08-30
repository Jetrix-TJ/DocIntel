"""End-to-end FORMAT coverage: every format `extract.convert.ACCEPTED_SUFFIXES`
names, run through the real, public `build_pipeline()` entry point end to
end - the same one `docintel process` uses - confirming each one reaches
Stage 8 with a valid, contract-compliant record and takes the format-
appropriate internal path (per this project's Stage 2 format-aware
architecture: images never touch PDF conversion, DOCX/XLSX render through
LibreOffice and get cached, TXT/CSV/HTML never touch OCR/vision/rendering).

Companion to `test_end_to_end_pipeline.py` (which proves the four pipeline
SHAPES work: known vendor / unknown vendor / corrupt input / whole gold
corpus). This file is organized by FORMAT instead, plus the edge cases
specific to format handling: unsupported extensions, per-format corruption,
empty files, duplicate detection across formats, retry-on-transient-error,
and a mixed-format batch processed by one Runner.

LibreOffice is not installed in this environment, so DOCX/XLSX tests
monkeypatch `convert.convert_office_to_pdf` with a fake that hands back a
small, real, valid PDF - proving the WIRING (Stage 2 routes to the
converter, the converted/cached path reaches extraction, Stage 8 emits)
without needing a real LibreOffice install. The converter function itself is
proven separately and exhaustively in `tests/extract/test_convert.py`.
"""

from __future__ import annotations

import csv as csv_module
import json
import os

import pytest
from PIL import Image, ImageDraw, ImageFont

from docintel import build_pipeline
from docintel.adapters.vision.fake import FakeVision
from docintel.core.contract import validate_record
from docintel.core.errors import TransientError
from docintel.extract import convert
from docintel.pipeline.hooks import HookRegistry
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_default_stages

# A real, already-classified corpus document - the "native PDF" row reuses
# it exactly as `test_end_to_end_pipeline.py` does, rather than hand-rolling
# a second minimal PDF-object-model just for this file.
NATIVE_PDF = "docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf"

_FONT = ImageFont.load_default(size=26)


def _text_image(path, lines: list[str], mode: str = "RGB", size=(700, 320)) -> str:
    background = "white" if mode == "RGB" else 255
    foreground = "black" if mode == "RGB" else 0
    img = Image.new(mode, size, background)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((20, 20 + i * 55), line, font=_FONT, fill=foreground)
    img.save(path)
    return str(path)


def _pipeline(vision=None):
    return build_pipeline(vision=vision or FakeVision())


def _mock_office_conversion(monkeypatch, tmp_path):
    """Stands in for LibreOffice (not installed in this environment) - hands
    back a small, real, valid single-page PDF so the rest of the pipeline has
    something legitimate to read. Proves the WIRING, not the converter
    itself (see `tests/extract/test_convert.py` for that).

    Each call's output MUST live in its own fresh subdirectory, disjoint
    from any sibling document's files - mirroring the real
    `convert_office_to_pdf`'s own `tempfile.mkdtemp()` isolation. A fake that
    put its output directly in the shared `tmp_path` root would make
    `os.path.dirname(real_path)` resolve to that whole shared root; Stage 2
    registers that as `ctx.temp_dirs`, and the Runner's per-document cleanup
    would then `shutil.rmtree` the ENTIRE batch directory - silently
    deleting every other document's file before it's ever processed. (A real
    bug this exact mistake caused, caught by the mixed-format batch test
    below, before it reached a real one.)
    """
    import tempfile

    calls: list[str] = []

    def fake_convert(path):
        calls.append(path)
        out_dir = tempfile.mkdtemp(dir=tmp_path, prefix=f"fake-office-convert-{len(calls)}-")
        out = os.path.join(out_dir, "converted.pdf")
        Image.new("RGB", (100, 100)).save(out, "PDF")
        return out

    monkeypatch.setattr(convert, "convert_office_to_pdf", fake_convert)
    return calls


# ===========================================================================
# 1. Format matrix - one test per accepted format
# ===========================================================================


def test_pdf_native_text_reaches_the_end_of_the_pipeline():
    record = _pipeline().process(document_id="fmt-pdf", source_path=NATIVE_PDF)
    validate_record(record)
    assert record["disposition"] == "processed"
    assert record["text_source"] == "native"


def test_pdf_scanned_image_only_reaches_the_end_of_the_pipeline(tmp_path):
    """Built via the real `convert_image_to_pdf` - the result genuinely has
    no text layer (`char_count == 0` on every page), the same shape as a
    real scanned invoice, so this exercises the real OCR routing decision,
    not a hand-waved stand-in for it."""
    img_path = _text_image(tmp_path / "scan-source.png", ["INVOICE NUMBER INV-40001", "TOTAL DUE 512.00"])
    scanned_pdf = convert.convert_image_to_pdf(img_path)

    record = _pipeline().process(document_id="fmt-pdf-scanned", source_path=scanned_pdf)
    validate_record(record)
    assert record["disposition"] == "processed"
    assert record["text_source"] == "ocr"


@pytest.mark.parametrize("suffix", [".jpg", ".jpeg", ".png"])
def test_gemini_native_images_reach_the_end_of_the_pipeline_with_zero_conversion(
    tmp_path, monkeypatch, suffix
):
    calls: list[str] = []
    real_convert = convert.convert_image_to_pdf
    monkeypatch.setattr(convert, "convert_image_to_pdf", lambda p: (calls.append(p), real_convert(p))[1])

    path = _text_image(tmp_path / f"invoice{suffix}", [f"INVOICE {suffix.upper()} TOTAL 250.00"])

    record = _pipeline().process(document_id=f"fmt-img-{suffix}", source_path=path)

    validate_record(record)
    assert record["disposition"] == "processed"
    assert record["text_source"] == "ocr"
    assert calls == [], f"{suffix} is Gemini-native and must never be converted to PDF"


@pytest.mark.parametrize("suffix", [".bmp", ".gif"])
def test_non_gemini_native_images_convert_lazily_exactly_once(tmp_path, monkeypatch, suffix):
    """BMP/GIF are Pillow-native for OCR (no eager conversion at Stage 2),
    but not Gemini-native - since this document has no persona, it reaches
    vision, which must convert lazily, exactly once."""
    calls: list[str] = []
    real_convert = convert.convert_image_to_pdf
    monkeypatch.setattr(convert, "convert_image_to_pdf", lambda p: (calls.append(p), real_convert(p))[1])

    path = _text_image(tmp_path / f"invoice{suffix}", [f"INVOICE {suffix.upper()} TOTAL 300.00"])

    record = _pipeline().process(document_id=f"fmt-img-lazy-{suffix}", source_path=path)

    validate_record(record)
    assert record["disposition"] == "processed"
    assert len(calls) == 1, f"{suffix} must convert lazily, exactly once, when vision is reached"


def test_multi_frame_tiff_reaches_the_end_of_the_pipeline(tmp_path):
    path = tmp_path / "multi.tiff"
    frame_a = Image.new("RGB", (700, 320), "white")
    ImageDraw.Draw(frame_a).text((20, 20), "PAGE ONE INVOICE", font=_FONT, fill="black")
    frame_b = Image.new("RGB", (700, 320), "white")
    ImageDraw.Draw(frame_b).text((20, 20), "PAGE TWO TOTAL 700.00", font=_FONT, fill="black")
    frame_a.save(path, save_all=True, append_images=[frame_b])

    record = _pipeline().process(document_id="fmt-tiff-multi", source_path=str(path))
    validate_record(record)
    assert record["disposition"] == "processed"


def test_docx_reaches_the_end_of_the_pipeline(tmp_path, monkeypatch):
    calls = _mock_office_conversion(monkeypatch, tmp_path)
    docx = tmp_path / "invoice.docx"
    docx.write_bytes(b"not a real docx - the converter is faked for this test")

    record = _pipeline().process(document_id="fmt-docx", source_path=str(docx))

    validate_record(record)
    assert record["disposition"] == "processed"
    assert calls == [str(docx)]


def test_xlsx_reaches_the_end_of_the_pipeline(tmp_path, monkeypatch):
    _mock_office_conversion(monkeypatch, tmp_path)
    monkeypatch.setattr(convert, "soffice_available", lambda: True)
    openpyxl = pytest.importorskip("openpyxl")
    xlsx = tmp_path / "invoice.xlsx"
    wb = openpyxl.Workbook()
    wb.active["A1"] = "Invoice Total 900.00"
    wb.save(xlsx)

    record = _pipeline().process(document_id="fmt-xlsx", source_path=str(xlsx))

    validate_record(record)
    assert record["disposition"] == "processed"
    assert "xlsx_hidden_content_present" not in record["tags"]


def test_xlsx_with_hidden_content_is_flagged_for_review(tmp_path, monkeypatch):
    _mock_office_conversion(monkeypatch, tmp_path)
    monkeypatch.setattr(convert, "soffice_available", lambda: True)
    openpyxl = pytest.importorskip("openpyxl")
    xlsx = tmp_path / "invoice-hidden.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "Invoice Total 900.00"
    ws["C1"] = "internal reconciled total"
    ws.column_dimensions["C"].hidden = True
    wb.save(xlsx)

    record = _pipeline().process(document_id="fmt-xlsx-hidden", source_path=str(xlsx))

    validate_record(record)
    assert record["disposition"] == "processed"
    assert "xlsx_hidden_content_present" in record["tags"]
    assert record["lane"] == "review"
    assert record["review_flag"] is True


def test_xlsx_without_libreoffice_with_hidden_content_is_flagged_for_review(tmp_path, monkeypatch):
    """Same hidden-content signal as `test_xlsx_with_hidden_content_is_flagged_for_review`
    above, but for the LibreOffice-free fallback branch (`s2_filter.py`'s
    `elif suffix == ".xlsx" and not convert.soffice_available():`) - that
    branch detects hidden content against the ORIGINAL workbook exactly like
    the LibreOffice path does, and this proves it's actually wired, not just
    documented."""
    monkeypatch.setattr(convert, "soffice_available", lambda: False)
    openpyxl = pytest.importorskip("openpyxl")

    xlsx = tmp_path / "invoice-hidden.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "Invoice Total 900.00"
    ws["C1"] = "internal reconciled total"
    ws.column_dimensions["C"].hidden = True
    wb.save(xlsx)

    record = _pipeline().process(document_id="fmt-xlsx-hidden-fallback", source_path=str(xlsx))

    validate_record(record)
    assert record["disposition"] == "processed"
    assert "xlsx_hidden_content_present" in record["tags"]
    assert record["lane"] == "review"
    assert record["review_flag"] is True


def test_xlsx_without_libreoffice_extracts_via_html_fallback_with_zero_vision_calls(tmp_path, monkeypatch):
    """No LibreOffice on this host - tier 1 (`extract.office_fallback.xlsx_to_html`)
    must extract a strong-match document alone, at zero vision cost."""
    monkeypatch.setattr(convert, "soffice_available", lambda: False)
    openpyxl = pytest.importorskip("openpyxl")

    pack_dir = tmp_path / "pack"
    (pack_dir / "personas").mkdir(parents=True)
    (pack_dir / "pack.json").write_text(json.dumps({
        "name": "xlsxfallback",
        "default_currency": "USD",
        "doc_types": ["invoice"],
        "fields": {
            "invoice": {
                "all": ["vendor_name", "invoice_number", "total_printed"],
                "required": ["vendor_name"],
                "any_of": [],
                "derived_only": [],
            }
        },
        "claim": {
            "rules": [{"kind": "markers", "scope": "primary", "values": ["XLSXFALLBACK CORP"]}],
            "vetoes": [],
        },
        "ladder": {
            "default": "invoice",
            "rungs": [{
                "name": "invoice_confirmed",
                "doc_type": "invoice",
                "when": {
                    "signal": "pattern_in_scope",
                    "params": {"pattern": "XLSXFALLBACK CORP", "scope": "primary"},
                },
            }],
        },
    }), encoding="utf-8")
    (pack_dir / "personas" / "xlsxfallback.json").write_text(json.dumps({
        "rule_version": "v1",
        "status": "active",
        "doc_type": "invoice",
        "sender_fingerprint": "xlsxfallback|xlsxfallback",
        "field_selectors": [
            {"field": "vendor_name", "anchor": "Vendor Name:", "region": "near-anchor", "pattern": "text"},
            {"field": "invoice_number", "anchor": "Invoice Number:", "region": "near-anchor", "pattern": "text"},
            {"field": "total_printed", "anchor": "Total Due:", "region": "near-anchor", "pattern": "currency"},
        ],
    }), encoding="utf-8")

    from docintel.packs.datapack import load_pack_file
    pack = load_pack_file(str(pack_dir / "pack.json"))

    xlsx = tmp_path / "invoice.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=1, column=1, value="Vendor Name: XLSXFALLBACK CORP")
    ws.cell(row=2, column=1, value="Invoice Number: INV-9001")
    ws.cell(row=3, column=1, value="Total Due: $500.00")
    wb.save(xlsx)

    vision = FakeVision()
    pipeline = build_pipeline(vision=vision, extra_packs=[pack])
    record = pipeline.process(document_id="xlsx-fallback-tier1", source_path=str(xlsx))

    validate_record(record)
    assert record["disposition"] == "processed"
    assert record["extraction_route"] == "5a_cached"
    assert vision.calls == [], "tier 1 alone must reach a confident cached-rule extraction"
    assert record["fields"]["vendor_name"] == "XLSXFALLBACK CORP"
    assert record["fields"]["invoice_number"] == "INV-9001"


def test_xlsx_without_libreoffice_escalates_to_a_rendered_image_when_cached_rules_collapse(tmp_path, monkeypatch):
    """Same fallback tier 1 as above, but the workbook doesn't carry any of
    the persona's declared fields - cached rules collapse, and Stage 5b must
    escalate to a REAL rendered `.png`, never the raw `.xlsx` path."""
    monkeypatch.setattr(convert, "soffice_available", lambda: False)
    openpyxl = pytest.importorskip("openpyxl")

    pack_dir = tmp_path / "pack"
    (pack_dir / "personas").mkdir(parents=True)
    (pack_dir / "pack.json").write_text(json.dumps({
        "name": "xlsxfallback",
        "default_currency": "USD",
        "doc_types": ["invoice"],
        "fields": {
            "invoice": {
                "all": ["vendor_name", "invoice_number", "total_printed"],
                "required": ["vendor_name"],
                "any_of": [],
                "derived_only": [],
            }
        },
        "claim": {
            "rules": [{"kind": "markers", "scope": "primary", "values": ["XLSXFALLBACK CORP"]}],
            "vetoes": [],
        },
        "ladder": {
            "default": "invoice",
            "rungs": [{
                "name": "invoice_confirmed",
                "doc_type": "invoice",
                "when": {
                    "signal": "pattern_in_scope",
                    "params": {"pattern": "XLSXFALLBACK CORP", "scope": "primary"},
                },
            }],
        },
    }), encoding="utf-8")
    (pack_dir / "personas" / "xlsxfallback.json").write_text(json.dumps({
        "rule_version": "v1",
        "status": "active",
        "doc_type": "invoice",
        "sender_fingerprint": "xlsxfallback|xlsxfallback",
        "field_selectors": [
            {"field": "vendor_name", "anchor": "Vendor Name:", "region": "near-anchor", "pattern": "text"},
            {"field": "invoice_number", "anchor": "Invoice Number:", "region": "near-anchor", "pattern": "text"},
            {"field": "total_printed", "anchor": "Total Due:", "region": "near-anchor", "pattern": "currency"},
        ],
    }), encoding="utf-8")

    from docintel.packs.datapack import load_pack_file
    pack = load_pack_file(str(pack_dir / "pack.json"))

    # Claims the pack (carries the marker) but declares none of the
    # persona's anchors - a genuine cached-rule collapse, not a bad fixture.
    xlsx = tmp_path / "invoice.xlsx"
    wb = openpyxl.Workbook()
    wb.active.cell(row=1, column=1, value="XLSXFALLBACK CORP - see attached statement")
    wb.save(xlsx)

    vision = FakeVision()
    pipeline = build_pipeline(vision=vision, extra_packs=[pack])
    record = pipeline.process(document_id="xlsx-fallback-tier2", source_path=str(xlsx))

    validate_record(record)
    assert record["disposition"] == "processed"
    assert vision.calls, "a cached-rule collapse must escalate to vision"
    assert vision.sources[0] is not None
    assert vision.sources[0].endswith(".png"), (
        f"vision must receive a rendered image, not the raw xlsx path - got {vision.sources[0]!r}"
    )


def test_txt_reaches_the_end_of_the_pipeline_with_zero_vision_calls(tmp_path):
    vision = FakeVision()
    txt = tmp_path / "invoice.txt"
    txt.write_text("Invoice Number: INV-50001\nTotal Due: 640.00\n", encoding="utf-8")

    record = _pipeline(vision).process(document_id="fmt-txt", source_path=str(txt))

    validate_record(record)
    assert record["disposition"] == "processed"
    assert record["text_source"] == "native"
    assert vision.calls == [], "TXT has no visual content - vision must never be called"


def test_csv_reaches_the_end_of_the_pipeline_with_zero_vision_calls(tmp_path):
    vision = FakeVision()
    csv_path = tmp_path / "invoice.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv_module.writer(fh)
        writer.writerow(["Vendor", "Invoice Number", "Total"])
        writer.writerow(["ACME Utilities", "INV-50002", "410.00"])

    record = _pipeline(vision).process(document_id="fmt-csv", source_path=str(csv_path))

    validate_record(record)
    assert record["disposition"] == "processed"
    assert record["text_source"] == "native"
    assert vision.calls == []


def test_html_reaches_the_end_of_the_pipeline_with_zero_vision_calls(tmp_path):
    vision = FakeVision()
    html = tmp_path / "invoice.html"
    html.write_text(
        "<html><body><p>Invoice Number: INV-50003</p><p>Total Due: 220.00</p></body></html>",
        encoding="utf-8",
    )

    record = _pipeline(vision).process(document_id="fmt-html", source_path=str(html))

    validate_record(record)
    assert record["disposition"] == "processed"
    assert record["text_source"] == "native"
    assert vision.calls == []


def test_htm_alias_reaches_the_end_of_the_pipeline(tmp_path):
    htm = tmp_path / "invoice.htm"
    htm.write_text("<p>Invoice Number: INV-50004</p>", encoding="utf-8")
    record = _pipeline().process(document_id="fmt-htm", source_path=str(htm))
    validate_record(record)
    assert record["disposition"] == "processed"


# ===========================================================================
# 2. Edge cases
# ===========================================================================


def test_a_genuinely_unsupported_extension_is_skipped_never_dropped(tmp_path):
    path = tmp_path / "presentation.pptx"
    path.write_bytes(b"stub bytes")
    record = _pipeline().process(document_id="edge-unsupported", source_path=str(path))
    validate_record(record)
    assert record["disposition"] == "skipped"
    assert record["reason"]


def test_a_missing_file_is_skipped_never_dropped():
    record = _pipeline().process(document_id="edge-missing", source_path="/definitely/not/real.pdf")
    validate_record(record)
    assert record["disposition"] == "skipped"
    assert record["reason"]


@pytest.mark.parametrize(
    "name,content",
    [
        ("empty.txt", ""),
        ("empty.csv", ""),
        ("empty.html", ""),
    ],
)
def test_an_empty_text_native_file_still_emits_a_valid_record(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    record = _pipeline().process(document_id=f"edge-empty-{name}", source_path=str(path))
    validate_record(record)
    assert record["disposition"] == "processed"


def test_an_empty_image_file_dead_letters_cleanly(tmp_path):
    path = tmp_path / "empty.png"
    path.write_bytes(b"")
    record = _pipeline().process(document_id="edge-empty-png", source_path=str(path))
    validate_record(record)
    assert record["disposition"] == "dead_letter"
    assert record["review_flag"] is True
    assert record["reason"]


def test_a_corrupted_image_dead_letters_cleanly(tmp_path):
    path = tmp_path / "corrupt.jpg"
    path.write_bytes(b"this is not a real jpeg, just garbage bytes")
    record = _pipeline().process(document_id="edge-corrupt-jpg", source_path=str(path))
    validate_record(record)
    assert record["disposition"] == "dead_letter"
    assert record["review_flag"] is True


def test_a_corrupted_xlsx_dead_letters_cleanly(tmp_path, monkeypatch):
    """The office CONVERTER (LibreOffice/`convert_office_to_pdf`) is what
    would actually reject a corrupt XLSX in production - simulated here by
    letting the mock raise the same error class the real one does."""
    from docintel.core.errors import PermanentError

    def fake_convert(path):
        raise PermanentError(f"soffice could not convert {path!r}: corrupt file")

    monkeypatch.setattr(convert, "convert_office_to_pdf", fake_convert)
    monkeypatch.setattr(convert, "soffice_available", lambda: True)
    path = tmp_path / "corrupt.xlsx"
    path.write_bytes(b"not a real xlsx at all")

    record = _pipeline().process(document_id="edge-corrupt-xlsx", source_path=str(path))
    validate_record(record)
    assert record["disposition"] == "dead_letter"
    assert record["review_flag"] is True


def test_a_duplicate_document_is_flagged_within_one_run(tmp_path):
    """Same bytes, processed twice through the same `Runner` (not two
    separate `build_pipeline()` calls - duplicate detection is scoped to one
    `Runner`'s `IdentityIndex`, see `core.duplicates`)."""
    txt = tmp_path / "repeat.txt"
    txt.write_text("Invoice Number: INV-60001\nTotal Due: 100.00\n", encoding="utf-8")

    runner = Runner(stages=build_default_stages(vision=FakeVision()), hooks=HookRegistry())

    first = runner.process("dup-1", str(txt))
    second = runner.process("dup-2", str(txt))

    validate_record(first)
    validate_record(second)
    assert first["possible_duplicate_of"] is None
    assert second["possible_duplicate_of"] == "dup-1"


def test_a_transient_stage_failure_is_retried_and_still_succeeds(tmp_path):
    """Proves the Runner's own retry contract end to end: a stage that fails
    once with `TransientError` and succeeds on retry must still produce a
    normally `processed` record - not a dead letter - because
    `build_pipeline`'s default `max_retries=2` gives it a second attempt."""

    class _FlakyOnce:
        name = "flaky_once"

        def __init__(self) -> None:
            self.attempts = 0

        def run(self, ctx):
            self.attempts += 1
            if self.attempts == 1:
                raise TransientError("simulated one-time transient failure")
            return ctx

    flaky = _FlakyOnce()
    runner = _pipeline()
    runner.stages.insert(0, flaky)

    txt = tmp_path / "flaky.txt"
    txt.write_text("Invoice Number: INV-70001\nTotal Due: 50.00\n", encoding="utf-8")

    record = runner.process(document_id="edge-retry", source_path=str(txt))

    validate_record(record)
    assert record["disposition"] == "processed", "a transient failure must be retried, not dead-lettered"
    assert flaky.attempts == 2, "expected exactly one retry after the first transient failure"


# ===========================================================================
# 3. Mixed-format batch - one Runner, every format, back to back
# ===========================================================================


def test_a_mixed_format_batch_processes_correctly_with_no_cross_document_leakage(tmp_path, monkeypatch):
    """The real-world case this whole architecture exists for: one vendor
    batch containing PDFs, images, Office documents, and plain text, all
    processed through the SAME `Runner` (matching the README's "one Runner
    per worker, reused across many documents" guidance), with no shared-
    state leakage between documents of different formats."""
    _mock_office_conversion(monkeypatch, tmp_path)
    monkeypatch.setattr(convert, "soffice_available", lambda: True)

    import tempfile

    created_dirs: list[str] = []
    real_mkdtemp = tempfile.mkdtemp

    def spy_mkdtemp(*args, **kwargs):
        directory = real_mkdtemp(*args, **kwargs)
        created_dirs.append(directory)
        return directory

    monkeypatch.setattr(tempfile, "mkdtemp", spy_mkdtemp)

    documents: list[tuple[str, str]] = []

    documents.append(("batch-pdf", NATIVE_PDF))

    png_path = _text_image(tmp_path / "batch.png", ["INVOICE BATCH PNG TOTAL 111.00"])
    documents.append(("batch-png", png_path))

    tiff_path = tmp_path / "batch.tiff"
    Image.new("RGB", (700, 320), "white").save(tiff_path)
    documents.append(("batch-tiff", str(tiff_path)))

    docx_path = tmp_path / "batch.docx"
    docx_path.write_bytes(b"not a real docx")
    documents.append(("batch-docx", str(docx_path)))

    txt_path = tmp_path / "batch.txt"
    txt_path.write_text("Invoice Number: INV-80001\nTotal Due: 999.00\n", encoding="utf-8")
    documents.append(("batch-txt", str(txt_path)))

    csv_path = tmp_path / "batch.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        csv_module.writer(fh).writerow(["Vendor", "Total"])
        csv_module.writer(fh).writerow(["ACME", "50.00"])
    documents.append(("batch-csv", str(csv_path)))

    html_path = tmp_path / "batch.html"
    html_path.write_text("<p>Invoice Number: INV-80002</p>", encoding="utf-8")
    documents.append(("batch-html", str(html_path)))

    runner = Runner(stages=build_default_stages(vision=FakeVision()), hooks=HookRegistry())

    records = [runner.process(doc_id, path) for doc_id, path in documents]

    for (doc_id, _), record in zip(documents, records):
        validate_record(record)
        assert record["disposition"] == "processed", f"{doc_id} did not process cleanly"

    assert runner.stats["intaken"] == runner.stats["emitted"] == len(documents)

    # No leaked temp directories after the whole batch is done - every
    # `mkdtemp()` call any stage made for any document (the DOCX conversion,
    # TIFF's lazy vision conversion) must have been cleaned up by the
    # Runner's own per-document `finally` block, one document at a time -
    # not merely by the time the whole batch finishes.
    assert created_dirs, "expected at least one temp dir across a batch containing DOCX/TIFF"
    leaked = [d for d in created_dirs if os.path.isdir(d)]
    assert leaked == [], f"temp directories were not cleaned up: {leaked}"
