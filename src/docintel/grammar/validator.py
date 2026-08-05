"""V1-V13: the persona-write security boundary (`selector-grammar.md` section 8).

From the spec's own framing of why this module exists:

    The validator is the security boundary. There is no sandbox because there is
    nothing to sandbox. If the validator accepts something it shouldn't, that is
    the whole vulnerability class.

Three properties this module holds to, each of which is a test:

1. **All or nothing.** Any failure rejects the whole persona write. There is no
   partial application, so a persona is never half-migrated to a bad rule set.
2. **Operates on the raw mapping.** Validation runs *before* `parse_persona`,
   because a typed constructor that rejected bad vocabularies would be doing
   the boundary's job in a place that is easy to bypass.
3. **`pack=None` means "cannot check", not "reject".** V1, V2's pack half and
   V13 need a pack's field set. Without one they are skipped, so grammar-only
   validation stays useful for authoring tools and for these tests. Every
   grammar-intrinsic rule still runs.

V10 is the load-bearing one. `amount_payable` is *derived* from `total_printed`,
`prior_balance` and `current_charges` - never extracted. A selector pointed
straight at it would look perfectly correct on 7 of the 10 corpus documents,
which is exactly what makes the F1 bug so easy to reintroduce and so hard to
notice.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from docintel.core.errors import ValidationError
from docintel.core.models import DERIVED_ONLY
from docintel.grammar import regions
from docintel.grammar.patterns import NAMED, compile_restricted
from docintel.grammar.schema import (
    BASE_ADJUST_OPS,
    OP_SUPPLIED_FIELDS,
    SCANLINE_AS_FORMS,
    SCANLINE_ASSERTABLE,
    SCANLINE_REGIONS,
    Pack,
)

MAX_PERSONA_BYTES = 64 * 1024
MAX_FEW_SHOT_EXAMPLES = 3

# A few-shot example may not come from a document with flattened annotations
# (V12, F3). Federal Recycling's colored fills are invisible to the text layer,
# so an example drawn from it teaches a confident, wrong lesson.
_POISONED_EXAMPLE_TAG = "flattened_annotations"


# --------------------------------------------------------------------------
# Pattern classification for V6
# --------------------------------------------------------------------------


def _literal_alnum(pattern: str) -> set[str]:
    """Alphanumeric characters the pattern matches *literally*.

    Skips escapes (`\\d`, `\\s`), character classes, quantifier braces and group
    prefixes, so what is left is genuine printed-text context. `NS\\s?#\\s?(\\d{7})`
    yields {N, S}; `(\\d{3}-\\d{4})` yields the empty set, because a dash is not
    context - that pattern is indistinguishable from a phone number.
    """
    out: set[str] = set()
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "\\":
            i += 2
            continue
        if c == "[":
            i += 1
            if i < n and pattern[i] == "^":
                i += 1
            if i < n and pattern[i] == "]":
                i += 1
            while i < n and pattern[i] != "]":
                i += 2 if pattern[i] == "\\" else 1
            i += 1
            continue
        if c == "{":
            while i < n and pattern[i] != "}":
                i += 1
            i += 1
            continue
        if c == "(":
            if pattern.startswith("(?P<", i):
                close = pattern.find(">", i)
                i = close + 1 if close != -1 else i + 4
                continue
            if pattern.startswith("(?", i):
                i += 3 if i + 2 < n and pattern[i + 2] in ":=!" else 2
                continue
            i += 1
            continue
        if c.isalnum():
            out.add(c)
        i += 1
    return out


def _references_digits(pattern: str) -> bool:
    return "\\d" in pattern or "0-9" in pattern


def _is_bare_digit_pattern(pattern: str) -> bool:
    """A digit matcher with no literal text to anchor it (F11).

    Unscoped, these match phone numbers, zip+4 and order numbers. The rule fires
    only for raw regexes: `integer` on `any-page` is a judgement call about
    precision, not a grammar violation.
    """
    if pattern in NAMED:
        return False
    return _references_digits(pattern) and not _literal_alnum(pattern)


# --------------------------------------------------------------------------
# Per-rule checks
# --------------------------------------------------------------------------


def _check_region(region: Any, where: str) -> str:
    """V3, plus V5's "a selector needs a region"."""
    if region is None:
        raise ValidationError(
            f"{where} has no region; a region is required (V5). Section 1.1 waives it "
            "for a provably unique anchor, but uniqueness is a property of a document "
            "and cannot be established at write time - name 'any-page' explicitly if "
            "that is what is meant"
        )
    if not isinstance(region, str) or not regions.is_known(region):
        raise ValidationError(
            f"{where} names region {region!r}, which is not in the section 2 enum (V3)"
        )
    return region


