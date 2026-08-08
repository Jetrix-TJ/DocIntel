"""Compile a classification ladder from data, against the closed signal registry.

**Why this exists.** Extraction was made generic years before classification:
a persona is JSON, validated against a closed op enum, so onboarding a vendor
is data plus evidence. Classification stayed hand-written Python per pack -
which is why onboarding a *company* costs ~1,200 lines across eight modules and
adding a *document type* costs an `if` branch and a release. This module closes
that asymmetry using the same shape the grammar already proved.

**A ladder is an ordered list of rungs; the first whose condition holds wins.**
That was already the rule (spec Stage 3); it was just implicit in the order of
`if` statements. Making it data makes it reviewable, diffable, and writable by
somebody who understands invoices rather than Python.

**A condition is a small closed algebra**, because both shipped ladders need
exactly this much and no more:

```
{"signal": "pattern_in_scope", "params": {...}}   a named primitive
{"all_of": [cond, ...]}                           every one holds
{"any_of": [cond, ...]}                           at least one holds
{"not": cond}                                     negation
```

Digital Direction's `disconnect_notice` rung is the reason `not` exists:
"suspension language AND no current-charges block" - both halves required,
because a bill that merely warns about future disconnection is still a bill.

**Validation is fail-loud and happens at load, not at classify time.** An
unknown signal name, an unknown scope, a misspelled parameter - each raises
rather than silently evaluating false. A rung that silently never fires is a
document type that silently never gets recognised, which is exactly the class of
failure this project refuses to ship (`s3_classify.py`: an unclaimed document is
flagged, never dropped).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from docintel.core.models import JobContext
from docintel.packs import signals


class LadderError(ValueError):
    """A classification spec that cannot be compiled. Raised at load time."""


# The closed registry. A pack composes what is here; adding an entry is a code
# change with a test and a named real document behind it - the same bar the
# grammar's `BASE_ADJUST_OPS` sets. This is what keeps "declarative" from
# becoming a second, unreviewed way to write regexes.
SIGNALS: dict[str, Any] = {
    "pattern_in_scope": signals.pattern_in_scope,
    "short_label_line": signals.short_label_line,
    "title_near_top": signals.title_near_top,
    "text_near_top": signals.text_near_top,
    "label_with_corroborating_value": signals.label_with_corroborating_value,
    "all_matches_negative": signals.all_matches_negative,
    "role_shape": signals.role_shape,
    "shared_pagination_footer": signals.shared_pagination_footer,
    "money_table_present": signals.money_table_present,
    "text_source_is": signals.text_source_is,
    "noise_ratio_above": signals.noise_ratio_above,
    "distinct_printed_aliases_at_least": signals.distinct_printed_aliases_at_least,
}

# Parameters whose value is a regular expression rather than a scalar. Compiled
# once at load, so a bad pattern is a load-time error and a classify-time
# `re.compile` never appears in a hot loop.
_PATTERN_PARAMS: frozenset[str] = frozenset({"pattern", "label"})

# Parameters naming a value predicate from `signals.VALUE_PREDICATES`.
_PREDICATE_PARAMS: frozenset[str] = frozenset({"same_line", "next_line"})


def _compile_params(name: str, params: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in params.items():
        if key in _PATTERN_PARAMS:
            flags = re.I if params.get("ignore_case", True) else 0
            try:
                out[key] = re.compile(value, flags)
            except re.error as exc:
                raise LadderError(f"{name}.{key}: bad regex {value!r}: {exc}") from exc
        elif key in _PREDICATE_PARAMS:
            out[key] = _compile_predicate(name, key, value, params)
        elif key == "ignore_case":
            continue  # consumed by the pattern params above
        else:
            out[key] = value
    return out


def _compile_predicate(
    name: str, key: str, value: Any, params: Mapping[str, Any]
) -> Any:
    """Resolve a value-predicate name to its function.

    `money_after_label_nonzero` needs the label it corroborates, so it is a
    factory rather than a plain predicate - the only one, and handled here
    rather than by giving every predicate a uniform-but-mostly-unused signature.
    """
    predicate = signals.VALUE_PREDICATES.get(value)
    if predicate is None:
        raise LadderError(
            f"{name}.{key}: unknown value predicate {value!r}; "
            f"expected one of {sorted(signals.VALUE_PREDICATES)}"
        )
    if value == "money_after_label_nonzero":
        label = params.get("label")
        if label is None:
            raise LadderError(f"{name}.{key}: {value!r} requires a `label` parameter")
        flags = re.I if params.get("ignore_case", True) else 0
        return predicate(re.compile(label, flags))
    return predicate


class Condition:
    """A compiled condition. Evaluating one never raises on document content."""

    def __init__(self, evaluate: Any, describe: str) -> None:
        self._evaluate = evaluate
        self.describe = describe

    def __call__(self, ctx: JobContext) -> bool:
        return bool(self._evaluate(ctx))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Condition {self.describe}>"


def compile_condition(spec: Mapping[str, Any], *, where: str = "condition") -> Condition:
    """Compile one node of the condition algebra. Raises `LadderError` on anything
    it does not recognise, rather than evaluating to False."""
    if not isinstance(spec, Mapping):
        raise LadderError(f"{where}: expected a mapping, got {type(spec).__name__}")

    keys = set(spec) & {"signal", "all_of", "any_of", "not"}
    if len(keys) != 1:
        raise LadderError(
            f"{where}: expected exactly one of signal/all_of/any_of/not, got {sorted(spec)}"
        )

    if "all_of" in spec or "any_of" in spec:
        combinator = "all_of" if "all_of" in spec else "any_of"
        children_spec = spec[combinator]
        if not isinstance(children_spec, Sequence) or isinstance(children_spec, str):
            raise LadderError(f"{where}.{combinator}: expected a list")
        if not children_spec:
            # An empty all_of is vacuously true and would make its rung fire on
            # every document; an empty any_of is vacuously false and would make
            # it fire on none. Both are far more likely to be an authoring slip
            # than an intent.
            raise LadderError(f"{where}.{combinator}: must not be empty")
        children = [
            compile_condition(child, where=f"{where}.{combinator}[{i}]")
            for i, child in enumerate(children_spec)
        ]
        joiner = all if combinator == "all_of" else any
        return Condition(
            lambda ctx: joiner(child(ctx) for child in children),
            f"{combinator}({', '.join(c.describe for c in children)})",
        )

    if "not" in spec:
        inner = compile_condition(spec["not"], where=f"{where}.not")
        return Condition(lambda ctx: not inner(ctx), f"not({inner.describe})")

    name = spec["signal"]
    fn = SIGNALS.get(name)
    if fn is None:
        raise LadderError(
            f"{where}: unknown signal {name!r}; expected one of {sorted(SIGNALS)}"
        )
    raw_params = spec.get("params", {})
    if not isinstance(raw_params, Mapping):
        raise LadderError(f"{where}.params: expected a mapping")
    params = _compile_params(name, raw_params)

    scope = params.get("scope")
    if scope is not None and scope not in signals.SCOPES:
        raise LadderError(
            f"{where}.params.scope: unknown scope {scope!r}; "
            f"expected one of {sorted(signals.SCOPES)}"
        )

    positional = [params.pop(key) for key in ("pattern",) if key in params]
    # `short_label_line` takes max_words positionally; everything else is
    # keyword-only, which is what makes a misspelled parameter a TypeError at
    # load rather than a silently ignored one.
    if name == "short_label_line" and "max_words" in params:
        positional.append(params.pop("max_words"))

    def evaluate(ctx: JobContext) -> bool:
        return bool(fn(ctx, *positional, **params))

    try:
        _probe(evaluate)
    except TypeError as exc:
        raise LadderError(f"{where}: {name} rejected its parameters: {exc}") from exc

    return Condition(evaluate, f"{name}({', '.join(sorted(raw_params))})")


def _probe(evaluate: Any) -> None:
    """Call the compiled signal once against an empty document.

    This is how a misspelled or missing parameter becomes a LOAD-time error.
    A signal is a pure function of the context, and an empty context exercises
    the signature without touching any real document - so a `TypeError` here is
    always a spec bug, never a data problem.
    """
    evaluate(JobContext(document_id="", source_path=""))


class Ladder:
    """A compiled ladder. `doc_type_for` mirrors the hand-written signature so a
    pack can swap representations without touching its hooks."""

    def __init__(self, rungs: list[tuple[str, str, Condition]], default: str) -> None:
        self.rungs = rungs
        self.default = default

    def doc_type_for(self, ctx: JobContext) -> tuple[str, str]:
        """(doc_type, signal_that_fired). First rung that holds wins, then stop."""
        for name, doc_type, condition in self.rungs:
            if condition(ctx):
                return doc_type, name
        return self.default, "default"

    def signal_names(self) -> list[str]:
        return [name for name, _, _ in self.rungs]


class TagRules:
    """Compiled tag rules. Unlike rungs these do not stop at the first match -
    tags are layered on and never change the type."""

    def __init__(self, rules: list[tuple[str, Condition]]) -> None:
        self.rules = rules

    def tags_for(self, ctx: JobContext) -> list[str]:
        return [tag for tag, condition in self.rules if condition(ctx)]


def compile_ladder(spec: Mapping[str, Any]) -> Ladder:
    rungs_spec = spec.get("rungs")
    if not isinstance(rungs_spec, Sequence) or not rungs_spec:
        raise LadderError("ladder.rungs: expected a non-empty list")
    default = spec.get("default")
    if not isinstance(default, str) or not default:
        raise LadderError("ladder.default: expected the fallback doc_type")

    seen: set[str] = set()
    rungs: list[tuple[str, str, Condition]] = []
    for i, rung in enumerate(rungs_spec):
        where = f"ladder.rungs[{i}]"
        if not isinstance(rung, Mapping):
            raise LadderError(f"{where}: expected a mapping")
        name, doc_type = rung.get("name"), rung.get("doc_type")
        if not isinstance(name, str) or not name:
            raise LadderError(f"{where}.name: expected the signal_that_fired value")
        if name in seen:
            # `signal_that_fired` is what an auditor reads to learn WHY a
            # document was classified. Two rungs sharing a name makes that
            # answer ambiguous.
            raise LadderError(f"{where}.name: duplicate rung name {name!r}")
        seen.add(name)
        if not isinstance(doc_type, str) or not doc_type:
            raise LadderError(f"{where}.doc_type: expected a doc_type")
        if name == "default":
            raise LadderError(f"{where}.name: 'default' is reserved for the fallback")
        rungs.append((name, doc_type, compile_condition(rung.get("when", {}), where=where)))
    return Ladder(rungs, default)


def compile_tags(spec: Sequence[Mapping[str, Any]]) -> TagRules:
    rules: list[tuple[str, Condition]] = []
    seen: set[str] = set()
    for i, rule in enumerate(spec):
        where = f"tags[{i}]"
        if not isinstance(rule, Mapping):
            raise LadderError(f"{where}: expected a mapping")
        tag = rule.get("tag")
        if not isinstance(tag, str) or not tag:
            raise LadderError(f"{where}.tag: expected a tag name")
        if tag in seen:
            raise LadderError(f"{where}.tag: duplicate tag {tag!r}")
        seen.add(tag)
        rules.append((tag, compile_condition(rule.get("when", {}), where=where)))
    return TagRules(rules)


def compile_classification(spec: Mapping[str, Any]) -> tuple[Ladder, TagRules]:
    """Compile a pack's whole `classification` block. Raises on any problem."""
    ladder_spec = spec.get("ladder")
    if not isinstance(ladder_spec, Mapping):
        raise LadderError("classification.ladder: expected a mapping")
    tags_spec = spec.get("tags", [])
    if not isinstance(tags_spec, Sequence):
        raise LadderError("classification.tags: expected a list")
    return compile_ladder(ladder_spec), compile_tags(tags_spec)
