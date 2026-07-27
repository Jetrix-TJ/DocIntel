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


def test_directory_expands_to_its_pdfs():
    items = list(FilesystemIntake(["docs"]).items())
    assert len(items) == 10
