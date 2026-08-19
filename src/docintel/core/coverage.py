"""What the persona promised, against what the page actually gave up.

**Completeness is a separate dimension from confidence, and collapsing the two
would reintroduce the bug this module exists to close.** Confidence answers "how
well did I read this value"; it is defined only where a value exists, because
`match_quality` is recorded inside `ExtractedFields.set()`. Completeness answers
"did I get everything I said I would", which is a statement about the fields that
are *not* there. Scoring a missing field 0.0 would express it in the confidence
vocabulary, but it would also claim the pipeline read something badly when in fact
it read nothing at all - and it would put a valueless name in the confidence map
that every downstream consumer reads alongside `fields`.

So this returns its own record, `s7_gate` routes on it as a second dimension, and
`confidence` keeps meaning exactly what it meant before.

**Two questions, because neither subsumes the other.**

* *Declared and empty* - a selector with `required: true` that produced no value.
  This is the hardcoded-literal failure: `bill_to_name` keyed to
  `(Clyde Administration Servi)` returns nothing for a client onboarded last week.
  `FieldSelector.required` has existed since the grammar was written and until now
  had exactly one consumer, the authoring-time validator (V13). This is the
  runtime half.

* *Never declared* - a name in the pack's `required_fields` / `required_any_of`
  contract that nothing satisfied. Selector-level `required` is structurally blind
  here: delete the selector and there is no longer anything to be required. That
  is not a hypothetical - it is the shape of an unfinished persona, and it is what
  the §4 rule-deletion experiment actually produced.

Nothing is exempted for being derived-only. V13 exempts `amount_payable` from
needing a *selector*, because V10 forbids one - but at runtime a derived field is
satisfied by `ctx.derived`, so the question "is it there" is answerable without
the exemption. A pack that requires a derived field the ops could not compute has
a real gap, and hiding it here would be the same mistake one layer down.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from docintel.core.models import JobContext

# Share of a persona's declared selectors that must produce nothing before a
# document reads as "the rules no longer fit this template" rather than "one
# field moved". Lives here, not in whichever stage first needed it, because it
# is a fact about what `miss_share` means - both `s5b_vision`'s escalation
# check and `s7_gate`'s lane routing compare against this same number, and a
# stage-5 module importing a stage-7 module's constant would be a
# backwards-looking dependency for no reason.
DEFAULT_COLLAPSE_SHARE = 0.60


@runtime_checkable
class ScalarSelector(Protocol):
    """A selector that names one field and says whether it must be found.

    A Protocol rather than an import of `grammar.schema.FieldSelector`, because
    `core` must not depend on `grammar` - the same rule that makes `_serialize` in
    `core.contract` duck-type DateResult and AccountNumber. Stating it as a
    Protocol instead of a `hasattr` pair keeps it checkable: the structural claim
    is verified by mypy rather than asserted in a comment.

    `field` plus `required` is exactly the shape of a scalar selector. A row group
    has neither, and a scan line has neither, so `isinstance` cleanly separates the
    three kinds a persona's `field_selectors` may contain.
    """

    @property
    def field(self) -> str: ...

    @property
    def required(self) -> bool: ...


@dataclass(frozen=True)
class Coverage:
    """The completeness of one document's extraction.

    `assessed` is not decoration. A document that reached no persona has nothing
    to be measured against, and `complete=True` on a vacuous count would be the
    original bug wearing a new key: silence reading as success.
    """

    declared: int = 0
    populated: int = 0
    missing_required: tuple[str, ...] = ()
    assessed: bool = False

    @property
    def complete(self) -> bool:
        return (
            self.assessed
            and not self.missing_required
            and self.populated == self.declared
        )

    @property
    def miss_share(self) -> float:
        """Share of declared selectors that produced nothing.

        Zero when nothing was declared, so an unassessed document never looks
        collapsed - `assessed` is what distinguishes those two cases, and the gate
        checks it.
        """
        if self.declared <= 0:
            return 0.0
        return (self.declared - self.populated) / self.declared

    def as_record(self) -> dict[str, object]:
        """The `extraction_coverage` block. Names, not just counts, because the
        actionable question downstream is *which* field is missing."""
        return {
            "declared": self.declared,
            "populated": self.populated,
            "missing_required": list(self.missing_required),
            "complete": self.complete,
        }


def assess(ctx: JobContext) -> Coverage:
    """Measure `ctx`'s extraction against what its persona and pack demanded."""
    if ctx.persona is None:
        return Coverage(assessed=False)

    declared: list[ScalarSelector] = [
        s for s in _selectors(ctx) if isinstance(s, ScalarSelector)
    ]

    def satisfied(name: str) -> bool:
        """Extracted or derived. A field an adjust op computed is present.

        U-PAK's `vendor_name` is resolved from an alias table into `derived` and
        never appears in `extracted`; reading only `extracted` would report it
        missing and force a document to review over a value the record carries.
        """
        return ctx.extracted.get(name) is not None or ctx.derived.get(name) is not None

    missing: set[str] = {
        s.field for s in declared if s.required and not satisfied(s.field)
    }
    missing |= _pack_gaps(ctx, satisfied)

    return Coverage(
        declared=len(declared),
        populated=sum(1 for s in declared if satisfied(s.field)),
        missing_required=tuple(sorted(missing)),
        assessed=True,
    )


def _selectors(ctx: JobContext) -> tuple[object, ...]:
    declared = getattr(ctx.persona, "field_selectors", ())
    return tuple(declared) if isinstance(declared, (list, tuple)) else ()


def _pack_gaps(ctx: JobContext, satisfied: Callable[[str], bool]) -> set[str]:
    """The pack contract's unmet requirements, flat and any-of.

    An any-of group reports as one synthetic name rather than as each of its
    members: the members are alternatives, so listing them individually would
    read as several missing fields when the gap is one unanswered question.
    """
    pack, doc_type = ctx.pack, ctx.doc_type
    if pack is None or doc_type is None:
        return set()

    gaps: set[str] = set()
    required = getattr(pack, "required_fields", None)
    if callable(required):
        gaps |= {name for name in required(doc_type) if not satisfied(name)}

    any_of = getattr(pack, "required_any_of", None)
    if callable(any_of):
        for group in any_of(doc_type):
            if group and not any(satisfied(name) for name in group):
                gaps.add(f"any_of({'|'.join(sorted(group))})")
    return gaps