def _check_pattern(pattern: Any, where: str) -> None:
    """V4: a section 3.1 name, or a regex that survives section 3.2."""
    if not isinstance(pattern, str) or not pattern:
        raise ValidationError(f"{where} has no pattern; one is required (V4)")
    if pattern in NAMED:
        return
    compile_restricted(pattern)  # raises ValidationError, already worded for the caller


def _check_bare_digits(pattern: str, region: str, scoped: bool, where: str) -> None:
    """V6: a bare-digit regex needs a narrowing region or a column_headers scope."""
    if not _is_bare_digit_pattern(pattern):
        return
    if scoped or region not in regions.NON_NARROWING:
        return
    raise ValidationError(
        f"{where} uses the bare-digit pattern {pattern!r} on region {region!r} with no "
        "narrowing region and no column_headers scope (V6). Unscoped it also matches "
        "phone numbers and zip+4 (F11)"
    )


def _capture_body(pattern: str) -> str:
    """The text inside the one capturing group, or the whole pattern if there is none.

    What a selector *returns* is the capture group, so that is the only part whose
    generality matters. `Circuit:\\s?([0-9]{10})` is a good rule with a literal in
    it: the literal is doing an anchor's job and the capture describes a shape.
    `payable to (Comcast)` is the same construction inverted, and only looking
    inside the group tells them apart.

    Section 3.2 caps capture groups at one, so the first capturing paren is the
    only one. `(?:...)` and `(?=...)` are skipped: they group without capturing.
    """
    depth = 0
    start: int | None = None
    open_depth = 0
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "\\":
            i += 2  # an escaped char is literal, including an escaped paren
            continue
        if char == "(":
            depth += 1
            if start is None and not pattern.startswith("(?", i):
                start, open_depth = i + 1, depth
        elif char == ")":
            if start is not None and depth == open_depth:
                return pattern[start:i]
            depth -= 1
        i += 1
    return pattern


# Regex constructs that make a capture match more than one string. Checked before
# escapes are neutralised, because `\d` is variability spelled as an escape while
# `\.` and `\(` are literals spelled the same way.
_SHORTHAND_CLASS = re.compile(r"\\[dDwWsSbB]")
_VARIABLE_META = re.compile(r"[\[\]{}*+?|.]")


def _is_literal_capture(pattern: str) -> bool:
    """True when the pattern can only ever capture one exact string.

    A named pattern never is: `text` and `text_block` capture whatever is printed,
    which is the opposite of a content assertion.
    """
    if pattern in NAMED:
        return False
    body = _capture_body(pattern)
    if _SHORTHAND_CLASS.search(body):
        return False
    # Escaped characters stand for themselves, so neutralise them before looking
    # for metacharacters - otherwise `\(1989\)` reads as a group.
    return not _VARIABLE_META.search(re.sub(r"\\.", "x", body))


