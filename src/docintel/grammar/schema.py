"""Persona data shapes (`selector-grammar.md` sections 1, 4 and 6).

Division of labour worth being explicit about, because getting it backwards
would put the security boundary in the wrong place:

* `validator.validate_persona` takes the **raw mapping** an agent wrote and
  decides whether it is allowed. That is the boundary.
* `parse_persona` takes a mapping that has *already passed* validation and
  builds frozen, typed objects for the executor. It rejects only structural
  impossibilities - a missing `doc_type`, a selector matching none of the three
  kinds - never policy. It does not re-check vocabularies.

The parsed types are frozen and their mappings are read-only views, matching
`core.models.ExtractedFields`: a persona is a contract, and a stage that could
edit it in place would make the emitted `rule_version` a lie.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Protocol, runtime_checkable

from docintel.core.errors import ValidationError

PersonaWriteStatus = Literal["draft", "active"]
Capture = Literal["first", "all_matches"]
AnchorOccurrence = Literal["first", "last"]
TotalsPageRole = Literal["last", "first"]
FingerprintTextSource = Literal["native", "ocr", "either"]

# The closed adjust-op enum (section 4). The agent may reference these; it may
# never define one. C3 supplies the implementations - the validator needs only
# the names, so that an unregistered op is rejected at write time today rather
# than discovered at run time later.
BASE_ADJUST_OPS: frozenset[str] = frozenset({
    # 4.1 base
    "strip_internal_whitespace",
    "strip_currency_symbols",
    "parens_to_negative",
    "trailing_cr_to_negative",
    "normalize_date_iso",
    "uppercase",
    "lowercase",
    "trim",
    "collapse_internal_spaces",
    # Added in C5a, deliberately: no other op turns a multi-line `text_block`
    # into the comma-joined single string every gold address label uses, and
    # `collapse_internal_spaces` loses the separator. See ops.base for the full
    # justification.
    "join_lines_comma",
    "dedupe_preserve_order",
    # 4.2 derivation - the F1 machinery
    "derive_amount_payable",
    "resolve_carried_balance",
    "normalize_credit_sign",
    "subtract_prior_balance_if_present",
    "prefer_current_charges_line",
    # 4.3 consistency - scoring only, never value-changing
    "crosscheck_line_sum",
    "crosscheck_total_composition",
    "crosscheck_balance_composition",
    "crosscheck_scanline",
    "crosscheck_duplicate_anchor",
    "crosscheck_filename",
    # 4.4 inference
    "infer_currency",
    "resolve_vendor_alias",
    # GRAMMAR EXTENSION, section 10. The bill-to counterpart of
    # `resolve_vendor_alias`, added for the same reason the vendor one exists: two
    # of the four telecom templates print their bill-to with no label anywhere
    # near it, so no anchor exists and no selector can read it. Those personas
    # therefore carried the client's name as their *pattern*, which returns
    # nothing for a client onboarded last week - and since extraction completeness
    # now escalates a missing required field, that meant every one of a new
    # client's invoices going to manual review. The pack's roster replaces 9
    # per-document literals across both packs with one table per pack.
    "resolve_bill_to_alias",
})

# Fields an adjust op can supply with no selector, so V13 counts them as covered.
#
# V13 asks that a required field be *covered*, not that it be selected, and it
# already exempted the derived-only fields on exactly these grounds: demanding a
# selector for `amount_payable` while V10 forbids one makes the two rules jointly
# unsatisfiable. A field read from a pack table is the same situation reached from
# the other direction - the value is real and on every record, and no selector can
# produce it.
#
# The derivation ops are deliberately absent: their outputs are all in
# `core.models.DERIVED_ONLY`, which V13 exempts already, and listing them twice
# would leave two places to keep in step.
OP_SUPPLIED_FIELDS: dict[str, frozenset[str]] = {
    # Reads the bill-to party from the pack's roster when the page prints no label
    # to anchor on - the case two of the four telecom templates present.
    "resolve_bill_to_alias": frozenset({"bill_to_name"}),
    # Supplies `vendor_name` from the pack's display table when the letterhead is
    # an image (Lumen) or the text layer breaks the brand mid-word (Windstream).
    "resolve_vendor_alias": frozenset({"vendor_name"}),
}

# Fields a scanline may corroborate (section 1.3). Binding `amount_payable` here
# would cement the F1 bug: Centracom's scanline encodes the misleading headline
# total, so a scanline "confirming" the payable would confirm the wrong number.
SCANLINE_ASSERTABLE: frozenset[str] = frozenset({
    "total_printed", "account_number", "invoice_number", "due_date",
})

# The `as` forms a scanline assert may request.
SCANLINE_AS_FORMS: frozenset[str] = frozenset({
    "digits_no_decimal", "digits_only",
})

# Where a scanline may be looked for. Section 1.3 writes this as an explicit
# enum (`"last-page" | "page:1" | "remittance-block"`), narrower than the full
# section 2 region vocabulary, and it is kept narrow here: an OCR-A remittance
# line is a physical feature of the payment stub, so a persona claiming to find
# one in a `header-block` is describing something that does not exist.
# `page:N` generalizes the spec's `page:1` - a five-page bill's stub is on page
# five, and a single named page is just as narrow as page one.
SCANLINE_REGIONS: frozenset[str] = frozenset({"last-page", "remittance-block"})


@runtime_checkable
class Pack(Protocol):
    """What the validator needs from a pack. The registry itself arrives in C5a.

    Kept to four members on purpose: every one of them backs a specific
    validation rule, so it is obvious when the protocol grows for a reason and
    when it is growing by accident.
    """

    @property
    def name(self) -> str: ...

    def fields_for(self, doc_type: str) -> frozenset[str]:
        """Every field name registered for `doc_type`. Backs V1."""
        ...

    def required_fields(self, doc_type: str) -> frozenset[str]:
        """Fields that must have a selector before a write can leave `draft`. V13."""
        ...

    def required_any_of(self, doc_type: str) -> tuple[frozenset[str], ...]:
        """Groups where at least one member must have a selector. Backs V13's
        any-of clause.

        A flat `required_fields` cannot express "any parseable date" or "at least
        one money amount" - both of which the field spec states outright, and both
        of which name fields that a fifth of real documents do not print. Each
        group here is satisfied by one covered member.
        """
        ...

    def derived_only_fields(self, doc_type: str) -> frozenset[str]:
        """Fields no selector may target, beyond `core.models.DERIVED_ONLY`. V10."""
        ...

    def adjust_ops(self) -> frozenset[str]:
        """Pack-registered ops, on top of `BASE_ADJUST_OPS`. Backs V2."""
        ...


# --------------------------------------------------------------------------
# Selector types
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldSelector:
    """One value. Section 1.1."""

    field: str
    pattern: str
    region: str
    anchor: str | None = None
    anchor_alts: tuple[str, ...] = ()
    # Which occurrence of `anchor` to resolve to. GRAMMAR EXTENSION, section 10.
    #
    # The reason: `_resolve_anchor` returns `hits[0]`, so a label printed more than
    # once always resolves to the first in reading order. `veritiv` and
    # `windstream` each print their own name exactly TWICE on the primary page,
    # and the second (last) occurrence is the one sitting above the remittance
    # block, so `anchor_occurrence: "last"` reaches it - both personas'
    # `remit_address` selectors depend on this.
    #
    # That does NOT generalize to every repeated anchor. `edco` prints its payee
    # name THREE times on its primary page (the letterhead, the remittance
    # block, and the "FOR SERVICE AT:" service-location header); `last` lands on
    # the third occurrence, not the remittance block. That is why `edco`'s
    # `remit_address` still anchors on "P.O. BOX 5488" (a value-in-the-anchor
    # workaround) rather than the payee name, and remains tracked in
    # `ANCHOR_IN_VALUE_DEBT` (`tests/packs/test_no_hardcoded_values.py`) - not a
    # trivial one-line fix, since the third occurrence is where the correct
    # anchor is unreachable, not simply the last one.
    #
    # Default "first", pinned by a test: flipping it would silently move every
    # anchored selector in both packs.
    anchor_occurrence: AnchorOccurrence = "first"
    capture: Capture = "first"
    adjust: tuple[str, ...] = ()
    required: bool = True


@dataclass(frozen=True)
class SubGroup:
    """A one-level nesting under a row group. Section 1.2, F19."""

    anchor: str
    field: str
    pattern: str


@dataclass(frozen=True)
class RowGroupSelector:
    """Repeating rows. Section 1.2.

    `columns` is keyed by column *name* and matched by header *text* (F19),
    never by index: U-PAK and Veritiv both reorder columns between revisions of
    the same template.
    """

    row_group: str
    table_anchor: str
    columns: Mapping[str, str]
    column_headers: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    region: str | None = None
    sub_group: SubGroup | None = None
    row_count: tuple[int, int] | None = None
    allow_empty_cells: bool = True
    # Opt in to dropping lines that match no money column. GRAMMAR EXTENSION,
    # added deliberately (section 10 requires a reason, not an agent's say-so).
    #
    # The reason: Veritiv's table is followed by five terms-and-conditions lines
    # that match its text column, and nothing in the page geometry distinguishes
    # them from a row - the pitch is regular and the gap is not structural.
    #
    # Default False because the opposite case is ALSO real and already specified:
    # F15 says a blank cell is a blank cell, and
    # `test_empty_cells_are_omitted_when_allowed` pins `BALANCE FORWARD` with no
    # amount as a legitimate row. EDCO's gold agrees. So this cannot be the
    # default without contradicting a decision the corpus already encodes.
    require_amount: bool = False
    # Opt in to ending the table at a row whose amount equals the sum of the rows
    # above it. GRAMMAR EXTENSION, same section 10 justification as above.
    #
    # The reason: on Complete Beverage and Federal Recycling the totals row is
    # printed TIGHTER than the body it follows (16.56pt against an 18.00pt pitch;
    # 16.92 against 19.98), so `TABLE_BREAK_FACTOR` can never reach it - no
    # multiple greater than 1 fires on a gap smaller than the pitch. Arithmetic
    # reaches it: their 12 and 10 gold rows sum to exactly 1177.70 and 481.20,
    # which are precisely the values being swallowed as an extra row.
    #
    # Default False for the same reason as `require_amount`: EDCO's gold counts
    # `CURRENT CHARGES:` as a line item, so a roll-up row is a real row on some
    # documents and a terminator on others. Only the persona can say which.
    stop_at_subtotal: bool = False


@dataclass(frozen=True)
class ScanlineAssert:
    """One corroboration claim. `as_form` renames `as`, which is a keyword."""

    field: str
    as_form: str


@dataclass(frozen=True)
class ScanlineSelector:
    """The remittance OCR-A line. Section 1.3.

    Scoring only: produces no field value, and can only raise or lower
    confidence on a field some other selector already extracted.
    """

    region: str
    asserts: tuple[ScanlineAssert, ...]


Selector = FieldSelector | RowGroupSelector | ScanlineSelector


@dataclass(frozen=True)
class LayoutFingerprint:
    """Document-level, never page-level (F20). Section 6.

    Every member is optional. An empty fingerprint matches anything and never
    produces a soft miss, which is the right default for a first draft persona.
    """

    page_count: tuple[int, int] | None = None
    has_table: bool | None = None
    header_signature: str | None = None
    totals_page_role: TotalsPageRole | None = None
    column_signature: tuple[str, ...] = ()
    text_source: FingerprintTextSource | None = None


@dataclass(frozen=True)
class Persona:
    """A parsed, validated persona: the rules for one sender's one doc type."""

    sender_fingerprint: str
    doc_type: str
    rule_version: str
    status: PersonaWriteStatus
    field_selectors: tuple[Selector, ...]
    layout_fingerprint: LayoutFingerprint
    few_shot_examples: tuple[Mapping[str, Any], ...] = ()


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def _require_key(raw: Mapping[str, Any], key: str) -> Any:
    if key not in raw:
        raise ValidationError(f"persona is missing required key {key!r}")
    return raw[key]


