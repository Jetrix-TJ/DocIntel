"""V1-V13, the persona-write security boundary (selector-grammar.md section 8).

From the spec's own framing: "The validator is the security boundary. There is
no sandbox because there is nothing to sandbox. If the validator accepts
something it shouldn't, that is the whole vulnerability class."

The V1-V13 block below is carried over verbatim from the implementation plan;
the tests after it cover the rules the plan's block did not reach.
"""

from __future__ import annotations

from typing import Any

import pytest

from docintel.core.errors import ValidationError
from docintel.grammar.validator import undeclared_risk_fields, validate_persona


def _base(**over: Any) -> dict[str, Any]:
    p = {
        "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
        "rule_version": "v1", "status": "draft", "field_selectors": [],
        "layout_fingerprint": {},
    }
    p.update(over)
    return p


class FakePack:
    """Minimal Pack for the pack-dependent rules. The real registry is C5a."""

    name = "fake"

    def __init__(
        self,
        fields: set[str] | None = None,
        required: set[str] | None = None,
        derived_only: set[str] | None = None,
        ops: set[str] | None = None,
        any_of: tuple[frozenset[str], ...] = (),
    ) -> None:
        self._fields = frozenset(fields or {"total_printed", "vendor_name", "invoice_number"})
        self._required = frozenset(required or set())
        self._derived_only = frozenset(derived_only or set())
        self._ops = frozenset(ops or set())
        self._any_of = any_of

    def fields_for(self, doc_type: str) -> frozenset[str]:
        return self._fields

    def required_fields(self, doc_type: str) -> frozenset[str]:
        return self._required

    def required_any_of(self, doc_type: str) -> tuple[frozenset[str], ...]:
        return self._any_of

    def derived_only_fields(self, doc_type: str) -> frozenset[str]:
        return self._derived_only

    def adjust_ops(self) -> frozenset[str]:
        return self._ops


# ==========================================================================
# The plan's V1-V13 block, verbatim
# ==========================================================================


def test_V10_selector_may_not_target_amount_payable() -> None:
    """The single easiest way to reintroduce the F1 bug."""
    p = _base(field_selectors=[
        {"field": "amount_payable", "anchor": "Total Amount Due",
         "region": "totals-block", "pattern": "currency"}
    ])
    with pytest.raises(ValidationError, match="derived_only"):
        validate_persona(p, pack=None)


def test_V7_scanline_may_not_assert_amount_payable() -> None:
    """Centracom's scanline encodes the trap value (F7)."""
    p = _base(field_selectors=[
        {"scanline": True, "region": "remittance-block",
         "asserts": [{"field": "amount_payable", "as": "digits_no_decimal"}]}
    ])
    with pytest.raises(ValidationError, match="amount_payable"):
        validate_persona(p, pack=None)


def test_V6_bare_digit_regex_needs_a_narrowing_region() -> None:
    p = _base(field_selectors=[
        {"field": "reference", "region": "any-page", "pattern": r"(\d{7})"}
    ])
    with pytest.raises(ValidationError, match="narrowing region"):
        validate_persona(p, pack=None)


def test_V4_unbounded_quantifier_is_rejected() -> None:
    p = _base(field_selectors=[
        {"field": "vendor_name", "region": "header-block", "pattern": ".*"}
    ])
    with pytest.raises(ValidationError, match="unbounded"):
        validate_persona(p, pack=None)


def test_V3_unknown_region_is_rejected() -> None:
    p = _base(field_selectors=[
        {"field": "total_printed", "region": "middle-ish", "pattern": "currency"}
    ])
    with pytest.raises(ValidationError, match="region"):
        validate_persona(p, pack=None)


def test_V8_sub_group_nesting_depth_is_capped_at_one() -> None:
    p = _base(field_selectors=[{
        "row_group": "line_items", "table_anchor": "Description",
        "columns": {"amount": "currency"},
        "sub_group": {"anchor": "WORK ORDER#:", "field": "work_order",
                      "pattern": r"(\d{7})",
                      "sub_group": {"anchor": "x", "field": "y", "pattern": "z"}},
    }])
    with pytest.raises(ValidationError, match="nesting"):
        validate_persona(p, pack=None)


def test_V9_row_count_must_be_a_range() -> None:
    p = _base(field_selectors=[{
        "row_group": "line_items", "table_anchor": "Description",
        "columns": {"amount": "currency"}, "row_count": 10,
    }])
    with pytest.raises(ValidationError, match="range"):
        validate_persona(p, pack=None)


def test_V11_persona_over_64kb_is_rejected() -> None:
    p = _base(few_shot_examples=[{"blob": "x" * 70_000}])
    with pytest.raises(ValidationError, match="64"):
        validate_persona(p, pack=None)


def test_V12_few_shot_examples_capped_at_three() -> None:
    p = _base(few_shot_examples=[{}, {}, {}, {}])
    with pytest.raises(ValidationError, match="few_shot"):
        validate_persona(p, pack=None)


def test_a_valid_persona_passes() -> None:
    validate_persona(_base(field_selectors=[
        {"field": "total_printed", "anchor": "Total Amount Due",
         "region": "totals-block", "pattern": "currency"}
    ]), pack=None)


