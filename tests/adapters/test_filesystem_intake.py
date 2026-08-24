import os

from docintel.adapters.intake.filesystem import FilesystemIntake

CORPUS = "docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf"


def test_ids_are_stable_across_runs():
    """Spec Stage 1: a crashed listener re-reading yields the same id, not a duplicate."""
    a = list(FilesystemIntake([CORPUS]).items())
    b = list(FilesystemIntake([CORPUS]).items())
    assert [i.document_id for i in a] == [i.document_id for i in b]


def test_ids_differ_between_documents():
    items = list(FilesystemIntake([
        CORPUS,
        "docs/EDCO 77087APR25 current charges can be misleading, paying $69.62.pdf",
    ]).items())
    assert len({i.document_id for i in items}) == 2


def test_a_directory_named_like_a_pdf_is_not_mistaken_for_a_document(tmp_path):
    """os.walk separates directories from files, so `archive.pdf/` is walked into."""
    fake_dir = tmp_path / "archive.pdf"
    fake_dir.mkdir()
    (fake_dir / "real.pdf").write_bytes(b"%PDF-1.4 stub")
    items = list(FilesystemIntake([str(tmp_path)]).items())
    paths = [i.source_path for i in items]
    assert str(fake_dir) not in paths, "a directory must never be yielded as a document"
    assert str(fake_dir / "real.pdf") in paths, "the PDF inside it must be found"


def test_nested_pdfs_are_found_not_silently_ignored(tmp_path):
    """Spec Stage 1: nothing is discarded at intake.

    A flat listing leaves a PDF one directory down invisible — not skipped, not
    dead-lettered, not even counted. That is the one failure mode this design
    refuses, so intake recurses.
    """
    (tmp_path / "top.pdf").write_bytes(b"%PDF-1.4")
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    (deep / "buried.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "ignore.pptx").write_text("not a pdf")  # .pptx: still unaccepted

    found = {os.path.basename(i.source_path) for i in FilesystemIntake([str(tmp_path)]).items()}
    assert found == {"top.pdf", "buried.pdf"}


def test_traversal_order_is_deterministic(tmp_path):
    for name in ("c.pdf", "a.pdf", "b.pdf"):
        (tmp_path / name).write_bytes(b"%PDF-1.4")
    first = [i.source_path for i in FilesystemIntake([str(tmp_path)]).items()]
    second = [i.source_path for i in FilesystemIntake([str(tmp_path)]).items()]
    assert first == second == sorted(first)


def test_directory_expands_to_its_pdfs(tmp_path):
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        (tmp_path / name).write_bytes(b"%PDF-1.4")
    (tmp_path / "not-a-pdf.pptx").write_text("ignore me")  # .pptx: still unaccepted
    items = list(FilesystemIntake([str(tmp_path)]).items())
    assert len(items) == 3


def test_a_directory_walk_now_also_finds_images_and_office_documents(tmp_path):
    """`_walk` used to hardcode `.pdf` a second time, independent of Stage
    2's own allowlist - the two could drift. Both now read
    `convert.ACCEPTED_SUFFIXES`, so a scan/Office document one directory
    down is no longer invisible before Stage 2 ever runs."""
    for name in ("a.pdf", "b.png", "c.docx", "d.xlsx", "e.jpg", "f.tiff"):
        (tmp_path / name).write_bytes(b"stub bytes")
    (tmp_path / "ignore.pptx").write_text("still not accepted")  # .pptx: still unaccepted

    found = {os.path.basename(i.source_path) for i in FilesystemIntake([str(tmp_path)]).items()}
    assert found == {"a.pdf", "b.png", "c.docx", "d.xlsx", "e.jpg", "f.tiff"}


def test_a_directory_walk_now_also_finds_text_documents(tmp_path):
    """Phase 4: TXT/CSV/HTML are also read straight from `ACCEPTED_SUFFIXES`,
    with zero changes to this module - the same "defined once" seam that
    already covered images/Office documents."""
    for name in ("a.txt", "b.csv", "c.html", "d.htm"):
        (tmp_path / name).write_text("stub content")
    (tmp_path / "ignore.pptx").write_text("still not accepted")

    found = {os.path.basename(i.source_path) for i in FilesystemIntake([str(tmp_path)]).items()}
    assert found == {"a.txt", "b.csv", "c.html", "d.htm"}
