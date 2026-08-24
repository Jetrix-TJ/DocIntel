"""Persona -> vision hints: field list and prose, nothing else."""

from __future__ import annotations

from docintel.adapters.vision.hints import (
    field_names_for_persona,
    hints_for_persona,
    recognized_vision_types,
    table_hints_for_persona,
    table_requests_for_persona,
    vision_type_prose,
)
from docintel.grammar.schema import FieldSelector


class _Persona:
    """Minimal stand-in - only `field_selectors` is read."""

    def __init__(self, field_selectors) -> None:
        self.field_selectors = field_selectors


def _sel(field: str, *, anchor: str | None = None, region: str = "near-anchor",
         pattern: str = "text") -> FieldSelector:
    return FieldSelector(field=field, pattern=pattern, region=region, anchor=anchor)


# -- field_names_for_persona -------------------------------------------------


def test_field_names_come_from_the_persona_in_order():
    persona = _Persona([_sel("vendor_name"), _sel("total_printed")])
    assert field_names_for_persona(persona) == ["vendor_name", "total_printed"]


def test_derived_only_fields_are_never_requested():
    """`amount_payable` can never be legitimately supplied by a page read -
    asking vision for it would invite exactly the guess the model is told
    never to make."""
    persona = _Persona([_sel("total_printed"), _sel("amount_payable")])
    assert field_names_for_persona(persona) == ["total_printed"]


def test_row_group_selectors_have_no_field_and_are_skipped():
    """A row-group/scanline selector has no `.field` - this must not raise on
    one, and must not produce a bogus entry for it."""

    class _RowGroup:
        row_group = "line_items"

    persona = _Persona([_sel("total_printed"), _RowGroup()])
    assert field_names_for_persona(persona) == ["total_printed"]


def test_an_empty_persona_yields_no_fields():
    assert field_names_for_persona(_Persona([])) == []


# -- hints_for_persona --------------------------------------------------------


def test_a_hint_combines_anchor_region_and_shape():
    persona = _Persona([_sel("total_printed", anchor="Total Amount Due",
                             region="totals-block", pattern="currency")])
    hints = hints_for_persona(persona)
    assert hints["total_printed"] == (
        'labelled "Total Amount Due", in the totals box, a money amount'
    )


def test_a_field_with_no_anchor_still_gets_a_region_hint():
    persona = _Persona([_sel("vendor_name", anchor=None, region="top-left", pattern="text")])
    assert hints_for_persona(persona)["vendor_name"] == "top-left of the page"


def test_an_unrecognised_region_or_pattern_contributes_nothing_rather_than_a_guess():
    persona = _Persona([_sel("weird_field", anchor=None, region="not-a-real-region",
                             pattern="not-a-real-pattern")])
    assert "weird_field" not in hints_for_persona(persona)


def test_a_bare_digit_count_regex_becomes_a_shape_description():
    persona = _Persona([_sel("account_number_raw", anchor=None, region="same-row",
                             pattern="([0-9]{10})")])
    assert hints_for_persona(persona)["account_number_raw"] == "on the same line as that label, 10 digits"


def test_the_regex_itself_is_never_sent_verbatim():
    """A hint is a description, not an instruction the model could not follow
    anyway - the raw pattern text must never leak into the prose."""
    persona = _Persona([_sel("weird", anchor=None, region="near-anchor",
                             pattern=r"[A-Z]{3}-\d{4}")])
    hints = hints_for_persona(persona)
    assert r"[A-Z]{3}-\d{4}" not in hints.get("weird", "")


def test_derived_only_fields_never_get_a_hint_either():
    persona = _Persona([_sel("amount_payable", anchor="Amount Due", region="totals-block")])
    assert hints_for_persona(persona) == {}


# -- table_requests_for_persona / table_hints_for_persona --------------------


class _RowGroup:
    """Minimal stand-in for a `RowGroupSelector` - only the attributes
    `hints.py`'s table functions actually read."""

    def __init__(self, row_group, columns, column_headers=None):
        self.row_group = row_group
        self.columns = columns
        self.column_headers = column_headers or {}


def test_table_requests_come_from_the_persona_s_row_group_columns_in_order():
    persona = _Persona([
        _sel("total_printed"),
        _RowGroup("line_items", {"date": "date", "description": "text", "amount": "currency"}),
    ])
    assert table_requests_for_persona(persona) == {
        "line_items": ["date", "description", "amount"]
    }


def test_a_persona_with_no_row_group_selector_has_no_table_requests():
    assert table_requests_for_persona(_Persona([_sel("total_printed")])) == {}


def test_table_hints_reuse_the_same_shape_vocabulary_as_scalar_hints():
    persona = _Persona([_RowGroup(
        "line_items",
        {"date": "date", "amount": "currency"},
        column_headers={"amount": "AMOUNT"},
    )])
    hints = table_hints_for_persona(persona)
    assert hints["line_items"]["date"] == "a date"
    assert hints["line_items"]["amount"] == 'labelled "AMOUNT", a money amount'


def test_a_column_with_no_header_or_describable_shape_is_absent():
    persona = _Persona([_RowGroup("line_items", {"mystery": "not-a-real-pattern"})])
    assert table_hints_for_persona(persona) == {"line_items": {}}


# -- pack-level vision_defaults vocabulary -----------------------------------


def test_currency_and_its_friendly_dollar_alias_produce_the_same_prose():
    assert vision_type_prose("currency") == "a money amount"
    assert vision_type_prose("$") == "a money amount"


def test_plain_text_has_no_describable_shape():
    assert vision_type_prose("text") is None


def test_an_unrecognized_type_name_is_not_in_the_recognized_set():
    assert "not-a-real-type" not in recognized_vision_types()


def test_every_pattern_prose_key_and_every_alias_and_text_are_recognized():
    recognized = recognized_vision_types()
    assert {"currency", "date", "decimal", "integer", "$", "money", "text"} <= recognized