def test_rejection_is_all_or_nothing() -> None:
    """A persona is never half-migrated to a bad rule set."""
    p = _base(field_selectors=[
        {"field": "total_printed", "region": "totals-block", "pattern": "currency"},
        {"field": "amount_payable", "region": "totals-block", "pattern": "currency"},
    ])
    with pytest.raises(ValidationError):
        validate_persona(p, pack=None)


# ==========================================================================
# The rules the plan's block did not reach
# ==========================================================================

# --- V1: every field is in the pack's registered field set -----------------


def test_V1_unregistered_field_is_rejected() -> None:
    p = _base(field_selectors=[
        {"field": "favourite_colour", "region": "header-block", "pattern": "text"}
    ])
    with pytest.raises(ValidationError, match="not a registered field"):
        validate_persona(p, pack=FakePack())


def test_V1_is_skipped_without_a_pack() -> None:
    """`pack=None` means "cannot check", which must not mean "reject".

    Grammar-only validation is genuinely useful on its own - it is what the
    grammar tests and the persona-authoring tools use - and conflating an
    unknown field set with a bad one would make that impossible.
    """
    validate_persona(_base(field_selectors=[
        {"field": "favourite_colour", "region": "header-block", "pattern": "text"}
    ]), pack=None)


def test_V1_applies_to_row_group_and_sub_group_fields_too() -> None:
    p = _base(field_selectors=[{
        "row_group": "line_items", "table_anchor": "Description",
        "columns": {"amount": "currency"},
        "sub_group": {"anchor": "WORK ORDER#:", "field": "not_a_field",
                      "pattern": r"WO\s?(\d{7})"},
    }])
    with pytest.raises(ValidationError, match="not a registered field"):
        validate_persona(p, pack=FakePack())


# --- V2: every adjust op is registered -------------------------------------


def test_V2_unregistered_adjust_op_is_rejected() -> None:
    """The agent may reference an op; it may never define one."""
    p = _base(field_selectors=[
        {"field": "total_printed", "region": "totals-block", "pattern": "currency",
         "adjust": ["strip_currency_symbols", "invent_a_number"]}
    ])
    with pytest.raises(ValidationError, match="invent_a_number"):
        validate_persona(p, pack=None)


def test_V2_base_ops_need_no_pack() -> None:
    validate_persona(_base(field_selectors=[
        {"field": "total_printed", "region": "totals-block", "pattern": "currency",
         "adjust": ["strip_currency_symbols", "derive_amount_payable"]}
    ]), pack=None)


def test_V2_pack_registered_ops_are_accepted() -> None:
    p = _base(field_selectors=[
        {"field": "total_printed", "region": "totals-block", "pattern": "currency",
         "adjust": ["northstar_special"]}
    ])
    validate_persona(p, pack=FakePack(ops={"northstar_special"}))
    with pytest.raises(ValidationError, match="northstar_special"):
        validate_persona(p, pack=FakePack())


# --- V3: regions ----------------------------------------------------------


def test_V3_accepts_every_name_in_the_enum() -> None:
    from docintel.grammar.regions import RESOLVERS

    for region in (*RESOLVERS, "page:1", "page:12"):
        validate_persona(_base(field_selectors=[
            {"field": "total_printed", "anchor": "Total", "region": region,
             "pattern": "currency"}
        ]), pack=None)


def test_V3_rejects_a_row_groups_region_too() -> None:
    p = _base(field_selectors=[{
        "row_group": "line_items", "table_anchor": "D", "region": "middle-ish",
        "columns": {"amount": "currency"},
    }])
    with pytest.raises(ValidationError, match="region"):
        validate_persona(p, pack=None)


def test_V3_rejects_a_scanlines_region_too() -> None:
    p = _base(field_selectors=[
        {"scanline": True, "region": "middle-ish",
         "asserts": [{"field": "total_printed", "as": "digits_only"}]}
    ])
    with pytest.raises(ValidationError, match="region"):
        validate_persona(p, pack=None)


# --- V4: patterns ---------------------------------------------------------


def test_V4_accepts_every_named_pattern() -> None:
    from docintel.grammar.patterns import NAMED

    for name in NAMED:
        validate_persona(_base(field_selectors=[
            {"field": "total_printed", "anchor": "Total", "region": "totals-block",
             "pattern": name}
        ]), pack=None)


def test_V4_treats_an_unknown_pattern_name_as_a_regex() -> None:
    """A typo'd pattern name is NOT caught here, and that is a real limitation.

    `currancy` is a syntactically valid regex matching the literal text
    "currancy", so V4 accepts it and the selector then misses on every
    document. The grammar cannot distinguish a typo from a deliberate literal
    matcher (`BALANCE FORWARD` is exactly that shape and is legitimate). What
    catches this is the eval attached to the persona write, not the validator.
    """
    p = _base(field_selectors=[
        {"field": "total_printed", "region": "totals-block", "pattern": "currancy"}
    ])
    validate_persona(p, pack=None)


