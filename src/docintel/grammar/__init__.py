"""The closed selector grammar (`docs/architecture/selector-grammar.md`).

Rule agents write *data*, never code (spec Part 6). This package is what
makes that enforceable: `schema` gives the data shapes a persona may take,
`patterns` and `regions` give the closed vocabularies a selector may name,
and `validator` is the security boundary that rejects anything outside
those vocabularies at write time, before a selector ever touches a real
document.
"""

from __future__ import annotations
