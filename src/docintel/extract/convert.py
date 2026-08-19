"""Turn a non-PDF input into a real, `pdfplumber`-readable PDF, at the intake
boundary, so that everything downstream of Stage 2 (`pdf.py`, `ocr.py`, the
whole grammar/persona/region system) runs completely unmodified regardless of
what format actually arrived.

Two entry points, one per format class, because the two classes have
genuinely different failure modes and genuinely different dependency shapes:

- `convert_image_to_pdf` — a raster image has no text layer at all, so
  wrapping it as a single-page (or multi-page, for a multi-frame TIFF) PDF is
  enough: the wrapped PDF reads back with `char_count == 0` on every page,
  which is exactly the existing signal `extract.normalize.NATIVE_CHAR_
  THRESHOLD` already uses to route a page to OCR. Pillow only - already a
  direct dependency, so this needs no new install.
- `convert_office_to_pdf` — a DOCX/XLSX has real text and real (if
  flow-laid-out) structure, and the honest way to give it real PDF-page
  geometry is to actually lay it out, which means an actual renderer.
  LibreOffice headless is that renderer, wrapped the same way `ocr.py` already
  wraps `pytesseract`: a thin Python layer around an external binary, with the
  right error class raised for each real failure mode. Synthesizing word
  coordinates from python-docx paragraphs or openpyxl cells instead was
  considered and rejected - `grammar.regions`'s selectors are calibrated
  against MEASURED geometry from real rendered pages, and a flow-layout
  format has no honest analogue to invent that from.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from docintel.core.errors import PermanentError, TransientError

# Formats Pillow reads natively. HEIC needs the `pillow-heif` plugin - a real
# extra dependency for a format that's rare outside iPhone photos - so it is
# deliberately not in this list; add it as its own follow-up if it's needed.
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif"})

# DOCX/XLSX only for now. PPTX/ODT would go through the identical soffice
# call, but nobody has asked for them - adding a suffix here is a one-line
# change once they are.
OFFICE_SUFFIXES = frozenset({".docx", ".xlsx"})

# Every suffix Stage 2 will accept, PDF included. The single source of truth
# for both `s2_filter.ALLOWED_SUFFIXES` and `FilesystemIntake._walk`'s own
# directory-scan filter - defined once, here, so the two cannot drift the way
# they would if each independently unioned `IMAGE_SUFFIXES`/`OFFICE_SUFFIXES`
# with ".pdf" itself.
ACCEPTED_SUFFIXES = frozenset({".pdf"}) | IMAGE_SUFFIXES | OFFICE_SUFFIXES

# soffice can take a while to cold-start its own process, and a hung
# conversion must not hang a whole pipeline run. Worth one retry
# (`TransientError`) on timeout, since a starved CI runner is plausible; a
# malformed document will not convert faster on a second attempt, which is
# why every OTHER failure below is `PermanentError`.
_CONVERT_TIMEOUT_SECONDS = 60


def convert_image_to_pdf(source_path: str) -> str:
    """Wrap one raster image (or every frame of a multi-frame TIFF/GIF, in
    order) as a PDF, and return the new file's path.

    Raises `PermanentError` for anything Pillow cannot open or cannot save -
    a truncated download, a file with an image-looking suffix that is not
    actually an image - never lets a `PIL` exception surface raw, since the
    caller (Stage 2) needs one of this project's own error classes to decide
    dead-letter vs. retry.
    """
    from PIL import Image, ImageSequence

    try:
        img = Image.open(source_path)
        img.load()
    except Exception as exc:
        raise PermanentError(
            f"could not open {os.path.basename(source_path)!r} as an image: {exc}"
        ) from exc

    # PDF only accepts RGB/L (greyscale) frames - a palette (P) or RGBA image
    # must be converted first, or Pillow's own PDF plugin rejects it.
    frames = [
        frame.convert("RGB") if frame.mode not in ("RGB", "L") else frame.copy()
        for frame in ImageSequence.Iterator(img)
    ]
    if not frames:
        raise PermanentError(f"{os.path.basename(source_path)!r} has no readable image frames")

    out_dir = tempfile.mkdtemp(prefix="docintel-imgpdf-")
    out_path = os.path.join(out_dir, "converted.pdf")
    try:
        frames[0].save(out_path, "PDF", save_all=True, append_images=frames[1:])
    except Exception as exc:
        raise PermanentError(
            f"could not convert {os.path.basename(source_path)!r} to PDF: {exc}"
        ) from exc
    return out_path


def convert_office_to_pdf(source_path: str) -> str:
    """Render one Office document (DOCX/XLSX) to PDF via LibreOffice headless,
    and return the new file's path.

    Every call gets its OWN `-env:UserInstallation` profile directory -
    concurrent `soffice` invocations sharing the default profile lock (or
    silently corrupt) each other, which is not a hypothetical: it is
    `soffice`'s documented behaviour under concurrent headless use. Passing a
    fresh, throwaway profile per call is the standard workaround, not a
    defensive extra.
    """
    out_dir = tempfile.mkdtemp(prefix="docintel-officepdf-")
    profile_dir = tempfile.mkdtemp(prefix="docintel-sofficeprofile-")
    profile_uri = Path(profile_dir).as_uri()

    try:
        result = subprocess.run(
            [
                "soffice", "--headless", "--norestore",
                "--convert-to", "pdf", "--outdir", out_dir,
                f"-env:UserInstallation={profile_uri}",
                source_path,
            ],
            capture_output=True,
            timeout=_CONVERT_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        # Not a per-document failure - the host has no LibreOffice installed.
        # Still a PermanentError, not a crash: every document of this format
        # dead-letters with a clear, actionable reason until someone installs
        # it, rather than taking the whole run down.
        raise PermanentError(
            "LibreOffice ('soffice') is not installed or not on PATH - required "
            "to convert Office documents to PDF"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise TransientError(
            f"converting {os.path.basename(source_path)!r} to PDF timed out after "
            f"{_CONVERT_TIMEOUT_SECONDS}s"
        ) from exc

    stem = Path(source_path).stem
    out_path = os.path.join(out_dir, f"{stem}.pdf")
    if result.returncode != 0 or not os.path.isfile(out_path):
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise PermanentError(
            f"soffice could not convert {os.path.basename(source_path)!r} to PDF "
            f"(exit {result.returncode}): {stderr or '(no output produced)'}"
        )
    return out_path