def test_V4_applies_to_row_group_column_patterns() -> None:
    p = _base(field_selectors=[{
        "row_group": "line_items", "table_anchor": "D",
        "columns": {"amount": ".*"},
    }])
    with pytest.raises(ValidationError, match="unbounded"):
        validate_persona(p, pack=None)


def test_V4_applies_to_sub_group_patterns() -> None:
    p = _base(field_selectors=[{
        "row_group": "line_items", "table_anchor": "D",
        "columns": {"amount": "currency"},
        "sub_group": {"anchor": "WO:", "field": "work_order", "pattern": ".+"},
    }])
    with pytest.raises(ValidationError, match="unbounded"):
        validate_persona(p, pack=None)


def test_V4_backreference_is_rejected() -> None:
    p = _base(field_selectors=[
        {"field": "total_printed", "region": "totals-block", "pattern": r"(a)\1"}
    ])
    with pytest.raises(ValidationError, match="backreference"):
        validate_persona(p, pack=None)


# --- V5: a selector needs a region ----------------------------------------


def test_V5_a_field_selector_without_a_region_is_rejected() -> None:
    """Section 1.1 makes `region` "required unless the anchor is provably
    unique". Uniqueness is a property of a document, not of the persona, so it
    cannot be proven at write time - the honest static rule is that `region` is
    always required. A persona that genuinely has a unique anchor loses
    nothing by naming `any-page` explicitly."""
    p = _base(field_selectors=[
        {"field": "total_printed", "anchor": "Total Amount Due", "pattern": "currency"}
    ])
    with pytest.raises(ValidationError, match="region"):
        validate_persona(p, pack=None)


def test_V5_a_scanline_without_a_region_is_rejected() -> None:
    p = _base(field_selectors=[
        {"scanline": True, "asserts": [{"field": "total_printed", "as": "digits_only"}]}
    ])
    with pytest.raises(ValidationError, match="region"):
        validate_persona(p, pack=None)


# --- V6: bare-digit patterns ----------------------------------------------


def test_V6_a_bare_digit_regex_is_fine_with_a_narrowing_region() -> None:
    validate_persona(_base(field_selectors=[
        {"field": "reference", "region": "header-block", "pattern": r"(\d{7})"}
    ]), pack=None)


def test_V6_an_anchor_relative_region_also_narrows() -> None:
    """`same-row` narrows too, but it needs the anchor it is defined against."""
    validate_persona(_base(field_selectors=[
        {"field": "reference", "anchor": "NS #", "region": "same-row",
         "pattern": r"(\d{7})"}
    ]), pack=None)


def test_an_anchor_relative_region_without_an_anchor_is_rejected() -> None:
    """`near-anchor` with nothing to be near cannot resolve at run time, so it is
    a write-time error rather than a silent field miss on every document."""
    p = _base(field_selectors=[
        {"field": "service_location", "region": "near-anchor", "pattern": "text_block"}
    ])
    with pytest.raises(ValidationError, match="anchor"):
        validate_persona(p, pack=None)


def test_V6_a_bare_digit_regex_is_fine_with_column_headers() -> None:
    validate_persona(_base(field_selectors=[{
        "row_group": "line_items", "table_anchor": "D",
        "columns": {"work_order": r"(\d{7})"},
        "column_headers": {"work_order": "WORK ORDER#"},
    }]), pack=None)


def test_V6_a_bare_digit_column_without_headers_is_rejected() -> None:
    p = _base(field_selectors=[{
        "row_group": "line_items", "table_anchor": "D",
        "columns": {"work_order": r"(\d{7})"},
    }])
    with pytest.raises(ValidationError, match="narrowing region"):
        validate_persona(p, pack=None)


@pytest.mark.parametrize("pattern", [
    r"(\d{7})", r"\d{5,9}", r"(\d{3}-\d{4})", r"[0-9]{7}", r"(\d\d\d\d\d\d\d)",
])
def test_V6_recognizes_every_bare_digit_form(pattern: str) -> None:
    """F11: unscoped, these match phone numbers and zip+4. A dash or a space is
    not literal context - `(\\d{3}-\\d{4})` is exactly a phone number."""
    p = _base(field_selectors=[
        {"field": "reference", "region": "any-page", "pattern": pattern}
    ])
    with pytest.raises(ValidationError, match="narrowing region"):
        validate_persona(p, pack=None)


@pytest.mark.parametrize("pattern", [
    r"NS\s?#\s?(\d{7})", r"Invoice\s(\d{5,9})", r"WO(\d{7})",
])
def test_V6_literal_text_context_is_not_a_bare_digit_pattern(pattern: str) -> None:
    validate_persona(_base(field_selectors=[
        {"field": "reference", "region": "any-page", "pattern": pattern}
    ]), pack=None)


def test_V6_does_not_fire_on_named_patterns() -> None:
    """`integer` on `any-page` is a judgement call, not a grammar violation."""
    validate_persona(_base(field_selectors=[
        {"field": "reference", "region": "any-page", "pattern": "integer"}
    ]), pack=None)


# --- V7: scanline asserts -------------------------------------------------


@pytest.mark.parametrize("field", ["total_printed", "account_number",
                                   "invoice_number", "due_date"])
