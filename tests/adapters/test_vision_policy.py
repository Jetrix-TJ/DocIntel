"""The vision privilege boundary. GUARDRAIL 7.

A `VisionResult` is not inert: Stage 5b writes its fields into `ExtractedFields`
and its irregularities into the document's modifier list, which Stage 7 routes on.
These tests exist so that a future adapter (a different vendor, a wider field set)
cannot widen what a model is allowed to assert without one of them failing.
"""

from __future__ import annotations

import pytest

from docintel.adapters.vision.policy import VISION_OBSERVABLE, sanitize
from docintel.adapters.vision.port import VisionResult
from docintel.core.confidence import CEILING, MODIFIERS
from docintel.core.models import DERIVED_ONLY
from docintel.adapters.vision.policy import VISION_FLOOR
from docintel.pipeline.stages.s7_gate import FORCING_MODIFIERS, VERY_LOW_FLOOR


def test_no_vision_observable_modifier_can_force_review_on_its_own():
    """The load-bearing property. A model may lower confidence; the gate decides
    what low confidence means. If someone adds `flattened_annotations` here, this
    fails - which is the point."""
    assert VISION_OBSERVABLE & FORCING_MODIFIERS == frozenset()


def test_every_observable_name_is_a_real_section_5_modifier():
    """A typo would make an observation inert: Stage 5b would file it as a tag and
    its penalty would never apply, while the record would look like it was honoured."""
    assert VISION_OBSERVABLE <= set(MODIFIERS)


def test_the_arithmetic_modifiers_are_not_delegated_to_a_model():
    """These are computed by ops that do real comparisons. A model asserting one
    would replace arithmetic with an opinion."""
    computed = {
        "arith_lines_mismatch", "arith_total_mismatch", "arith_balance_mismatch",
        "scanline_mismatch", "filename_disagree",
    }
    assert VISION_OBSERVABLE & computed == frozenset()


# -- fields ----------------------------------------------------------------


def test_only_the_requested_fields_survive():
    result = VisionResult(fields={"total_printed": "1.00", "notes": "chatty"})
    assert set(sanitize(result, ["total_printed"]).fields) == {"total_printed"}


@pytest.mark.parametrize("name", sorted(DERIVED_ONLY))
def test_a_derived_only_field_is_dropped_even_if_a_caller_asked_for_it(name):
    """`ExtractedFields.set` raises on these (grammar V10), so passing one through
    would crash the stage rather than merely polluting the record."""
    result = VisionResult(fields={name: "9.99"})
    assert sanitize(result, [name]).fields == {}


def test_whitespace_only_is_absence_not_a_value():
    result = VisionResult(fields={"total_printed": "   ", "vendor_name": " ACME "})
    cleaned = sanitize(result, ["total_printed", "vendor_name"])
    assert cleaned.fields == {"vendor_name": "ACME"}


def test_a_non_string_value_is_dropped():
    """The schema says string, but a hand-edited cassette is not schema-checked."""
    result = VisionResult(fields={"total_printed": 1177.70})  # type: ignore[dict-item]
    assert sanitize(result, ["total_printed"]).fields == {}


# -- confidence ------------------------------------------------------------


def test_confidence_is_clamped_to_the_global_ceiling():
    """JSON Schema cannot express minimum/maximum in the API's supported subset, so
    the bound lives here. CEILING applies because nothing read off a document is
    ever certain."""
    result = VisionResult(fields={"a": "1"}, confidence={"a": 4.2})
    assert sanitize(result, ["a"]).confidence["a"] == pytest.approx(float(CEILING))


def test_confidence_is_floored_so_a_model_cannot_demand_regeneration():
    """GUARDRAIL 7, second path - the one the irregularity tests above do not cover.

    `s7_gate._confidence_lane` routes to the `low` lane when a majority share of
    fields score below `VERY_LOW_FLOOR`, and the `low` lane sets `regen_flag` -
    a request to regenerate the vendor's persona. Without a lower clamp, a model
    reporting 0.01 on the fields it returned would reach that path, which is
    lane-routing power AND rule-lifecycle power granted by a number the model
    chose.

    Flooring does not silence the model: `VISION_FLOOR` sits below every pack
    threshold, so a floored field still falls short and still routes the document
    to a human. What it cannot do is claim the RULES are broken - the model saw an
    illegible image, which is not evidence about the persona.
    """
    result = VisionResult(fields={"a": "1"}, confidence={"a": 0.01})
    assert sanitize(result, ["a"]).confidence["a"] >= VERY_LOW_FLOOR