def _check_literal_capture(pattern: str, region: str, anchor: Any, where: str) -> None:
    """V14: a literal capture must be placed, not merely asserted.

    The converse of V6. V6 forbids a pattern with no literal text on a whole-page
    region because it matches too much; V14 forbids a pattern with nothing BUT
    literal text there because it says nothing about where the value is - it
    restates one document's answer, so it returns nothing on the next document
    where that answer differs.

    Either an `anchor` or a narrowing region satisfies it, because either one is a
    claim about location. With one present the literal is confirming what should be
    found in a known place, which is a legitimate rule: a vendor's own name on its
    own letterhead does not change between its invoices.
    """
    if not _is_literal_capture(pattern):
        return
    if anchor or region not in regions.NON_NARROWING:
        return
    raise ValidationError(
        f"{where} captures the fixed text {_capture_body(pattern)!r} on region "
        f"{region!r} with no anchor (V14). This states what the answer was on one "
        "document rather than where to read it, so it returns nothing on any "
        "document where the value differs - name the printed label in `anchor`, or "
        "narrow the region, or capture a shape instead"
    )


def _check_anchors_are_not_values(selectors: Sequence[Any]) -> None:
    """V14, second half: an anchor may not restate a value the persona captures.

    An anchor is a literal string by nature, so a printed label and the party name
    printed beside it are indistinguishable here - with one exception. If the same
    persona also captures that exact string as a field value, the persona has
    itself declared the string to be a value, and anchoring on it keys the rule to
    one document exactly as a literal pattern would.

    This is the only part of the anchor problem decidable at write time. An anchor
    keyed to a value the persona does NOT also capture still passes, and no static
    rule can catch it; that limit is real and is recorded in
    `docs/architecture/selector-grammar.md`.
    """
    captured: dict[str, str] = {}
    for sel in selectors:
        if not isinstance(sel, Mapping) or "field" not in sel:
            continue
        pattern = sel.get("pattern")
        if isinstance(pattern, str) and _is_literal_capture(pattern):
            body = re.sub(r"\\(.)", r"\1", _capture_body(pattern))
            captured[_norm_anchor(body)] = str(sel.get("field"))

    for index, sel in enumerate(selectors):
        if not isinstance(sel, Mapping):
            continue
        for key in ("anchor", "table_anchor"):
            anchor = sel.get(key)
            if not isinstance(anchor, str):
                continue
            owner = captured.get(_norm_anchor(anchor))
            if owner is not None:
                raise ValidationError(
                    f"selector[{index}] anchors on {anchor!r}, which this persona "
                    f"also captures as the value of {owner!r} (V14). A field value "
                    "cannot double as a label: both move together on the next "
                    "document, so the anchor fails exactly when the value changes"
                )


def _norm_anchor(text: str) -> str:
    """Case- and whitespace-insensitive, colon-agnostic; matches executor._norm."""
    return " ".join(text.split()).upper().rstrip(":")


def _check_anchor_present(region: str, anchor: Any, where: str) -> None:
    """A region defined relative to an anchor cannot resolve without one."""
    if region in regions.ANCHOR_REQUIRED and not anchor:
        raise ValidationError(
            f"{where} uses region {region!r}, which is resolved relative to an anchor, "
            "but declares no anchor"
        )


def _check_not_derived(name: Any, extra: frozenset[str], where: str) -> None:
    """V10. The set is read from core.models so the two cannot drift apart."""
    if name in DERIVED_ONLY or name in extra:
        raise ValidationError(
            f"{where} targets {name!r}, which is derived_only (V10) and may never be "
            "extracted; compute it with an adjust op instead. Pointing a selector at it "
            "is the single easiest way to reintroduce the F1 bug, because on 7 of the 10 "
            "corpus documents such a selector would look perfectly correct"
        )


def _check_adjust(ops: Any, pack: Pack | None, where: str) -> None:
    """V2: every op is registered. The agent references ops; it never defines one."""
    if ops is None:
        return
    listed = (ops,) if isinstance(ops, str) else ops
    if isinstance(listed, Mapping) or not isinstance(listed, Sequence):
        raise ValidationError(f"{where} adjust must be a string or a list of strings")
    known = BASE_ADJUST_OPS | (pack.adjust_ops() if pack is not None else frozenset())
    for op in listed:
        if op not in known:
            raise ValidationError(
                f"{where} names adjust op {op!r}, which is not registered (V2). A new op "
                "is a business-logic change and needs a PR and an eval, not a persona write"
            )