def test_V7_permits_the_four_named_fields(field: str) -> None:
    validate_persona(_base(field_selectors=[
        {"scanline": True, "region": "remittance-block",
         "asserts": [{"field": field, "as": "digits_only"}]}
    ]), pack=None)


@pytest.mark.parametrize("field", ["current_charges", "prior_balance",
                                   "vendor_name", "subtotal"])
def test_V7_rejects_everything_else(field: str) -> None:
    """Narrow by enumeration, not by exclusion: `current_charges` is named in the
    spec, but so is the principle that the set is closed."""
    p = _base(field_selectors=[
        {"scanline": True, "region": "remittance-block",
         "asserts": [{"field": field, "as": "digits_only"}]}
    ])
    with pytest.raises(ValidationError, match="scanline"):
        validate_persona(p, pack=None)


@pytest.mark.parametrize("region", ["last-page", "remittance-block", "page:1", "page:5"])
def test_a_scanline_may_be_sought_in_the_stub_regions(region: str) -> None:
    validate_persona(_base(field_selectors=[
        {"scanline": True, "region": region,
         "asserts": [{"field": "total_printed", "as": "digits_only"}]}
    ]), pack=None)


@pytest.mark.parametrize("region", ["header-block", "totals-block", "any-page",
                                    "top-left", "line_items"])
def test_a_scanline_may_not_be_sought_anywhere_else(region: str) -> None:
    """Section 1.3 writes the scanline's region as its own narrower enum. An
    OCR-A remittance line is a physical feature of the payment stub, so a
    persona claiming one in a header block describes something that cannot
    exist - and the spec's whole position is that closed vocabularies are
    rejected at write time, not discovered at run time."""
    p = _base(field_selectors=[
        {"scanline": True, "region": region,
         "asserts": [{"field": "total_printed", "as": "digits_only"}]}
    ])
    with pytest.raises(ValidationError, match="scanline"):
        validate_persona(p, pack=None)


def test_V7_rejects_an_unknown_as_form() -> None:
    p = _base(field_selectors=[
        {"scanline": True, "region": "remittance-block",
         "asserts": [{"field": "total_printed", "as": "base64"}]}
    ])
    with pytest.raises(ValidationError, match="base64"):
        validate_persona(p, pack=None)


# --- V9: row_count --------------------------------------------------------


def test_V9_a_min_max_range_is_accepted() -> None:
    validate_persona(_base(field_selectors=[{
        "row_group": "line_items", "table_anchor": "D",
        "columns": {"amount": "currency"}, "row_count": {"min": 1, "max": 40},
    }]), pack=None)


def test_V9_an_inverted_range_is_rejected() -> None:
    p = _base(field_selectors=[{
        "row_group": "line_items", "table_anchor": "D",
        "columns": {"amount": "currency"}, "row_count": {"min": 40, "max": 1},
    }])
    with pytest.raises(ValidationError, match="range"):
        validate_persona(p, pack=None)


def test_V9_a_min_only_range_is_rejected() -> None:
    p = _base(field_selectors=[{
        "row_group": "line_items", "table_anchor": "D",
        "columns": {"amount": "currency"}, "row_count": {"min": 1},
    }])
    with pytest.raises(ValidationError, match="range"):
        validate_persona(p, pack=None)


# --- V10: derived_only ----------------------------------------------------


@pytest.mark.parametrize("field", sorted({
    "amount_payable", "payable_basis", "document_identity",
    "identity_basis", "carried_balance",
}))
def test_V10_covers_every_derived_only_field(field: str) -> None:
    """V10 reads its set from core.models.DERIVED_ONLY, so the two cannot drift."""
    p = _base(field_selectors=[
        {"field": field, "region": "totals-block", "pattern": "currency"}
    ])
    with pytest.raises(ValidationError, match="derived_only"):
        validate_persona(p, pack=None)


def test_V10_applies_to_row_group_columns() -> None:
    """A column named amount_payable is the same footgun wearing a hat."""
    p = _base(field_selectors=[{
        "row_group": "line_items", "table_anchor": "D",
        "columns": {"amount_payable": "currency"},
    }])
    with pytest.raises(ValidationError, match="derived_only"):
        validate_persona(p, pack=None)


def test_V10_applies_to_sub_group_fields() -> None:
    p = _base(field_selectors=[{
        "row_group": "line_items", "table_anchor": "D",
        "columns": {"amount": "currency"},
        "sub_group": {"anchor": "WO:", "field": "amount_payable", "pattern": "currency"},
    }])
    with pytest.raises(ValidationError, match="derived_only"):
        validate_persona(p, pack=None)


def test_V10_honours_a_pack_specific_derived_only_field() -> None:
    p = _base(field_selectors=[
        {"field": "allocation_key", "region": "totals-block", "pattern": "text"}
    ])
    pack = FakePack(fields={"allocation_key"}, derived_only={"allocation_key"})
    with pytest.raises(ValidationError, match="derived_only"):
        validate_persona(p, pack=pack)


# --- V11 / V12 ------------------------------------------------------------


