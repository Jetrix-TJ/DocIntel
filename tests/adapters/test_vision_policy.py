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
from docintel.pipeline.stages.s7_gate import FORCING_MODIFIERS


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


def test_negative_confidence_is_clamped_to_zero():
    result = VisionResult(fields={"a": "1"}, confidence={"a": -3.0})
    assert sanitize(result, ["a"]).confidence["a"] == 0.0


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
