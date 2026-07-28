"""Persona data shapes (selector-grammar.md section 1) and the Pack seam.

`parse_persona` is the *typed constructor*, not the security boundary. It runs
after `validate_persona` has accepted the raw dict, so it is entitled to assume
the vocabularies are already checked. Everything it rejects is a structural
impossibility rather than a policy violation.
"""

from __future__ import annotations

import pytest

from docintel.core.errors import ValidationError
from docintel.grammar.schema import (
    BASE_ADJUST_OPS,
    FieldSelector,
    LayoutFingerprint,
    Persona,
    RowGroupSelector,
    ScanlineSelector,
    parse_persona,
)


def _base(**over: object) -> dict[str, object]:
    p: dict[str, object] = {
        "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
        "rule_version": "v1", "status": "draft", "field_selectors": [],
        "layout_fingerprint": {},
    }
    p.update(over)
    return p


# --------------------------------------------------------------------------
# The adjust-op enum
# --------------------------------------------------------------------------


def test_base_adjust_ops_are_the_closed_enum_from_section_4() -> None:
    """The op vocabulary is closed. C3 implements these; the validator needs
    only the names, so it can reject an unregistered op today."""
    assert BASE_ADJUST_OPS == frozenset({
        # 4.1 base
        "strip_internal_whitespace", "strip_currency_symbols", "parens_to_negative",
        "trailing_cr_to_negative", "normalize_date_iso", "uppercase", "lowercase",
        "trim", "collapse_internal_spaces", "dedupe_preserve_order",
        "join_lines_comma",
        # 4.2 derivation - the F1 machinery
        "derive_amount_payable", "resolve_carried_balance", "normalize_credit_sign",
        "subtract_prior_balance_if_present", "prefer_current_charges_line",
        # 4.3 consistency - scoring only
        "crosscheck_line_sum", "crosscheck_total_composition",
        "crosscheck_balance_composition", "crosscheck_scanline",
        "crosscheck_duplicate_anchor", "crosscheck_filename",
        # 4.4 inference
        "infer_currency", "resolve_vendor_alias",
    })
    assert len(BASE_ADJUST_OPS) == 24


# --------------------------------------------------------------------------
# parse_persona dispatch
# --------------------------------------------------------------------------


def test_parse_persona_returns_a_persona() -> None:
    persona = parse_persona(_base())
    assert isinstance(persona, Persona)
    assert persona.sender_fingerprint == "x|y"
    assert persona.doc_type == "standard_invoice"
    assert persona.rule_version == "v1"
    assert persona.status == "draft"
    assert persona.field_selectors == ()


def test_parse_persona_dispatches_on_selector_shape() -> None:
    """`row_group` and `scanline` are the discriminants; anything else is a field."""
    persona = parse_persona(_base(field_selectors=[
        {"field": "total_printed", "anchor": "Total Amount Due",
         "region": "totals-block", "pattern": "currency"},
        {"row_group": "line_items", "table_anchor": "DESCRIPTION",
         "columns": {"amount": "currency"}, "row_count": {"min": 1, "max": 40}},
        {"scanline": True, "region": "remittance-block",
         "asserts": [{"field": "total_printed", "as": "digits_no_decimal"}]},
    ]))
    kinds = [type(s) for s in persona.field_selectors]
    assert kinds == [FieldSelector, RowGroupSelector, ScanlineSelector]


def test_field_selector_defaults_match_the_spec() -> None:
    (sel,) = parse_persona(_base(field_selectors=[
        {"field": "vendor_name", "region": "header-block", "pattern": "text"},
    ])).field_selectors
    assert isinstance(sel, FieldSelector)
    assert sel.capture == "first"      # section 1.1 default
    assert sel.required is True        # section 1.1 default
    assert sel.adjust == ()
    assert sel.anchor is None
    assert sel.anchor_alts == ()


def test_adjust_accepts_a_bare_string_or_a_list() -> None:
    """Section 1.1 allows both; downstream should only ever see a tuple."""
    (one,) = parse_persona(_base(field_selectors=[
        {"field": "a", "region": "header-block", "pattern": "text", "adjust": "trim"},
    ])).field_selectors
    (many,) = parse_persona(_base(field_selectors=[
        {"field": "a", "region": "header-block", "pattern": "text",
         "adjust": ["trim", "uppercase"]},
    ])).field_selectors
    assert one.adjust == ("trim",)
    assert many.adjust == ("trim", "uppercase")