def test_V11_a_persona_just_under_the_limit_passes() -> None:
    validate_persona(_base(few_shot_examples=[{"blob": "x" * 60_000}]), pack=None)


def test_V12_exactly_three_examples_pass() -> None:
    validate_persona(_base(few_shot_examples=[{}, {}, {}]), pack=None)


def test_V12_an_example_from_a_flattened_annotation_document_is_rejected() -> None:
    """F3: Federal Recycling's colored fills are invisible to the text layer, so
    a few-shot example drawn from it teaches the wrong lesson confidently."""
    p = _base(few_shot_examples=[
        {"document_id": "d1", "source_tags": ["ocr_only", "flattened_annotations"]}
    ])
    with pytest.raises(ValidationError, match="flattened_annotations"):
        validate_persona(p, pack=None)


# --- V13: required fields need selectors before leaving draft --------------


def test_V13_an_active_persona_missing_a_required_field_is_rejected() -> None:
    p = _base(status="active", field_selectors=[
        {"field": "total_printed", "region": "totals-block", "pattern": "currency"}
    ])
    pack = FakePack(required={"total_printed", "vendor_name"})
    with pytest.raises(ValidationError, match="vendor_name"):
        validate_persona(p, pack=pack)


def test_V13_a_draft_persona_may_be_incomplete() -> None:
    """Draft is how a persona gets built up over successive writes."""
    p = _base(status="draft", field_selectors=[
        {"field": "total_printed", "region": "totals-block", "pattern": "currency"}
    ])
    validate_persona(p, pack=FakePack(required={"total_printed", "vendor_name"}))


def test_V13_an_active_persona_with_every_required_field_passes() -> None:
    p = _base(status="active", field_selectors=[
        {"field": "total_printed", "region": "totals-block", "pattern": "currency"},
        {"field": "vendor_name", "region": "header-block", "pattern": "text"},
    ])
    validate_persona(p, pack=FakePack(required={"total_printed", "vendor_name"}))


def test_V13_a_derived_only_required_field_needs_no_selector() -> None:
    """amount_payable is required AND derived_only. V13 must not demand a
    selector for it, or V10 and V13 would make the persona unwritable."""
    p = _base(status="active", field_selectors=[
        {"field": "total_printed", "region": "totals-block", "pattern": "currency"},
    ])
    pack = FakePack(
        fields={"total_printed", "amount_payable"},
        required={"total_printed", "amount_payable"},
        derived_only={"amount_payable"},
    )
    validate_persona(p, pack=pack)


def test_V13_a_row_group_column_satisfies_a_required_field() -> None:
    p = _base(status="active", field_selectors=[{
        "row_group": "line_items", "table_anchor": "D",
        "columns": {"description": "text", "amount": "currency"},
        "column_headers": {"amount": "CHARGES"},
    }])
    pack = FakePack(fields={"description", "amount"}, required={"amount"})
    validate_persona(p, pack=pack)


def test_v13_any_of_passes_when_one_group_member_is_covered() -> None:
    """EDCO's shape: a bill_date selector and no invoice_date."""
    pack = FakePack(
        fields={"bill_date", "invoice_date", "total_printed"},
        required=frozenset(),
        any_of=(frozenset({"invoice_date", "bill_date"}),),
    )
    persona = {
        "status": "active",
        "doc_type": "standard_invoice",
        "field_selectors": [
            {"field": "bill_date", "region": "top-right", "pattern": "date"},
        ],
    }
    validate_persona(persona, pack)  # must not raise


def test_v13_any_of_fails_when_no_group_member_is_covered() -> None:
    pack = FakePack(
        fields={"bill_date", "invoice_date", "total_printed"},
        required=frozenset(),
        any_of=(frozenset({"invoice_date", "bill_date"}),),
    )
    persona = {
        "status": "active",
        "doc_type": "standard_invoice",
        "field_selectors": [
            {"field": "total_printed", "region": "first-page", "pattern": "currency"},
        ],
    }
    with pytest.raises(ValidationError, match="any of"):
        validate_persona(persona, pack)


def test_v13_any_of_is_skipped_for_draft_personas() -> None:
    pack = FakePack(
        fields={"invoice_date", "bill_date"},
        required=frozenset(),
        any_of=(frozenset({"invoice_date", "bill_date"}),),
    )
    persona = {"status": "draft", "doc_type": "standard_invoice", "field_selectors": []}
    validate_persona(persona, pack)  # must not raise


def test_v13_any_of_group_of_only_derived_names_is_not_a_trap() -> None:
    """A group whose every member is derived-only cannot be satisfied by any
    selector, so it must be skipped rather than making the persona unwritable -
    the same reasoning that exempts derived-only names from flat REQUIRED."""
    pack = FakePack(
        fields={"total_printed"},
        required=frozenset(),
        any_of=(frozenset({"amount_payable", "carried_balance"}),),
    )
    persona = {
        "status": "active",
        "doc_type": "standard_invoice",
        "field_selectors": [
            {"field": "total_printed", "region": "first-page", "pattern": "currency"},
        ],
    }
    validate_persona(persona, pack)  # must not raise


# --- structural / whole-persona -------------------------------------------