def _check_row_count(value: Any, where: str) -> None:
    """V9: a range, never an equality. Bills legitimately vary in length."""
    if value is None:
        return
    if not isinstance(value, Mapping) or "min" not in value or "max" not in value:
        raise ValidationError(
            f"{where} row_count must be a range mapping with 'min' and 'max' (V9), "
            f"got {value!r}"
        )
    try:
        low, high = int(value["min"]), int(value["max"])
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{where} row_count range bounds must be integers (V9)") from exc
    if low > high:
        raise ValidationError(
            f"{where} row_count range is inverted: min {low} > max {high} (V9)"
        )


def _check_scanline(sel: Mapping[str, Any], index: int) -> None:
    """V7, and the region half of V5."""
    where = f"selector[{index}] (scanline)"
    region = _check_region(sel.get("region"), where)
    if region not in SCANLINE_REGIONS and not region.startswith("page:"):
        raise ValidationError(
            f"{where} names region {region!r}; a scanline may only be sought in "
            f"{sorted(SCANLINE_REGIONS)} or a single 'page:N' (section 1.3). An OCR-A "
            "remittance line is a physical feature of the payment stub"
        )

    asserts = sel.get("asserts") or ()
    if isinstance(asserts, Mapping) or not isinstance(asserts, Sequence):
        raise ValidationError(f"{where} asserts must be a list")
    for item in asserts:
        if not isinstance(item, Mapping):
            raise ValidationError(f"{where} each assert must be a mapping")
        field = item.get("field")
        if field not in SCANLINE_ASSERTABLE:
            raise ValidationError(
                f"{where} may not name {field!r}; a scanline assert is limited to "
                f"{sorted(SCANLINE_ASSERTABLE)} (V7). Centracom's scanline encodes the "
                "misleading headline total, so binding the payable to it would cement "
                "the F1 bug"
            )
        as_form = item.get("as", "digits_only")
        if as_form not in SCANLINE_AS_FORMS:
            raise ValidationError(
                f"{where} names unknown scanline form {as_form!r}; permitted forms are "
                f"{sorted(SCANLINE_AS_FORMS)}"
            )


def _check_sub_group(sub: Any, pack: Pack | None, extra: frozenset[str], where: str) -> str | None:
    """V8 (nesting depth <= 1), plus V4/V10/V1 on the sub-group's own field."""
    if sub is None:
        return None
    if not isinstance(sub, Mapping):
        raise ValidationError(f"{where} sub_group must be a mapping")
    if "sub_group" in sub:
        raise ValidationError(
            f"{where} exceeds the sub_group nesting depth of 1 (V8). There is no corpus "
            "evidence for deeper nesting, and unbounded nesting is unbounded debugging"
        )
    field = sub.get("field")
    _check_not_derived(field, extra, f"{where} sub_group")
    _check_pattern(sub.get("pattern"), f"{where} sub_group")
    return None if field is None else str(field)


# --------------------------------------------------------------------------
# Whole-persona checks
# --------------------------------------------------------------------------


def _check_size(persona: Mapping[str, Any]) -> None:
    """V11: total serialized size <= 64 KB."""
    try:
        payload = json.dumps(persona, default=str)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"persona is not JSON-serializable: {exc}") from exc
    size = len(payload.encode("utf-8"))
    if size > MAX_PERSONA_BYTES:
        raise ValidationError(
            f"persona serializes to {size} bytes; the limit is 64 KB "
            f"({MAX_PERSONA_BYTES} bytes) (V11)"
        )


