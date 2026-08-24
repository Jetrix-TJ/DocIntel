"""`extract.convert`: non-PDF inputs become a real, pdfplumber-readable PDF
before anything downstream ever sees them.
"""

from __future__ import annotations

import subprocess

import pdfplumber
import pytest
from PIL import Image

from docintel.core.errors import PermanentError, TransientError
from docintel.extract import convert

# ---------------------------------------------------------------------------
# the suffix registry
# ---------------------------------------------------------------------------


def test_accepted_suffixes_is_pdf_plus_image_plus_office_plus_text():
    assert convert.ACCEPTED_SUFFIXES == (
        {".pdf"} | convert.IMAGE_SUFFIXES | convert.OFFICE_SUFFIXES | convert.TEXT_SUFFIXES
    )


def test_image_and_office_suffixes_never_overlap():
    assert not (convert.IMAGE_SUFFIXES & convert.OFFICE_SUFFIXES)


def test_text_suffixes_never_overlap_image_or_office():
    assert not (convert.TEXT_SUFFIXES & convert.IMAGE_SUFFIXES)
    assert not (convert.TEXT_SUFFIXES & convert.OFFICE_SUFFIXES)


# ---------------------------------------------------------------------------
# convert_image_to_pdf
# ---------------------------------------------------------------------------


def test_a_single_image_becomes_a_one_page_pdf(tmp_path):
    src = tmp_path / "scan.png"
    Image.new("RGB", (850, 1100), (255, 255, 255)).save(src)

    out_path = convert.convert_image_to_pdf(str(src))

    with pdfplumber.open(out_path) as doc:
        assert len(doc.pages) == 1
        page = doc.pages[0]
        # No text layer at all - this is exactly the signal
        # `extract.normalize.NATIVE_CHAR_THRESHOLD` already uses to route a
        # page to OCR, so nothing downstream needed to change.
        assert (page.extract_text() or "") == ""
        assert len(page.images) == 1


def test_a_multi_frame_tiff_becomes_a_multi_page_pdf_in_order(tmp_path):
    src = tmp_path / "fax.tiff"
    frames = [Image.new("RGB", (850, 1100), (255, 255, 255)) for _ in range(3)]
    frames[0].save(src, save_all=True, append_images=frames[1:])

    out_path = convert.convert_image_to_pdf(str(src))

    with pdfplumber.open(out_path) as doc:
        assert len(doc.pages) == 3


def test_a_palette_image_converts_cleanly():
    """PDF only accepts RGB/L frames - a P-mode (palette) or RGBA image must
    be converted first, or Pillow's own PDF writer rejects it outright."""
    import tempfile

    src_path = tempfile.mktemp(suffix=".png")
    Image.new("P", (100, 100)).save(src_path)

    out_path = convert.convert_image_to_pdf(src_path)

    with pdfplumber.open(out_path) as doc:
        assert len(doc.pages) == 1


def test_a_corrupted_image_fails_as_a_permanent_error(tmp_path):
    src = tmp_path / "not_really.png"
    src.write_bytes(b"this is not image data")

    with pytest.raises(PermanentError, match="could not open"):
        convert.convert_image_to_pdf(str(src))


def test_an_image_with_no_readable_frames_is_a_permanent_error(tmp_path, monkeypatch):
    """Defensive: if Pillow ever opens a file but yields zero frames, that must
    fail loudly rather than silently produce an empty PDF."""
    from PIL import ImageSequence

    src = tmp_path / "scan.png"
    Image.new("RGB", (10, 10)).save(src)
    monkeypatch.setattr(ImageSequence, "Iterator", lambda img: iter(()))

    with pytest.raises(PermanentError, match="no readable image frames"):
        convert.convert_image_to_pdf(str(src))


# ---------------------------------------------------------------------------
# convert_office_to_pdf - subprocess mocked; no real `soffice` needed to
# exercise every branch except the happy path, which is separately gated.
# ---------------------------------------------------------------------------