def test_a_non_mapping_persona_is_rejected() -> None:
    with pytest.raises(ValidationError, match="mapping"):
        validate_persona(["not", "a", "persona"], pack=None)  # type: ignore[arg-type]


def test_a_persona_missing_status_is_rejected() -> None:
    p = _base()
    del p["status"]
    with pytest.raises(ValidationError, match="status"):
        validate_persona(p, pack=None)


def test_the_worked_edco_example_from_section_nine_validates() -> None:
    """The persona the spec itself puts forward as correct must pass.

    This is the end-to-end check on the whole rule set: if section 9's worked
    example cannot be written, the grammar is wrong, not the example.

    SPEC ERRATUM: section 9 asserts `invoice_account` in its scanline, but
    section 1.3's permitted set is `total_printed`, `account_number`,
    `invoice_number`, `due_date`. Section 1.3 is normative and load-bearing
    (it is what stops the F1 bug being cemented via F7), while section 9's
    field naming is illustrative and already diverges from the Northstar pack
    elsewhere (`invoice_account` vs `vendor_account_number`, `bill_date` vs
    `invoice_date`). Read as a typo for `account_number` and reproduced here
    with the normative name.
    """
    edco = {
        "sender_fingerprint": "edcodisposal.com|edco waste & recycling service",
        "doc_type": "standard_invoice",
        "rule_version": "v1",
        "status": "draft",
        "field_selectors": [
            {"field": "invoice_account", "anchor": "Account Number",
             "region": "header-block", "pattern": "account_number",
             "adjust": ["strip_internal_whitespace"]},
            {"field": "bill_date", "anchor": "Billing Date",
             "region": "header-block", "pattern": "date",
             "adjust": ["normalize_date_iso"]},
            {"field": "total_printed", "anchor": "Total Amount Due",
             "anchor_alts": ["Amount Due"],
             "region": "totals-block", "pattern": "currency",
             "adjust": ["crosscheck_scanline", "crosscheck_duplicate_anchor"]},
            {"field": "prior_balance", "anchor": "BALANCE FORWARD",
             "region": "line_items", "pattern": "currency", "required": False},
            {"field": "current_charges", "anchor": "CURRENT CHARGES:",
             "anchor_alts": ["CURRENT CHARGES", "Current Charges"],
             "region": "line_items", "pattern": "currency",
             "adjust": ["derive_amount_payable", "crosscheck_balance_composition"]},
            {"field": "service_location", "anchor": "FOR SERVICE AT:",
             "region": "near-anchor", "pattern": "text_block"},
            {"field": "bill_to_name", "anchor": "SEND PAYMENT TO:",
             "region": "header-block", "pattern": "text_block", "required": False},
            {"row_group": "line_items", "table_anchor": "DESCRIPTION",
             "column_headers": {"description": "DESCRIPTION", "charges": "CHARGES",
                                "payments": "PAYMENTS", "balance": "BALANCE"},
             "columns": {"description": "text", "charges": "currency",
                         "payments": "currency", "balance": "currency"},
             "row_count": {"min": 1, "max": 40}, "allow_empty_cells": True},
            {"scanline": True, "region": "remittance-block",
             "asserts": [{"field": "total_printed", "as": "digits_no_decimal"},
                         {"field": "account_number", "as": "digits_only"}]},
        ],
        "layout_fingerprint": {
            "page_count": {"min": 1, "max": 2}, "has_table": True,
            "header_signature": "vendor-left|boxes-right",
            "totals_page_role": "first", "text_source": "native",
            "column_signature": ["DESCRIPTION", "CHARGES", "PAYMENTS", "BALANCE"],
        },
    }
    validate_persona(edco, pack=None)


# ==========================================================================
# V14: a literal capture must say WHERE, not just WHAT
# ==========================================================================
#
# The rule V6 already states in the other direction. V6 says a pattern with no
# literal text needs a narrowing region, because a bare digit run matches phone
# numbers. V14 says the converse: a pattern that captures nothing BUT literal text
# needs a narrowing region or an anchor, because a capture with no shape to it is a
# restatement of one document's answer rather than a description of where the value
# lives.
#
# Measured motivation: 19 of 118 shipped field rules were such literals, and on
# three of four telecom carriers the hardcoded value was `bill_to_name` - a field
# whose value is a different managed client on every document. Since extraction
# completeness now routes a missing required field to `review`, a literal there does
# not merely fail, it sends 100% of a newly onboarded client's invoices to manual
# review. The blast radius grew, which is why this is a validator rule and not a
# style note.


def test_a_literal_capture_on_a_whole_page_region_is_rejected() -> None:
    """The shape that broke: nothing about position, everything about content."""
    with pytest.raises(ValidationError, match="V14"):
        validate_persona(_base(field_selectors=[
            {"field": "bill_to_name", "region": "any-page",
             "pattern": "(CITY OF DUBLIN)"},
        ]), pack=None)


def test_a_literal_capture_is_allowed_when_an_anchor_places_it() -> None:
    """With an anchor the persona has made a claim about location, and the literal
    is confirming what should be found there rather than standing in for it."""
    validate_persona(_base(field_selectors=[
        {"field": "vendor_name", "anchor": "Remit to", "region": "near-anchor",
         "pattern": "(ACME HAULING)"},
    ]), pack=None)


