import glob

from docintel.extract.annotations import detect_flattened
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
        assert flagged == (path == FEDERAL), f"unexpected result for {path}"


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
