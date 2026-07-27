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