class _FakeCompleted:
    def __init__(self, returncode: int, stderr: bytes = b"") -> None:
        self.returncode = returncode
        self.stderr = stderr


def test_a_successful_conversion_returns_the_output_path(tmp_path, monkeypatch):
    src = tmp_path / "invoice.docx"
    src.write_bytes(b"not a real docx, subprocess is mocked")

    written_path = {}

    def fake_run(args, capture_output, timeout, check):
        # soffice writes `<outdir>/<stem>.pdf` - simulate that side effect so
        # the real "does the output file exist" check still exercises.
        out_dir = args[args.index("--outdir") + 1]
        import os

        out_path = os.path.join(out_dir, "invoice.pdf")
        with open(out_path, "wb") as fh:
            fh.write(b"%PDF-1.4 fake")
        written_path["path"] = out_path
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    out_path = convert.convert_office_to_pdf(str(src))

    assert out_path == written_path["path"]


def test_a_nonzero_exit_is_a_permanent_error(tmp_path, monkeypatch):
    src = tmp_path / "invoice.docx"
    src.write_bytes(b"x")
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: _FakeCompleted(returncode=1, stderr=b"soffice: unrecoverable error"),
    )

    with pytest.raises(PermanentError, match="unrecoverable error"):
        convert.convert_office_to_pdf(str(src))


def test_exit_zero_but_no_output_file_is_still_a_permanent_error(tmp_path, monkeypatch):
    """soffice can exit 0 without producing anything on certain malformed
    inputs - the presence of the output file is the real signal, not the
    exit code alone."""
    src = tmp_path / "invoice.xlsx"
    src.write_bytes(b"x")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _FakeCompleted(returncode=0))

    with pytest.raises(PermanentError, match="no output produced"):
        convert.convert_office_to_pdf(str(src))


def test_a_timeout_is_transient_not_permanent(tmp_path, monkeypatch):
    """Worth one retry - a starved CI runner is plausible, unlike a
    malformed document, which will not convert faster on a second try."""
    src = tmp_path / "invoice.docx"
    src.write_bytes(b"x")

    def raise_timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="soffice", timeout=60)

    monkeypatch.setattr(subprocess, "run", raise_timeout)

    with pytest.raises(TransientError, match="timed out"):
        convert.convert_office_to_pdf(str(src))


def test_a_missing_soffice_binary_is_a_clear_permanent_error(tmp_path, monkeypatch):
    """Not a per-document problem - the host has no LibreOffice installed.
    Still a PermanentError (not a crash): every Office document dead-letters
    with an actionable reason until someone installs it."""
    src = tmp_path / "invoice.docx"
    src.write_bytes(b"x")

    def raise_not_found(*a, **kw):
        raise FileNotFoundError("soffice")

    monkeypatch.setattr(subprocess, "run", raise_not_found)

    with pytest.raises(PermanentError, match="not installed"):
        convert.convert_office_to_pdf(str(src))


def test_each_call_gets_its_own_profile_directory(tmp_path, monkeypatch):
    """Concurrent `soffice` invocations sharing the default profile lock or
    corrupt each other - a fresh `-env:UserInstallation` per call is not
    optional, so pin that the argument is actually present and unique."""
    src = tmp_path / "invoice.docx"
    src.write_bytes(b"x")
    seen_profiles: list[str] = []

    def fake_run(args, capture_output, timeout, check):
        profile_arg = next(a for a in args if a.startswith("-env:UserInstallation="))
        seen_profiles.append(profile_arg)
        out_dir = args[args.index("--outdir") + 1]
        import os

        with open(os.path.join(out_dir, "invoice.pdf"), "wb") as fh:
            fh.write(b"%PDF-1.4 fake")
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    convert.convert_office_to_pdf(str(src))
    convert.convert_office_to_pdf(str(src))

    assert len(seen_profiles) == 2
    assert seen_profiles[0] != seen_profiles[1]


