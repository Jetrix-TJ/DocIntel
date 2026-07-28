"""A persona store backed by the packs' shipped JSON.

This is the read half of Stage 4. The write half - an agent authoring a new
persona into SQLite - is C7; the lookup contract is the same either way, which is
what makes the seam honest rather than a placeholder.

Personas are keyed by `(sender_fingerprint, doc_type)`. A pack ships a persona per
vendor, and the vendor's canonical key is what the `beforePersonaLookup` hook
computes from page text - so the key a persona declares and the key Stage 4 looks
up are the same string by construction, not by convention.
"""

from __future__ import annotations

from typing import Any

from docintel.grammar.schema import Persona, parse_persona
from docintel.packs.registry import Pack, load_packs


class PackPersonaStore:
    """Every persona the loaded packs ship, indexed for lookup.

    Parsed once at construction. A persona that fails to parse raises here rather
    than being skipped: a pack shipping a malformed persona is a build error, and
    silently ignoring it would mean a vendor quietly falling back to the vision
    path with nothing on the record to explain why.
    """

    def __init__(self, packs: list[Pack] | None = None) -> None:
        self.packs = load_packs() if packs is None else packs
        self._by_key: dict[tuple[str, str], Persona] = {}
        self._raw: dict[tuple[str, str], dict[str, Any]] = {}
        for pack in self.packs:
            for raw in pack.personas():
                persona = parse_persona(raw)
                key = (persona.sender_fingerprint, persona.doc_type)
                self._by_key[key] = persona
                self._raw[key] = raw

    def lookup(self, sender_fingerprint: str | None, doc_type: str | None) -> Persona | None:
        if sender_fingerprint is None or doc_type is None:
            return None
        return self._by_key.get((sender_fingerprint, doc_type))

    def raw(self, sender_fingerprint: str, doc_type: str) -> dict[str, Any] | None:
        """The unparsed mapping, for anything that needs to re-validate it."""
        return self._raw.get((sender_fingerprint, doc_type))

    def __len__(self) -> int:
        return len(self._by_key)

    @property
    def keys(self) -> list[tuple[str, str]]:
        return sorted(self._by_key)
