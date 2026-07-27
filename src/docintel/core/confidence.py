"""The closed confidence-modifier enum.

One mechanism, multiplicative, every applied modifier recorded on the emitted
record (spec Stage 6). There is deliberately no other way to lower confidence.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

MODIFIERS: dict[str, Decimal] = {
    "soft_miss": Decimal("0.80"),
    "draft_rules": Decimal("0.85"),
    "ocr_source": Decimal("0.90"),
    "ambiguous_anchor": Decimal("0.90"),
    "anchor_alt_used": Decimal("0.95"),
    "pattern_timeout": Decimal("0.50"),
    "arith_lines_mismatch": Decimal("0.85"),
    "arith_total_mismatch": Decimal("0.85"),
    "arith_balance_mismatch": Decimal("0.80"),
    "scanline_mismatch": Decimal("0.85"),
    "filename_disagree": Decimal("0.95"),
    "currency_inferred_weak": Decimal("0.90"),
    "ambiguous_two_digit_year": Decimal("0.95"),
    "handwriting_detected": Decimal("0.60"),
    "high_skew": Decimal("0.85"),
    "flattened_annotations": Decimal("0.75"),
}

BOOST_CAP = Decimal("1.10")
CEILING = Decimal("0.99")
_PER_BOOST = Decimal("1.03")


def _clamp(value: Decimal) -> float:
    """Confidence is always within [0, CEILING].

    CEILING is a global invariant, not a boost-only rule: this pipeline never
    reports certainty about a value read off a document.
    """
    return float(min(CEILING, max(Decimal("0"), value)))


def apply_modifiers(base: float, names: Sequence[str]) -> float:
    value = Decimal(str(base))
    for name in names:
        if name not in MODIFIERS:
            raise ValueError(f"unknown confidence modifier: {name!r}")
        value *= MODIFIERS[name]
    return _clamp(value)


def apply_boosts(base: float, count: int) -> float:
    """Corroboration raises confidence a little, never to certainty."""
    if count <= 0:
        return _clamp(Decimal(str(base)))
    factor = min(BOOST_CAP, _PER_BOOST ** count)
    return _clamp(Decimal(str(base)) * factor)
