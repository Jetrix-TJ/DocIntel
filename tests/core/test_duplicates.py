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


def test_peek_reports_the_first_sighting_without_mutating() -> None:
    """`_emit` needs to read the answer before deciding whether it should
    stick (see the module docstring) - `peek` alone must never register a
    document, however many times it is called."""
    idx = IdentityIndex()
    idx.commit("doc-1", "x")
    assert idx.peek("doc-2", "x") == "doc-1"
    assert idx.peek("doc-2", "x") == "doc-1"
    assert idx.peek("doc-3", "y") is None


def test_peek_excludes_a_replay_of_the_first_sighting_itself() -> None:
    """Round-2 review regression: `peek` used to take only `identity`, so it
    could not tell "the document on file is THIS one" from "a different
    document with the same identity" - `_emit`, which calls `peek` and never
    `see`, told a replayed document it duplicated itself. `peek` now takes
    `document_id` and excludes it, the same way `see` always has.
    """
    idx = IdentityIndex()
    idx.commit("doc-1", "x")
    assert idx.peek("doc-1", "x") is None


def test_commit_is_a_no_op_for_an_unidentifiable_document() -> None:
    idx = IdentityIndex()
    idx.commit("doc-1", None)
    assert idx.peek("doc-2", "x") is None


def test_a_peeked_but_never_committed_identity_is_still_unclaimed() -> None:
    """The exact bug the peek/commit split exists to prevent: reading the
    answer must not, by itself, reserve the slot for a document whose own
    record never ends up carrying that identity."""
    idx = IdentityIndex()
    assert idx.peek("doc-1", "x") is None  # doc-1 looks up the slot...
    # ...but doc-1's emit fails downstream and is never committed.
    assert idx.see("doc-2", "x") is None, "doc-2 must be free to claim it"