def _check_few_shot(persona: Mapping[str, Any]) -> None:
    """V12: at most three examples, none from a flattened-annotation document."""
    examples = persona.get("few_shot_examples") or ()
    if isinstance(examples, Mapping) or not isinstance(examples, Sequence):
        raise ValidationError("few_shot_examples must be a list (V12)")
    if len(examples) > MAX_FEW_SHOT_EXAMPLES:
        raise ValidationError(
            f"persona carries {len(examples)} few_shot_examples; at most "
            f"{MAX_FEW_SHOT_EXAMPLES} are permitted (V12)"
        )
    for i, example in enumerate(examples):
        if not isinstance(example, Mapping):
            continue
        raw_tags = example.get("source_tags") or ()
        tags: tuple[Any, ...]
        if isinstance(raw_tags, str):
            tags = (raw_tags,)
        elif isinstance(raw_tags, Mapping) or not isinstance(raw_tags, Sequence):
            # Not tag-shaped at all. Not this rule's business to reject, but
            # `in` on a non-container would raise TypeError rather than a
            # ValidationError, and the boundary must never leak a raw TypeError.
            tags = ()
        else:
            tags = tuple(raw_tags)
        if _POISONED_EXAMPLE_TAG in tags:
            raise ValidationError(
                f"few_shot_examples[{i}] is drawn from a document tagged "
                f"{_POISONED_EXAMPLE_TAG!r} (V12, F3); its colored fills are invisible "
                "to the text layer, so the example would teach a confident wrong lesson"
            )


def _op_supplied(persona: Mapping[str, Any]) -> frozenset[str]:
    """Fields the ops this persona actually declares will supply.

    Read off the persona rather than assumed, so naming the op is what buys the
    exemption. A persona that drops `resolve_bill_to_alias` loses the coverage it
    granted and V13 speaks up again.
    """
    supplied: set[str] = set()
    selectors = persona.get("field_selectors", ())
    if isinstance(selectors, Mapping) or not isinstance(selectors, Sequence):
        return frozenset()
    for sel in selectors:
        if not isinstance(sel, Mapping):
            continue
        adjust = sel.get("adjust") or ()
        names = (adjust,) if isinstance(adjust, str) else adjust
        if isinstance(names, Mapping) or not isinstance(names, Sequence):
            continue
        for name in names:
            supplied |= OP_SUPPLIED_FIELDS.get(str(name), frozenset())
    return frozenset(supplied)


def _check_required_coverage(
    persona: Mapping[str, Any], pack: Pack, covered: set[str], doc_type: str
) -> None:
    """V13: every required field is COVERED, unless the write stays `draft`.

    Covered, not selected - and the difference is the whole of the two exemptions:

    * **Derived-only fields.** `amount_payable` is both required and forbidden to
      select, so demanding a selector for it would make V10 and V13 jointly
      unsatisfiable.
    * **Fields an `adjust` op supplies** (`schema.OP_SUPPLIED_FIELDS`). The same
      situation from the other direction: two of the four telecom templates print
      their bill-to with no label anywhere near it, so `resolve_bill_to_alias`
      reads it from the pack's roster and no selector can produce it. Requiring one
      is what pushed those personas into hardcoding the client's name as a pattern,
      which V14 now rejects - so without this exemption V13 and V14 would be
      jointly unsatisfiable exactly where the document is least helpful.

    Two shapes of requirement. A flat name in `required_fields` must be covered.
    An any-of group in `required_any_of` needs one covered member - which is how
    "any parseable date" and "at least one money amount" are expressed, since
    neither can be pinned to a single field name that every document prints.
    """
    if persona.get("status") == "draft":
        return
    exempt = (
        DERIVED_ONLY
        | pack.derived_only_fields(doc_type)
        | _op_supplied(persona)
    )
    missing = sorted(pack.required_fields(doc_type) - covered - exempt)
    if missing:
        raise ValidationError(
            f"persona status is {persona.get('status')!r} but required fields have no "
            f"selector: {missing} (V13). Leave the write as 'draft' until they do"
        )

    for group in pack.required_any_of(doc_type):
        satisfiable = group - exempt
        # A group of nothing but derived-only names cannot be met by any selector.
        # Raising would make the persona unwritable, which is the same trap the
        # `exempt` subtraction above exists to avoid.
        if not satisfiable:
            continue
        if not (satisfiable & covered):
            raise ValidationError(
                f"persona status is {persona.get('status')!r} but no selector covers "
                f"any of {sorted(satisfiable)} (V13 any-of). Leave the write as "
                "'draft' until one does"
            )


