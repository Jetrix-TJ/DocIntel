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
    def __init__(self) -> None:
        self._first: dict[str, str] = {}

    def see(self, document_id: str, identity: str | None) -> str | None:
        """The document_id first seen with `identity`, or None.

        None for an unidentifiable document: two documents nothing could
        identify are not evidence of one document twice.
        """
        if identity is None:
            return None
        first = self._first.setdefault(identity, document_id)
        return None if first == document_id else first