def test_the_throwaway_profile_directory_is_removed_after_a_successful_conversion(
    tmp_path, monkeypatch
):
    """`profile_dir` is fully consumed the instant `soffice` returns - unlike
    the output directory (which the caller still needs to read the converted
    PDF from), nothing ever reads it again, so it must never linger on disk
    for the life of the process."""
    import os

    src = tmp_path / "invoice.docx"
    src.write_bytes(b"x")
    seen_profile_dirs: list[str] = []

    from urllib.parse import urlparse
    from urllib.request import url2pathname

    def fake_run(args, capture_output, timeout, check):
        profile_arg = next(a for a in args if a.startswith("-env:UserInstallation="))
        seen_profile_dirs.append(url2pathname(urlparse(profile_arg.split("=", 1)[1]).path))
        out_dir = args[args.index("--outdir") + 1]
        with open(os.path.join(out_dir, "invoice.pdf"), "wb") as fh:
            fh.write(b"%PDF-1.4 fake")
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    convert.convert_office_to_pdf(str(src))

    assert not os.path.isdir(seen_profile_dirs[0])


def test_the_throwaway_profile_directory_is_removed_even_when_conversion_fails(
    tmp_path, monkeypatch
):
    """The profile directory must not leak on the failure paths either - a
    permanently-failing document must not accumulate one orphaned directory
    per attempt."""
    import os
    from urllib.parse import urlparse
    from urllib.request import url2pathname

    src = tmp_path / "invoice.docx"
    src.write_bytes(b"x")
    seen_profile_dirs: list[str] = []

    def fake_run(args, capture_output, timeout, check):
        profile_arg = next(a for a in args if a.startswith("-env:UserInstallation="))
        seen_profile_dirs.append(url2pathname(urlparse(profile_arg.split("=", 1)[1]).path))
        return _FakeCompleted(returncode=1, stderr=b"boom")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(PermanentError):
        convert.convert_office_to_pdf(str(src))

    assert not os.path.isdir(seen_profile_dirs[0])


def test_the_output_directory_is_left_in_place_for_the_caller_to_read(tmp_path, monkeypatch):
    """Unlike the throwaway profile directory, the converted PDF's own
    directory must still exist when this function returns - the caller (and,
    later, Stage 5b's vision call) still needs to read the file from it."""
    import os

    src = tmp_path / "invoice.docx"
    src.write_bytes(b"x")

    def fake_run(args, capture_output, timeout, check):
        out_dir = args[args.index("--outdir") + 1]
        with open(os.path.join(out_dir, "invoice.pdf"), "wb") as fh:
            fh.write(b"%PDF-1.4 fake")
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    out_path = convert.convert_office_to_pdf(str(src))

    assert os.path.isfile(out_path)


# ---------------------------------------------------------------------------
# the one test that needs a real LibreOffice install - skips cleanly without it
# ---------------------------------------------------------------------------


def _soffice_available() -> bool:
    import shutil

    return shutil.which("soffice") is not None


def _minimal_docx(path, body_text: str) -> None:
    """A hand-built, dependency-free DOCX - just enough XML for Word/
    LibreOffice to open it. Avoids adding python-docx as a test-only
    dependency for the one test that needs a real source file."""
    import zipfile

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
        'relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{body_text}</w:t></w:r></w:p></w:body>"
        "</w:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("word/document.xml", document_xml)


@pytest.mark.skipif(not _soffice_available(), reason="LibreOffice ('soffice') is not installed")
def test_a_real_docx_converts_to_a_readable_pdf(tmp_path):
    """The one end-to-end proof that needs the real binary - everything above
    proves the wrapper's error handling without it. Skips cleanly rather than
    failing on a machine that hasn't installed LibreOffice, the same
    discipline `--vision live`/`--vision record` already uses for a missing
    API key."""
    src = tmp_path / "invoice.docx"
    _minimal_docx(src, "Real invoice text for a real conversion.")

    out_path = convert.convert_office_to_pdf(str(src))

    with pdfplumber.open(out_path) as pdf:
        assert len(pdf.pages) >= 1
        assert "Real invoice text" in (pdf.pages[0].extract_text() or "")