def test_a_literal_capture_is_allowed_when_the_region_narrows() -> None:
    """`top-left` is a positional claim: the vendor's own name on its own
    letterhead is invariant across that vendor's documents, and where it is
    printed is the real content of the rule."""
    validate_persona(_base(field_selectors=[
        {"field": "vendor_name", "region": "top-left", "pattern": "(CENTRACOM)"},
    ]), pack=None)


def test_a_shape_capture_needs_no_positional_help() -> None:
    """A pattern describing FORM generalises by construction, so V14 has no
    opinion about where it is applied."""
    validate_persona(_base(field_selectors=[
        {"field": "invoice_number", "region": "any-page",
         "pattern": "(715-[0-9]{8})"},
    ]), pack=None)


def test_an_inline_label_does_not_excuse_a_literal_capture() -> None:
    """`payable to (Comcast)` reads as anchored, but the CAPTURE is still one
    vendor's name. The label belongs in `anchor`, where the grammar can see it -
    hiding it in the pattern buys the appearance of a location claim without one."""
    with pytest.raises(ValidationError, match="V14"):
        validate_persona(_base(field_selectors=[
            {"field": "remit_payee", "region": "any-page",
             "pattern": "payable to (Comcast)"},
        ]), pack=None)


def test_a_named_pattern_is_never_a_literal() -> None:
    """`text` and `text_block` capture whatever is there; they are the opposite of
    a content assertion and must not be caught by this rule."""
    validate_persona(_base(field_selectors=[
        {"field": "vendor_name", "region": "any-page", "pattern": "text"},
    ]), pack=None)


def test_an_anchor_may_not_restate_a_value_captured_elsewhere() -> None:
    """The residual half of the same mistake, and the only part of it that is
    decidable at write time.

    An anchor is a literal string by nature, so `Account Name:` and
    `CLYDE COMPANIES` are indistinguishable to the validator - except when the
    same persona also captures that string as a field value. Then the persona has
    told us itself that the string is a value, and anchoring on it keys the rule
    to one document just as surely as the pattern did.
    """
    with pytest.raises(ValidationError, match="V14"):
        validate_persona(_base(field_selectors=[
            {"field": "bill_to_attention", "region": "top-left",
             "pattern": "(ATTN CLYDE COMPANIES-IT)"},
            {"field": "bill_to_address", "anchor": "ATTN CLYDE COMPANIES-IT",
             "region": "label-block", "pattern": "text_block"},
        ]), pack=None)


# ==========================================================================
# V13 and the fields an op supplies
# ==========================================================================


def test_a_required_field_an_op_supplies_needs_no_selector() -> None:
    """V13 asks that every required field be *covered*, not that it be selected.

    `amount_payable` was already exempt on those grounds - it is required and V10
    forbids selecting it, so demanding a selector made V10 and V13 jointly
    unsatisfiable. A field an `adjust` op supplies from a pack table is the same
    situation arrived at from the other direction: two of the four telecom
    templates print their bill-to with no label, so `resolve_bill_to_alias` reads
    it from the pack roster and no selector can or should exist.
    """
    validate_persona(_base(status="active", field_selectors=[
        {"field": "total_printed", "anchor": "Total", "region": "near-anchor",
         "pattern": "currency", "adjust": ["resolve_bill_to_alias"]},
    ]), pack=FakePack(fields={"total_printed", "bill_to_name"},
                      required={"bill_to_name"},
                      ops={"resolve_bill_to_alias"}))


def test_a_required_field_with_neither_selector_nor_op_still_fails_v13() -> None:
    """The exemption is specific to what an op actually supplies. Without the op
    the persona has simply not covered the field, and V13 must still say so."""
    with pytest.raises(ValidationError, match="V13"):
        validate_persona(_base(status="active", field_selectors=[
            {"field": "total_printed", "anchor": "Total", "region": "near-anchor",
             "pattern": "currency"},
        ]), pack=FakePack(fields={"total_printed", "bill_to_name"},
                          required={"bill_to_name"}))


# ==========================================================================
# undeclared_risk_fields: the authoring-time warning behind the s7_gate blind
# spot. Non-fatal by construction - see the function's own docstring for why
# this must never become a V-numbered hard failure.
# ==========================================================================


def test_undeclared_risk_fields_flags_an_optional_money_field_with_no_selector_and_no_op() -> None:
    pack = FakePack(
        fields={"bill_to_name", "subtotal", "total_printed"},
        required={"bill_to_name"},
    )
    persona = {
        "doc_type": "standard_invoice",
        "field_selectors": [
            {"field": "bill_to_name", "region": "top-left", "pattern": "text"},
            {"field": "total_printed", "anchor": "Total", "region": "near-anchor",
             "pattern": "currency"},
            # subtotal has NO selector at all
        ],
    }
    risky = undeclared_risk_fields(persona, pack)
    assert risky == ["subtotal"]


