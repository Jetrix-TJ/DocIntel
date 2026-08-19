"""Persona -> vision hints: field list and prose, nothing else."""

from __future__ import annotations

from docintel.adapters.vision.hints import field_names_for_persona, hints_for_persona
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