def test_row_group_defaults() -> None:
    (sel,) = parse_persona(_base(field_selectors=[
        {"row_group": "line_items", "table_anchor": "DESCRIPTION",
         "columns": {"amount": "currency"}},
    ])).field_selectors
    assert isinstance(sel, RowGroupSelector)
    assert sel.allow_empty_cells is True      # section 1.2 default, F15
    assert sel.sub_group is None
    assert sel.row_count is None
    assert sel.column_headers == {}


def test_row_group_columns_and_headers_are_read_only() -> None:
    """A parsed persona is a frozen contract; a stage must not edit it in place."""
    (sel,) = parse_persona(_base(field_selectors=[
        {"row_group": "line_items", "table_anchor": "D",
         "columns": {"amount": "currency"}, "column_headers": {"amount": "CHARGES"}},
    ])).field_selectors
    assert isinstance(sel, RowGroupSelector)
    with pytest.raises(TypeError):
        sel.columns["amount"] = "text"        # type: ignore[index]
    with pytest.raises(TypeError):
        sel.column_headers["amount"] = "X"    # type: ignore[index]


def test_scanline_selector_parses_its_asserts() -> None:
    (sel,) = parse_persona(_base(field_selectors=[
        {"scanline": True, "region": "remittance-block",
         "asserts": [{"field": "total_printed", "as": "digits_no_decimal"},
                     {"field": "invoice_number", "as": "digits_only"}]},
    ])).field_selectors
    assert isinstance(sel, ScanlineSelector)
    assert [a.field for a in sel.asserts] == ["total_printed", "invoice_number"]
    assert sel.asserts[0].as_form == "digits_no_decimal"


def test_persona_is_frozen() -> None:
    persona = parse_persona(_base())
    with pytest.raises(Exception):
        persona.status = "active"  # type: ignore[misc]


# --------------------------------------------------------------------------
# Layout fingerprint - section 6
# --------------------------------------------------------------------------


def test_layout_fingerprint_parses_the_section_six_shape() -> None:
    fp = parse_persona(_base(layout_fingerprint={
        "page_count": {"min": 1, "max": 6},
        "has_table": True,
        "header_signature": "logo-left|addr-right",
        "totals_page_role": "last",
        "column_signature": ["Description", "Qty", "Rate", "Amount"],
        "text_source": "native",
    })).layout_fingerprint
    assert isinstance(fp, LayoutFingerprint)
    assert fp.page_count == (1, 6)
    assert fp.has_table is True
    assert fp.totals_page_role == "last"
    assert fp.column_signature == ("Description", "Qty", "Rate", "Amount")
    assert fp.text_source == "native"


def test_empty_layout_fingerprint_is_all_none() -> None:
    """An empty fingerprint matches anything; it never soft-misses."""
    fp = parse_persona(_base(layout_fingerprint={})).layout_fingerprint
    assert fp.page_count is None
    assert fp.has_table is None
    assert fp.column_signature == ()


def test_page_count_is_stored_as_a_range_never_an_equality() -> None:
    """Section 6: bills legitimately vary in length month to month."""
    fp = parse_persona(_base(layout_fingerprint={
        "page_count": {"min": 3, "max": 3},
    })).layout_fingerprint
    assert fp.page_count == (3, 3)


# --------------------------------------------------------------------------
# Structural rejections
# --------------------------------------------------------------------------


@pytest.mark.parametrize("missing", [
    "sender_fingerprint", "doc_type", "rule_version", "status",
])
def test_a_persona_missing_an_identity_key_is_rejected(missing: str) -> None:
    p = _base()
    del p[missing]
    with pytest.raises(ValidationError, match=missing):
        parse_persona(p)


def test_an_unrecognizable_selector_shape_is_rejected() -> None:
    """Not a field, not a row group, not a scanline - section 1 has exactly three."""
    with pytest.raises(ValidationError, match="selector"):
        parse_persona(_base(field_selectors=[{"mystery": "yes"}]))


def test_a_non_list_field_selectors_is_rejected() -> None:
    with pytest.raises(ValidationError, match="field_selectors"):
        parse_persona(_base(field_selectors={"field": "a"}))


def test_an_unknown_status_is_rejected() -> None:
    with pytest.raises(ValidationError, match="status"):
        parse_persona(_base(status="published"))


def test_parse_persona_accepts_any_mapping_not_only_dict() -> None:
    """Ledger erratum from Part A: a `dict` check where a `Mapping` check was
    needed leaked Decimal objects into emitted records. Same class of bug."""
    from types import MappingProxyType

    persona = parse_persona(MappingProxyType(_base()))
    assert persona.doc_type == "standard_invoice"