def validate_persona(persona: Mapping[str, Any], pack: Pack | None = None) -> None:
    """Validate a persona write against V1-V13. Returns None; raises on any failure.

    Rejection is all-or-nothing: the first failing rule raises, and nothing about
    the persona has been applied anywhere by the time it does.
    """
    if isinstance(persona, str) or not isinstance(persona, Mapping):
        raise ValidationError(
            f"persona must be a mapping, got {type(persona).__name__}"
        )

    status = persona.get("status")
    if status not in ("draft", "active"):
        raise ValidationError(
            f"persona status must be 'draft' or 'active', got {status!r}"
        )
    doc_type = str(persona.get("doc_type", ""))

    _check_size(persona)
    _check_few_shot(persona)

    selectors = persona.get("field_selectors", ())
    if isinstance(selectors, Mapping) or not isinstance(selectors, Sequence):
        raise ValidationError("field_selectors must be a list of selectors")

    pack_derived = pack.derived_only_fields(doc_type) if pack is not None else frozenset()
    registered = pack.fields_for(doc_type) if pack is not None else None
    covered: set[str] = set()

    for index, sel in enumerate(selectors):
        if not isinstance(sel, Mapping):
            raise ValidationError(f"selector[{index}] must be a mapping")

        if "scanline" in sel:
            _check_scanline(sel, index)
            continue

        if "row_group" in sel:
            where = f"selector[{index}] (row_group {sel.get('row_group')!r})"
            if sel.get("region") is not None:
                _check_region(sel["region"], where)
            if not sel.get("table_anchor"):
                raise ValidationError(f"{where} has no table_anchor")

            columns = sel.get("columns")
            if not isinstance(columns, Mapping) or not columns:
                raise ValidationError(f"{where} columns must be a non-empty mapping")
            headers = sel.get("column_headers") or {}
            if not isinstance(headers, Mapping):
                raise ValidationError(f"{where} column_headers must be a mapping")

            for name, pattern in columns.items():
                _check_not_derived(name, pack_derived, f"{where} column {name!r}")
                _check_pattern(pattern, f"{where} column {name!r}")
                # A row group's scope is its table; an explicit column header is
                # the narrowing V6 asks for, since the search is confined to
                # that column rather than loose on the page.
                _check_bare_digits(
                    str(pattern),
                    str(sel.get("region") or "any-page"),
                    scoped=name in headers,
                    where=f"{where} column {name!r}",
                )
                covered.add(str(name))

            _check_row_count(sel.get("row_count"), where)
            sub_field = _check_sub_group(sel.get("sub_group"), pack, pack_derived, where)
            if sub_field is not None:
                covered.add(sub_field)
            _check_adjust(sel.get("adjust"), pack, where)

            if registered is not None and pack is not None:
                named = (*columns, *((sub_field,) if sub_field else ()))
                for name in named:
                    if name not in registered:
                        raise ValidationError(
                            f"{where} names {name!r}, which is not a registered field "
                            f"for doc_type {doc_type!r} in pack {pack.name!r} (V1)"
                        )
            continue

        # field_selector
        field = sel.get("field")
        where = f"selector[{index}] (field {field!r})"
        if not field:
            raise ValidationError(f"selector[{index}] has no field name")

        _check_not_derived(field, pack_derived, where)
        region = _check_region(sel.get("region"), where)
        _check_pattern(sel.get("pattern"), where)
        _check_bare_digits(str(sel["pattern"]), region, scoped=False, where=where)
        _check_literal_capture(str(sel["pattern"]), region, sel.get("anchor"), where)
        _check_anchor_present(region, sel.get("anchor"), where)
        _check_adjust(sel.get("adjust"), pack, where)

        if registered is not None and pack is not None and field not in registered:
            raise ValidationError(
                f"{where} is not a registered field for doc_type {doc_type!r} in pack "
                f"{pack.name!r} (V1)"
            )
        covered.add(str(field))

    # Persona-wide, so it runs after every selector has been seen: the anchor and
    # the value that collide may be declared in either order.
    _check_anchors_are_not_values(selectors)

    if pack is not None:
        _check_required_coverage(persona, pack, covered, doc_type)
