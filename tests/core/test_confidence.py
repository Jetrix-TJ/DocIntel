import pytest
from docintel.core.confidence import (
    BOOST_CAP, CEILING, MODIFIERS, apply_boosts, apply_modifiers,
)


def test_all_sixteen_modifiers_are_registered():
    """The modifier enum is closed - selector-grammar.md section 5."""
    assert len(MODIFIERS) == 16
    assert float(MODIFIERS["soft_miss"]) == 0.80
    assert float(MODIFIERS["ocr_source"]) == 0.90
    assert float(MODIFIERS["pattern_timeout"]) == 0.50
    assert float(MODIFIERS["flattened_annotations"]) == 0.75
    assert float(MODIFIERS["arith_balance_mismatch"]) == 0.80


def test_modifiers_are_multiplicative_and_composable():
    # draft rules on an OCR'd document
    assert apply_modifiers(1.0, ["draft_rules", "ocr_source"]) == pytest.approx(0.765)


def test_unknown_modifier_is_rejected():
    with pytest.raises(ValueError, match="unknown confidence modifier"):
        apply_modifiers(1.0, ["vibes"])


def test_modifier_order_does_not_matter():
    a = apply_modifiers(1.0, ["ocr_source", "soft_miss"])
    b = apply_modifiers(1.0, ["soft_miss", "ocr_source"])
    assert a == pytest.approx(b)


def test_boosts_are_capped_at_1_10():
    assert apply_boosts(0.50, count=99) == pytest.approx(0.50 * float(BOOST_CAP))


def test_boost_can_never_exceed_the_ceiling():
    """Three agreeing renderings of an OCR'd number can still all be wrong the same way."""
    assert apply_boosts(0.98, count=3) == pytest.approx(float(CEILING))
    assert apply_boosts(1.0, count=1) == pytest.approx(float(CEILING))


def test_confidence_floors_at_zero():
    assert apply_modifiers(0.0, ["pattern_timeout"]) == 0.0


def test_apply_boosts_clamps_above_ceiling_when_count_is_zero():
    """apply_boosts must clamp to CEILING even when count <= 0."""
    assert apply_boosts(1.5, count=0) == pytest.approx(float(CEILING))


def test_apply_boosts_clamps_above_ceiling_when_count_is_negative():
    """apply_boosts must clamp to CEILING even when count is negative."""
    assert apply_boosts(1.5, count=-5) == pytest.approx(float(CEILING))


def test_apply_boosts_preserves_value_under_ceiling_when_count_is_zero():
    """apply_boosts preserves values already under the ceiling."""
    assert apply_boosts(0.9, count=0) == pytest.approx(0.9)


def test_apply_modifiers_clamps_above_ceiling_with_no_modifiers():
    """apply_modifiers must clamp base confidence to CEILING."""
    assert apply_modifiers(2.0, []) == pytest.approx(float(CEILING))


def test_apply_modifiers_clamps_above_ceiling_after_multiplication():
    """apply_modifiers must clamp even when result of multiplication exceeds CEILING."""
    assert apply_modifiers(1.5, ["ocr_source"]) == pytest.approx(float(CEILING))


def test_apply_modifiers_never_reports_certainty():
    """A field is never reported as certain, even with base 1.0 and no modifiers.

    This pipeline never claims certainty about a value read off a scanned
    document.
    """
    assert apply_modifiers(1.0, []) == pytest.approx(float(CEILING))


def test_apply_modifiers_clamps_below_floor():
    """apply_modifiers must clamp negative values to 0."""
    assert apply_modifiers(-5.0, []) == pytest.approx(0.0)


def test_confidence_stays_within_bounds():
    """Property test: confidence must always be in [0, CEILING] inclusive.

    For any base in [0, 2] and various modifier combinations, the result
    must always be within [0.0, 0.99].
    """
    import itertools

    bases = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0]
    modifier_combos = [
        [],
        ["soft_miss"],
        ["ocr_source"],
        ["draft_rules", "ocr_source"],
        ["pattern_timeout"],
        ["ocr_source", "ambiguous_anchor"],
    ]

    for base, modifiers in itertools.product(bases, modifier_combos):
        result = apply_modifiers(base, modifiers)
        assert 0.0 <= result <= float(CEILING), f"base={base}, modifiers={modifiers}, result={result}"

    boost_counts = [-5, -1, 0, 1, 2, 3, 5, 10, 99]
    for base, count in itertools.product(bases, boost_counts):
        result = apply_boosts(base, count)
        assert 0.0 <= result <= float(CEILING), f"base={base}, count={count}, result={result}"
