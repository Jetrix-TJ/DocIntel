"""Within-run duplicate detection, keyed on `derived.document_identity`.

`possible_duplicate_of` has been in the output contract since C2b, type-checked
by `validate_record`, and never assigned - so every record has reported "no
duplicate" whether or not anything looked. A permanently-null field is worse
than an absent one: it reads as a completed check.

Scope is deliberately ONE RUN. A cross-run index needs the persona store's
database (cluster C7) and a retention policy nobody has decided; claiming
cross-run coverage from an in-memory dict would be the same false completeness
this module exists to remove.
"""

from __future__ import annotations


class IdentityIndex:
    """`peek` and `commit` are split apart so a caller can decide the answer
    before deciding whether the sighting should stick.

    That split exists because of a review finding on this module's first
    version: `Runner._emit` used to call a single mutating `see()` before
    `build_record`/`validate_record` ran. If those then raised, the document's
    own record was rebuilt from a fresh, empty context
    (`Runner._minimal_dead_letter`) that carries no trace of the identity or
    the claim just made - but the mutation had already happened, so a LATER
    document could still be told "duplicate of that one" and point a reviewer
    at a record with no corroborating evidence at all. `peek` lets `_emit`
    read the answer to put in the candidate record; `commit` is called only
    once that record is proven buildable and valid, so a document can never
    irrevocably claim an identity slot its own shipped record does not back.

    `peek` takes `document_id` for the same reason `commit` does: a replay of
    one document under its own id must never read as a duplicate of itself.
    An earlier version gave `peek` only `identity`, which could not tell "the
    document on file is THIS one" from "a different document with the same
    identity" - `_emit`, which calls `peek` and never a fused call, told a
    replayed document it duplicated itself.

    There is no `see()` combining `peek` and `commit` in one call: `_emit` is
    this class's only production caller and always needs them split, so a
    fused convenience method would carry no caller and only invite a future
    one to reintroduce the exact bug the split fixed. `tests/core/test_
    duplicates.py` composes `peek` + `commit` directly (a private test-only
    helper) where earlier versions called `see`.

    `_first` grows by one entry per distinct `document_identity` seen and is
    never evicted, for the run's lifetime (`_cmd_process` builds one `Runner`,
    and so one `IdentityIndex`, per batch). That is deliberate, not an
    oversight: evicting an entry to bound memory would mean a document late
    in a large batch silently stops being checked against an identity seen
    early in the same batch - missing a duplicate is the exact failure this
    module exists to remove, so there is no size at which "cheaper" is worth
    it. Contrast `extract.normalize`'s `_load_document_cached` memo, which
    IS bounded (`_MEMO_CACHE_SIZE = 64`): a stale eviction there is merely a
    cache miss - the next call just re-parses the PDF - so bounding it costs
    nothing but a little repeated work. There is no equivalent "just redo it"
    fallback for a dropped identity entry; the duplicate it would have caught
    is gone.
    """

    def __init__(self) -> None:
        self._first: dict[str, str] = {}

    def peek(self, document_id: str, identity: str | None) -> str | None:
        """The document_id first seen with `identity`, or None.

        Never mutates. None for an unidentifiable document (two documents
        nothing could identify are not evidence of one document twice) and
        None when `document_id` itself is the first sighting on record (a
        replay is not a duplicate of itself).
        """
        if identity is None:
            return None
        first = self._first.get(identity)
        if first is None or first == document_id:
            return None
        return first

    def commit(self, document_id: str, identity: str | None) -> None:
        """Register `document_id` as the first sighting of `identity`.

        A no-op for an unidentifiable document, and a no-op if some other
        document already holds this identity's slot - the FIRST sighting
        wins, permanently.
        """
        if identity is None:
            return
        self._first.setdefault(identity, document_id)
