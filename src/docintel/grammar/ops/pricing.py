"""Weight-tiered manufacturing pricing - a second derivation family, alongside
`derive.py`'s telecom F1 machinery.

The shape of the problem is the same as F1's ("what's actually owed is not
simply what's printed"), but the formula and the vendor vertical are entirely
different: a carbon-bar distributor whose per-foot price depends on the
TOTAL WEIGHT of an order (a margin schedule with three weight-break tiers),
not a carried balance. Kept in its own module rather than folded into
`derive.py`, which is specifically telecom billing's F1/F1b history - a
future reader should not have to separate two unrelated business domains
out of one file.

**The one rule this op exists to enforce**: the weight tier is decided from
the ACTUAL, COMPUTED order weight (`weight_per_ft x footage`), never from
whatever tier a vendor's own invoice claims. A vendor's printed narrative
text naming a tier is exactly as trustworthy as `total_printed` on a
telecom bill - real, but not authoritative, because it can be produced from
a rounding error or by using the wrong schedule at write time. Two SPT
Metals corpus documents exist specifically because their own invoices claim
the wrong tier - one overcharges, one undercharges - proving the derivation
has to inspect both directions, not just guard against inflation.

`weight_tier_margin`, `state_freight_rate`, `ctl_adder`, and `total_weight`
are supplied by the claiming pack's own `afterExtraction` hook (the exact
`prior_balance_basis` pattern: a fact the derivation needs that the page
cannot supply, looked up from a reviewed table and threaded through
`ctx.extracted` as if it were printed - see `packs/spt_metals/conventions.py`).
This op is pack-agnostic: any future weight-tiered vendor supplies its own
tables through the same three names and reuses this exact formula.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from docintel.core.models import JobContext

TWO_PLACES = Decimal("0.01")


def _decimal(value: Any) -> Decimal | None:
    """Coerce an extracted/derived value to Decimal, or None.

    Same discipline as `derive.py::_money`: never float arithmetic, and a
    float arriving here (e.g. from a hand-written gold fixture) is routed
    through `str` so it keeps its printed precision.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except (InvalidOperation, ValueError):
            return None
    return None


def _field(ctx: JobContext, name: str) -> Decimal | None:
    """Prefer an extracted value, accept a derived one - the same lookup
    order `derive.py::_field` uses, so a pack-supplied convention
    (threaded through `ctx.extracted`, see module docstring) and a value
    another op already derived compose the same way."""
    value = _decimal(ctx.extracted.get(name))
    if value is None:
        value = _decimal(ctx.derived.get(name))
    return value


# The genuine OUTPUTS of this op, in `ctx.derived` - NOT `total_weight`/
# `weight_tier`, which live only in `ctx.extracted` (see the module
# docstring: the same single-location choice `prior_balance_basis` uses).
_DERIVED_KEYS = ("price_per_foot", "material_total", "freight", "order_total")


def _refuse(ctx: JobContext, reason: str) -> JobContext:
    """Record that the order total could not be determined, and why -
    mirrors `derive.py::_refuse` exactly: explicit `None`s so a consumer can
    tell "we looked and could not decide" from "this pipeline never tried"."""
    for key in _DERIVED_KEYS:
        ctx.derived.set(key, None)
    ctx.add_modifier("weight_tiered_pricing_incomplete")
    ctx.review_flag = True
    ctx.log(f"s6: order_total not derived - {reason}")
    return ctx


def derive_price_per_foot(ctx: JobContext) -> JobContext:
    """Price per foot ($/ft) = Weight/ft x Base Cost/lb x Margin x CTL Factor,
    then Order Total = (Price/ft x Footage) + Energy Surcharge + Freight.

    Refuses, rather than guessing, when: a required raw value is missing;
    the computed total weight falls outside every margin tier the pack
    knows about; or the destination state has no freight rate on file. Each
    is a real failure mode, not a defensive hypothetical - the same
    discipline `derive_amount_payable` applies to its own three refusal
    paths.
    """
    weight_per_ft = _field(ctx, "weight_per_ft")
    base_cost_per_lb = _field(ctx, "base_cost_per_lb")
    footage = _field(ctx, "footage")
    if weight_per_ft is None or base_cost_per_lb is None or footage is None:
        return _refuse(ctx, "weight_per_ft, base_cost_per_lb, or footage was not extracted")

    # `total_weight`/`weight_tier` are supplied by the pack's afterExtraction
    # hook (it needs weight_per_ft x footage before this op runs, to pick the
    # margin tier from the ACTUAL order weight rather than the invoice's own
    # tier claim - see the module docstring) and live in `ctx.extracted`,
    # the same single location `prior_balance_basis` uses - not duplicated
    # into `ctx.derived`. Recomputing `total_weight` here as a fallback keeps
    # this op honest even against a pack that has not wired that hook yet.
    total_weight = _field(ctx, "total_weight")
    if total_weight is None:
        total_weight = (weight_per_ft * footage).quantize(TWO_PLACES)

    margin = _field(ctx, "weight_tier_margin")
    if margin is None:
        return _refuse(
            ctx,
            f"no margin tier covers a computed order weight of {total_weight} lbs",
        )

    ctl_adder = _field(ctx, "ctl_adder")
    if ctl_adder is None:
        return _refuse(ctx, "no CTL adder is on file for this pack")
    ctl_factor = Decimal(1) + ctl_adder

    price_per_foot = (weight_per_ft * base_cost_per_lb * margin * ctl_factor).quantize(TWO_PLACES)
    ctx.derived.set("price_per_foot", price_per_foot)

    material_total = (price_per_foot * footage).quantize(TWO_PLACES)
    ctx.derived.set("material_total", material_total)

    state_rate = _field(ctx, "state_freight_rate")
    if state_rate is None:
        return _refuse(
            ctx,
            f"no freight rate on file for state {ctx.extracted.get('ship_to_state')!r}",
        )
    freight = (total_weight * state_rate).quantize(TWO_PLACES)
    ctx.derived.set("freight", freight)

    surcharge = _field(ctx, "energy_surcharge") or Decimal(0)
    order_total = material_total + surcharge + freight
    ctx.derived.set("order_total", order_total)
    return ctx
