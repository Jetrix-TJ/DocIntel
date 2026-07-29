from docintel.core.duplicates import IdentityIndex


def test_the_first_sighting_of_an_identity_is_not_a_duplicate() -> None:
    assert IdentityIndex().see("doc-1", "northstar|veritiv|715-33905296") is None


def test_a_second_sighting_names_the_first_document() -> None:
    idx = IdentityIndex()
    idx.see("doc-1", "northstar|veritiv|715-33905296")
    assert idx.see("doc-2", "northstar|veritiv|715-33905296") == "doc-1"


def test_an_unidentifiable_document_is_never_called_a_duplicate() -> None:
    """`document_identity` is None when nothing on the page identified it.

    Two unidentifiable documents are not evidence of the same document twice,
    and saying so would be worse than saying nothing.
    """
    idx = IdentityIndex()
    assert idx.see("doc-1", None) is None
    assert idx.see("doc-2", None) is None


def test_the_same_document_id_twice_is_a_replay_not_a_duplicate() -> None:
    """Re-processing one document must not accuse it of duplicating itself."""
    idx = IdentityIndex()
    idx.see("doc-1", "x")
    assert idx.see("doc-1", "x") is None