def _as_tuple(value: Any) -> tuple[str, ...]:
    """Section 1.1 allows `adjust` as a bare string or a list; normalize to one shape."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(str(v) for v in value)
    raise ValidationError(f"expected a string or a list of strings, got {type(value).__name__}")


def _parse_range(value: Any, what: str) -> tuple[int, int] | None:
    """A {min, max} mapping. Equality-as-a-range is fine; a bare int is not (V9)."""
    if value is None:
        return None
    if not isinstance(value, Mapping) or "min" not in value or "max" not in value:
        raise ValidationError(f"{what} must be a range mapping with 'min' and 'max'")
    return int(value["min"]), int(value["max"])


def _parse_field_selector(raw: Mapping[str, Any]) -> FieldSelector:
    capture = raw.get("capture", "first")
    if capture not in ("first", "all_matches"):
        raise ValidationError(f"capture must be 'first' or 'all_matches', got {capture!r}")
    occurrence = raw.get("anchor_occurrence", "first")
    if occurrence not in ("first", "last"):
        raise ValidationError(
            f"anchor_occurrence must be 'first' or 'last', got {occurrence!r}"
        )
    if occurrence != "first" and raw.get("anchor") is None:
        # An occurrence selector with no anchor to select an occurrence OF is a
        # typo that would otherwise do nothing quietly.
        raise ValidationError("anchor_occurrence requires an anchor")
    return FieldSelector(
        field=str(_require_key(raw, "field")),
        pattern=str(_require_key(raw, "pattern")),
        region=str(_require_key(raw, "region")),
        anchor=None if raw.get("anchor") is None else str(raw["anchor"]),
        anchor_alts=_as_tuple(raw.get("anchor_alts")),
        anchor_occurrence=occurrence,
        capture=capture,
        adjust=_as_tuple(raw.get("adjust")),
        required=bool(raw.get("required", True)),
    )


def _parse_sub_group(raw: Any) -> SubGroup | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValidationError("sub_group must be a mapping")
    return SubGroup(
        anchor=str(_require_key(raw, "anchor")),
        field=str(_require_key(raw, "field")),
        pattern=str(_require_key(raw, "pattern")),
    )


def _parse_row_group(raw: Mapping[str, Any]) -> RowGroupSelector:
    columns = _require_key(raw, "columns")
    if not isinstance(columns, Mapping) or not columns:
        raise ValidationError("row_group columns must be a non-empty mapping")
    headers = raw.get("column_headers") or {}
    if not isinstance(headers, Mapping):
        raise ValidationError("column_headers must be a mapping")
    return RowGroupSelector(
        row_group=str(raw["row_group"]),
        table_anchor=str(_require_key(raw, "table_anchor")),
        columns=MappingProxyType({str(k): str(v) for k, v in columns.items()}),
        column_headers=MappingProxyType({str(k): str(v) for k, v in headers.items()}),
        region=None if raw.get("region") is None else str(raw["region"]),
        sub_group=_parse_sub_group(raw.get("sub_group")),
        row_count=_parse_range(raw.get("row_count"), "row_count"),
        allow_empty_cells=bool(raw.get("allow_empty_cells", True)),
        require_amount=bool(raw.get("require_amount", False)),
        stop_at_subtotal=bool(raw.get("stop_at_subtotal", False)),
    )


def _parse_scanline(raw: Mapping[str, Any]) -> ScanlineSelector:
    asserts_raw = raw.get("asserts") or ()
    if not isinstance(asserts_raw, Sequence) or isinstance(asserts_raw, str):
        raise ValidationError("scanline asserts must be a list")
    asserts: list[ScanlineAssert] = []
    for item in asserts_raw:
        if not isinstance(item, Mapping):
            raise ValidationError("each scanline assert must be a mapping")
        asserts.append(
            ScanlineAssert(
                field=str(_require_key(item, "field")),
                as_form=str(item.get("as", "digits_only")),
            )
        )
    return ScanlineSelector(
        region=str(_require_key(raw, "region")),
        asserts=tuple(asserts),
    )


def parse_selector(raw: Mapping[str, Any]) -> Selector:
    """Dispatch on shape. `row_group` and `scanline` are the discriminants."""
    if not isinstance(raw, Mapping):
        raise ValidationError(f"each selector must be a mapping, got {type(raw).__name__}")
    if "row_group" in raw:
        return _parse_row_group(raw)
    if "scanline" in raw:
        return _parse_scanline(raw)
    if "field" in raw:
        return _parse_field_selector(raw)
    raise ValidationError(
        "unrecognized selector shape; section 1 defines exactly three kinds "
        "(field_selector, row_group_selector, scanline_selector)"
    )


def parse_layout_fingerprint(raw: Any) -> LayoutFingerprint:
    if raw is None:
        return LayoutFingerprint()
    if not isinstance(raw, Mapping):
        raise ValidationError("layout_fingerprint must be a mapping")

    role = raw.get("totals_page_role")
    if role is not None and role not in ("last", "first"):
        raise ValidationError(f"totals_page_role must be 'last' or 'first', got {role!r}")
    source = raw.get("text_source")
    if source is not None and source not in ("native", "ocr", "either"):
        raise ValidationError(
            f"fingerprint text_source must be 'native', 'ocr' or 'either', got {source!r}"
        )
    has_table = raw.get("has_table")

    return LayoutFingerprint(
        page_count=_parse_range(raw.get("page_count"), "page_count"),
        has_table=None if has_table is None else bool(has_table),
        header_signature=(
            None if raw.get("header_signature") is None else str(raw["header_signature"])
        ),
        totals_page_role=role,
        column_signature=_as_tuple(raw.get("column_signature")),
        text_source=source,
    )


def parse_persona(raw: Mapping[str, Any]) -> Persona:
    """Build a frozen `Persona` from a mapping that has already been validated.

    Accepts any `Mapping`, not only `dict`. The Part A ledger records a bug in
    exactly this shape - an `isinstance(x, dict)` check where a `Mapping` check
    was needed - which silently dropped values arriving as MappingProxyType.
    """
    if not isinstance(raw, Mapping):
        raise ValidationError(f"persona must be a mapping, got {type(raw).__name__}")

    status = _require_key(raw, "status")
    if status not in ("draft", "active"):
        raise ValidationError(f"persona status must be 'draft' or 'active', got {status!r}")

    selectors_raw = raw.get("field_selectors", ())
    if isinstance(selectors_raw, Mapping) or not isinstance(selectors_raw, Sequence):
        raise ValidationError("field_selectors must be a list of selectors")

    examples_raw = raw.get("few_shot_examples") or ()
    if isinstance(examples_raw, Mapping) or not isinstance(examples_raw, Sequence):
        raise ValidationError("few_shot_examples must be a list")

    return Persona(
        sender_fingerprint=str(_require_key(raw, "sender_fingerprint")),
        doc_type=str(_require_key(raw, "doc_type")),
        rule_version=str(_require_key(raw, "rule_version")),
        status=status,
        field_selectors=tuple(parse_selector(s) for s in selectors_raw),
        layout_fingerprint=parse_layout_fingerprint(raw.get("layout_fingerprint")),
        few_shot_examples=tuple(
            MappingProxyType(dict(e)) for e in examples_raw if isinstance(e, Mapping)
        ),
    )