def test_the_vision_floor_stays_at_or_above_the_gate_s_collapse_floor():
    """The two constants live in different modules on purpose - `policy` must not
    import a pipeline stage. This test is the link: lower `VISION_FLOOR` below the
    gate's floor and the guardrail above silently stops holding."""
    assert VISION_FLOOR >= VERY_LOW_FLOOR


def test_negative_confidence_is_clamped_into_the_allowed_band():
    result = VisionResult(fields={"a": "1"}, confidence={"a": -3.0})
    assert sanitize(result, ["a"]).confidence["a"] == pytest.approx(VISION_FLOOR)


def test_a_field_with_no_confidence_gets_the_default():
    result = VisionResult(fields={"a": "1"})
    assert sanitize(result, ["a"]).confidence["a"] == pytest.approx(0.50)


def test_a_bool_is_not_a_confidence():
    """`True` is an int in Python, so a naive numeric check would read it as 1.0 -
    i.e. as certainty."""
    result = VisionResult(fields={"a": "1"}, confidence={"a": True})  # type: ignore[dict-item]
    assert sanitize(result, ["a"]).confidence["a"] == pytest.approx(0.50)


def test_confidence_for_a_dropped_field_does_not_survive():
    result = VisionResult(fields={"a": ""}, confidence={"a": 0.9})
    assert sanitize(result, ["a"]).confidence == {}


# -- irregularities --------------------------------------------------------

@pytest.mark.parametrize("flag", sorted(VISION_OBSERVABLE))
def test_an_observable_flag_survives(flag):
    assert sanitize(VisionResult(irregularities=[flag]), []).irregularities == [flag]


@pytest.mark.parametrize(
    "flag",
    ["flattened_annotations", "arith_total_mismatch", "ocr_source", "review_now", ""],
)
def test_a_flag_outside_the_observable_set_is_dropped(flag):
    assert sanitize(VisionResult(irregularities=[flag]), []).irregularities == []


def test_duplicate_flags_are_collapsed_in_order():
    result = VisionResult(irregularities=["high_skew", "handwriting_detected", "high_skew"])
    assert sanitize(result, []).irregularities == ["high_skew", "handwriting_detected"]


# -- tables (line items) -----------------------------------------------------


def test_only_a_requested_table_survives():
    result = VisionResult(row_groups={"line_items": [{"amount": "1.00"}], "charges": [{"a": "1"}]})
    cleaned = sanitize(result, [], {"line_items": ["amount"]})
    assert set(cleaned.row_groups) == {"line_items"}


def test_only_declared_columns_survive_in_each_row():
    """Same rule-1 allowlist reasoning as scalar fields, one level down: a
    model returning an extra, unrequested column must not leak it through."""
    result = VisionResult(row_groups={"line_items": [{"amount": "1.00", "notes": "chatty"}]})
    cleaned = sanitize(result, [], {"line_items": ["amount"]})
    assert cleaned.row_groups["line_items"] == [{"amount": "1.00"}]


def test_a_missing_cell_is_an_empty_string_not_a_dropped_key():
    """Unlike a scalar field (where absence means the field itself is
    missing), a blank CELL in a real row is a legitimate value - the row
    still exists, so every declared column stays present on it."""
    result = VisionResult(row_groups={"line_items": [{"amount": "1.00"}]})
    cleaned = sanitize(result, [], {"line_items": ["amount", "description"]})
    assert cleaned.row_groups["line_items"] == [{"amount": "1.00", "description": ""}]


def test_a_non_dict_row_is_dropped_not_raised():
    result = VisionResult(row_groups={"line_items": ["not a row", {"amount": "1.00"}]})
    cleaned = sanitize(result, [], {"line_items": ["amount"]})
    assert cleaned.row_groups["line_items"] == [{"amount": "1.00"}]


def test_a_non_list_table_value_is_dropped_not_raised():
    result = VisionResult(row_groups={"line_items": "not a list"})  # type: ignore[dict-item]
    cleaned = sanitize(result, [], {"line_items": ["amount"]})
    assert cleaned.row_groups["line_items"] == []


def test_a_table_that_was_not_requested_is_absent_even_if_the_model_supplied_one():
    result = VisionResult(row_groups={"secret_table": [{"a": "1"}]})
    cleaned = sanitize(result, [], {"line_items": ["amount"]})
    assert cleaned.row_groups == {"line_items": []}


def test_no_table_requests_means_no_row_groups_at_all():
    result = VisionResult(row_groups={"line_items": [{"amount": "1.00"}]})
    assert sanitize(result, ["a"]).row_groups == {}