def test_undeclared_risk_fields_does_not_flag_a_field_an_op_supplies() -> None:
    """vendor_name is exactly what `resolve_vendor_alias` supplies (schema.py):
    Lumen's letterhead is an image and Windstream's text layer breaks the brand
    mid-word, so no selector can or should exist for it - it must not be flagged."""
    pack = FakePack(fields={"vendor_name"})
    persona = {
        "doc_type": "standard_invoice",
        "field_selectors": [
            {"field": "total_printed", "anchor": "Total", "region": "near-anchor",
             "pattern": "currency", "adjust": ["resolve_vendor_alias"]},
        ],
    }
    assert undeclared_risk_fields(persona, pack) == []


def test_undeclared_risk_fields_does_not_flag_a_required_field() -> None:
    """A required field with no selector is V13's job, not this warning's -
    flagging it too would be redundant noise on top of a hard failure."""
    pack = FakePack(fields={"bill_to_name"}, required={"bill_to_name"})
    persona = {"doc_type": "standard_invoice", "field_selectors": []}
    assert undeclared_risk_fields(persona, pack) == []


def test_undeclared_risk_fields_does_not_flag_a_derived_only_field() -> None:
    """amount_payable can never carry a selector (V10); it would be flagged on
    every persona ever written if this function didn't exempt it too."""
    pack = FakePack(
        fields={"amount_payable", "total_printed"},
        derived_only={"amount_payable"},
    )
    persona = {
        "doc_type": "standard_invoice",
        "field_selectors": [
            {"field": "total_printed", "anchor": "Total", "region": "near-anchor",
             "pattern": "currency"},
        ],
    }
    assert undeclared_risk_fields(persona, pack) == []


def test_undeclared_risk_fields_credits_a_row_group_column_as_covered() -> None:
    """A row_group column IS a selector for that field, and this warning must
    say so - `validate_persona`'s own V13 coverage check always counted it.

    The two disagreeing is not hypothetical: reading only scalar
    `sel["field"]` entries made this function report 49 at-risk fields on
    `northstar/complete_beverage.json`, a real, valid, shipped persona whose
    line-item money fields are row-group columns. Both now read the same
    `_covered_fields` collection.
    """
    pack = FakePack(fields={"total_printed", "quantity", "unit_price", "amount"})
    persona = {
        "doc_type": "standard_invoice",
        "field_selectors": [
            {"field": "total_printed", "anchor": "Total", "region": "near-anchor",
             "pattern": "currency"},
            {
                "row_group": "line_items",
                "table_anchor": "Description",
                "columns": {
                    "quantity": "integer",
                    "unit_price": "currency",
                    "amount": "currency",
                },
            },
        ],
    }
    assert undeclared_risk_fields(persona, pack) == []


def test_undeclared_risk_fields_credits_a_sub_group_field_as_covered() -> None:
    """Same argument one nesting level down (V8 permits exactly one): a
    sub_group's `field` is written by that selector, and `validate_persona`
    counts it toward V13 coverage, so this warning must not call it at risk."""
    pack = FakePack(fields={"total_printed", "amount", "service_date"})
    persona = {
        "doc_type": "standard_invoice",
        "field_selectors": [
            {"field": "total_printed", "anchor": "Total", "region": "near-anchor",
             "pattern": "currency"},
            {
                "row_group": "line_items",
                "table_anchor": "Description",
                "columns": {"amount": "currency"},
                "sub_group": {"field": "service_date", "pattern": "date"},
            },
        ],
    }
    assert undeclared_risk_fields(persona, pack) == []


def test_undeclared_risk_fields_still_flags_a_field_no_row_group_column_names() -> None:
    """The complement, so the fix above is a narrowing and not a blanket
    silencing: a field absent from every scalar selector AND every row_group
    column is still genuinely at risk of vanishing silently."""
    pack = FakePack(fields={"total_printed", "amount", "subtotal"})
    persona = {
        "doc_type": "standard_invoice",
        "field_selectors": [
            {"field": "total_printed", "anchor": "Total", "region": "near-anchor",
             "pattern": "currency"},
            {
                "row_group": "line_items",
                "table_anchor": "Description",
                "columns": {"amount": "currency"},
            },
            # subtotal is named nowhere - no scalar selector, no column
        ],
    }
    assert undeclared_risk_fields(persona, pack) == ["subtotal"]


def test_undeclared_risk_fields_does_not_credit_a_scanline_assert_as_coverage() -> None:
    """A scanline's `asserts` cross-check a value extracted elsewhere; they do
    not write it (see `_check_scanline` / V7). `validate_persona` never counted
    them toward coverage, so neither may this - crediting them would silence a
    warning about a field genuinely nothing extracts."""
    pack = FakePack(fields={"total_printed", "amount_payable_printed"})
    persona = {
        "doc_type": "standard_invoice",
        "field_selectors": [
            {"field": "total_printed", "anchor": "Total", "region": "near-anchor",
             "pattern": "currency"},
            {
                "scanline": True,
                "region": "payment-stub",
                "asserts": [{"field": "amount_payable_printed", "as": "digits_only"}],
            },
        ],
    }
    assert undeclared_risk_fields(persona, pack) == ["amount_payable_printed"]
