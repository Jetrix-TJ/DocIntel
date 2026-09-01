import glob
import os
import threading
import unittest.mock

import pdfplumber
from PIL import Image, ImageDraw

from docintel.extract import annotations as annotations_module
from docintel.extract.annotations import RESOLUTION, detect_flattened, detect_flattened_image
from docintel.extract.normalize import load_document

FEDERAL = "docs/CONTRA ONLY Everything already on AR Federal Recycling 1330123.pdf"
CLEAN = "docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf"


def test_federal_recycling_flattened_annotations_are_detected():
    """F3: annots==0 because the overlays were flattened into the page image."""
    pages, meta, _ = load_document(FEDERAL)
    assert meta[0].annot_count == 0  # no annotation layer to strip
    assert detect_flattened(FEDERAL, pages, meta) is True


def test_clean_document_is_not_flagged():
    pages, meta, _ = load_document(CLEAN)
    assert detect_flattened(CLEAN, pages, meta) is False


def test_only_federal_recycling_is_flagged_across_the_whole_corpus():
    """The other nine documents include two more OCR-only, zero-annot-layer
    pages (Complete Beverage Destruction) and several brand-colour-heavy
    native PDFs (Comcast, Windstream, EDCO) - none of them may trip the
    detector, or every one of them earns a needless forced review (F3).
    """
    for path in sorted(glob.glob("docs/*.pdf")):
        pages, meta, _ = load_document(path)
        flagged = detect_flattened(path, pages, meta)
        assert flagged == (path.replace(os.sep, "/") == FEDERAL), f"unexpected result for {path}"


def test_detection_is_memoized_and_does_not_mutate_shared_state():
    """detect_flattened re-renders pages from disk on a miss; the corpus'
    fault-injection matrix reprocesses the same document hundreds of times
    within one process, so a repeat call for the same file must be cheap and
    must never depend on, or corrupt, anything `load_document` cached.
    """
    pages, meta, _ = load_document(FEDERAL)
    first = detect_flattened(FEDERAL, pages, meta)
    second = detect_flattened(FEDERAL, pages, meta)
    assert first is second is True


def test_pdfium_render_lock_serializes_concurrent_calls():
    """Proves the lock is actually acquired around the pdfium-touching call:
    patches the REAL pdfplumber Page.to_image (not an invented fake page —
    this file has no such fixture) to detect re-entrancy while "rendering".

    `detect_flattened` is memoized (`functools.lru_cache`, see
    `annotations.py`), so a cache hit would skip `to_image` entirely and make
    this test vacuous. Guard against that explicitly with a call counter,
    not just the in-flight list, per the task brief's instruction — a
    fixture already cached (e.g. because another test in this file ran
    first, in the same process) must not silently turn this into a no-op.

    Note: a bare `threading.Thread` swallows an `AssertionError` raised
    inside its target — `Thread.join()` does not re-raise it, pytest only
    logs a `PytestUnhandledThreadExceptionWarning`, and the test itself
    still reports PASSED. Confirmed by running this against the pre-fix
    code with the naive "just start/join" version: it printed the exact
    re-entrancy AssertionError to the warnings summary yet pytest still said
    "1 passed". Threads therefore report failures into a shared list that
    the main thread inspects after joining, so a re-entrancy violation
    actually fails the test.
    """
    import pdfplumber.page

    calls_in_flight = []
    call_count = 0
    original_to_image = pdfplumber.page.Page.to_image

    def tracking_to_image(self, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        calls_in_flight.append(1)
        assert len(calls_in_flight) == 1, "two calls entered the pdfium region concurrently"
        try:
            return original_to_image(self, *args, **kwargs)
        finally:
            calls_in_flight.pop()

    errors: list[BaseException] = []

    def run_detect_flattened(pages, meta):
        try:
            detect_flattened(CLEAN, pages, meta)
        except BaseException as exc:  # noqa: BLE001 - propagate any thread failure to the main thread
            errors.append(exc)

    with unittest.mock.patch.object(pdfplumber.page.Page, "to_image", tracking_to_image):
        pages, meta, _ = load_document(CLEAN)
        threads = [threading.Thread(target=run_detect_flattened, args=(pages, meta)) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert not errors, f"{len(errors)} thread(s) raised: {errors[0]!r}"
    assert call_count >= 1, (
        "tracking_to_image was never called - detect_flattened(CLEAN, ...) must have hit the "
        "memoization cache (populated by an earlier test in this process) rather than actually "
        "rendering, so this run proves nothing about the lock; run in isolation "
        "(pytest ... -k pdfium_render_lock) to get a real, uncached exercise of the lock."
    )


def test_concurrent_detection_on_real_fixtures_produces_correct_results_under_load():
    """A softer regression guard using this file's own real fixtures: many
    threads calling detect_flattened concurrently must all still return the
    correct, already-established answer (see test_clean_document_is_not_flagged
    and test_federal_recycling_flattened_annotations_are_detected above) - not
    a segfault, not a wrong result from interleaved native state."""
    federal_pages, federal_meta, _ = load_document(FEDERAL)
    clean_pages, clean_meta, _ = load_document(CLEAN)
    results = []

    def check_federal():
        results.append(("federal", detect_flattened(FEDERAL, federal_pages, federal_meta)))

    def check_clean():
        results.append(("clean", detect_flattened(CLEAN, clean_pages, clean_meta)))

    threads = [threading.Thread(target=check_federal if i % 2 == 0 else check_clean) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for name, result in results:
        assert result == (name == "federal")


def test_greyscale_annotations_are_a_known_blind_spot_not_detected():
    """Pins Finding 3's documented limitation: detection is entirely
    saturation-dependent, so a greyscale scan or black/grey-pen annotation
    is invisible to it. This is EXPECTED, not desired, behaviour - a
    regression test for a known gap, not a spec for correct output.

    Uses Federal Recycling's own page, the one real annotated page in the
    corpus, desaturated to grey. Same annotation geometry, same coverage,
    same spread across the page that `test_federal_recycling_flattened_
    annotations_are_detected` above confirms IS caught in colour - only the
    saturation is gone. If this test ever starts failing (i.e. detection
    starts returning True here), that is not a bug fix to celebrate
    silently: it means the blind spot documented in the module docstring
    has narrowed, and the docstring must be updated to match, or the
    detector has started keying off something other than saturation and
    the corpus-evidence thresholds need re-validating from scratch.
    """
    with pdfplumber.open(FEDERAL) as doc:
        colour_img = doc.pages[0].to_image(resolution=RESOLUTION).original.convert("RGB")

    # Sanity check: the colour version of this exact image IS detected -
    # otherwise this test would be pinning nothing.
    assert annotations_module._image_is_annotated(colour_img) is True  # noqa: SLF001

    grey_img = colour_img.convert("L").convert("RGB")
    assert annotations_module._image_is_annotated(grey_img) is False  # noqa: SLF001


def test_zebra_striped_delivery_table_is_not_flagged_as_annotated() -> None:
    """Real DTSS bug: DTSS's real second-sample document `_AP Invoice
    6081DTSS D.T.S.S. Inc. 36000.00000.pdf` page 2 is a computer-generated
    delivery table with a solid pastel-blue header bar and a pastel-blue
    shaded "Delivery ID" column running the full height of the table -
    measured at `hit_frac=0.0933` (threshold 0.03) and `hit_cells=280`
    (threshold 50) at this module's `RESOLUTION`, i.e. it clears *both*
    existing thresholds with more margin than Federal Recycling's own true
    positive does (`hit_frac=0.0445`, `hit_cells=193`) - so tightening either
    threshold cannot separate this page from the true positive; only a
    shape/contiguity check can. Reusing this file's controlled-saturation
    image-construction approach (see `test_greyscale_annotations_are_a_
    known_blind_spot_not_detected` above), this fixture paints a same-size
    (850x1100, this module's `RESOLUTION` for a US-Letter page) synthetic
    page with the same two rectangles in the same measured HSV band
    (S=47, V=216, i.e. within [SAT_MIN, SAT_MAX] at >=VALUE_MIN) and neutral
    (S=0) grey everywhere else, reproducing the real page's single dominant,
    tall, contiguous connected component (one printed table column/header,
    not six scattered highlighter strokes) that `_image_is_annotated` must
    not mistake for flattened human markup.
    """
    band_colour = (176, 192, 216)  # HSV S=47, V=216 - sampled from the real DTSS page
    background = (248, 248, 248)  # HSV S=0 - neutral page background, outside the band
    img = Image.new("RGB", (850, 1100), background)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 42, 701, 84], fill=band_colour)  # full-width header bar
    draw.rectangle([64, 85, 170, 994], fill=band_colour)  # shaded ID column, full table height

    assert annotations_module._image_is_annotated(img) is False  # noqa: SLF001


# -- detect_flattened_image: the raw-image counterpart, no PDF involved -----


def _scattered_highlight_image(tmp_path, name: str = "annotated.png"):
    """A synthetic raster reproducing Federal Recycling's real shape: several
    small, separate pastel-band blobs scattered down the page, not one
    contiguous printed band - see the module docstring's Federal Recycling
    vs. DTSS contrast."""
    band_colour = (176, 192, 216)  # same measured HSV band as the tests above
    background = (248, 248, 248)
    img = Image.new("RGB", (850, 1100), background)
    draw = ImageDraw.Draw(img)
    # Six small, widely separated blocks, mirroring "six independent
    # highlighter strokes and comment boxes scattered down the page".
    for top in (60, 220, 380, 540, 700, 860):
        draw.rectangle([80, top, 260, top + 40], fill=band_colour)
    path = tmp_path / name
    img.save(path)
    return path


def test_detect_flattened_image_catches_scattered_annotations_on_a_raw_raster(tmp_path):
    path = _scattered_highlight_image(tmp_path)
    assert detect_flattened_image(str(path)) is True


def test_detect_flattened_image_does_not_flag_a_clean_raster(tmp_path):
    img = Image.new("RGB", (850, 1100), (248, 248, 248))
    path = tmp_path / "clean.png"
    img.save(path)
    assert detect_flattened_image(str(path)) is False


def test_detect_flattened_image_examines_every_frame_of_a_multi_frame_tiff(tmp_path):
    """A multi-frame TIFF (a multi-page scan) must be flagged if ANY frame
    carries flattened annotations, not only the first - mirroring
    `convert.convert_image_to_pdf`'s own "every frame, in order" handling."""
    clean = Image.new("RGB", (850, 1100), (248, 248, 248))
    band_colour = (176, 192, 216)
    annotated = Image.new("RGB", (850, 1100), (248, 248, 248))
    draw = ImageDraw.Draw(annotated)
    for top in (60, 220, 380, 540, 700, 860):
        draw.rectangle([80, top, 260, top + 40], fill=band_colour)

    path = tmp_path / "multi.tiff"
    clean.save(path, save_all=True, append_images=[clean, annotated])

    assert detect_flattened_image(str(path)) is True


def test_detect_flattened_image_is_memoized_and_does_not_mutate_shared_state(tmp_path):
    path = _scattered_highlight_image(tmp_path)
    first = detect_flattened_image(str(path))
    second = detect_flattened_image(str(path))
    assert first is second is True
