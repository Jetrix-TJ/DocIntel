"""Business facts SPT Metals' invoices need but never print - the same
`prior_balance_basis` pattern digitaldirection uses (`conventions.py` there):
a hand-maintained, reviewed table, not something a persona selector could
read off a page or a rule-authoring agent could invent.

The weight-tier margin table is keyed on the ORDER'S ACTUAL COMPUTED WEIGHT,
never on whatever tier an invoice's own narrative text claims - that
computed-not-claimed distinction is the entire reason
`grammar.ops.pricing.derive_price_per_foot` exists rather than just reading
a printed price-per-foot figure.
"""

from __future__ import annotations

from decimal import Decimal

from docintel.core.models import JobContext

# (low, high, tier name, margin multiplier). `high=None` means "and above".
# Matches SPT's own published price sheet ("SPT Price Sheet - Carbon Bar").
WEIGHT_TIER_MARGIN: tuple[tuple[Decimal, Decimal | None, str, Decimal], ...] = (
    (Decimal(0), Decimal(2000), "Tier 1", Decimal("1.12")),
    (Decimal("2000.01"), Decimal(5000), "Tier 2", Decimal("1.08")),
    (Decimal("5000.01"), None, "Tier 3", Decimal("1.04")),
)

# CTL = Cut-to-Length. A flat adder over the random-length base price,
# published on the same price sheet as the margin table.
CTL_ADDER = Decimal("0.10")

# Per-state freight rate, $/lb. Two states on file - onboarding a new
# destination state is a one-line table change, not a code change.
STATE_FREIGHT_RATE: dict[str, Decimal] = {
    "NY": Decimal("0.03"),
    "OH": Decimal("0.02"),
}


def _tier_for(total_weight: Decimal) -> tuple[str, Decimal] | None:
    for low, high, name, margin in WEIGHT_TIER_MARGIN:
        if total_weight < low:
            continue
        if high is None or total_weight <= high:
            return name, margin
    return None


def apply_pricing_conventions(ctx: JobContext) -> JobContext:
    """Compute total order weight from the extracted per-foot weight and
    footage, then supply the tier margin, CTL adder, and state freight rate
    - all threaded through `ctx.extracted` as if they were printed, so the
    pack-agnostic `derive_price_per_foot` op can read them the same way it
    reads a genuinely printed value.

    Runs whether or not the tier/state actually resolve: an unresolvable one
    is left absent rather than defaulted, so `derive_price_per_foot` refuses
    loudly instead of silently picking a tier or a rate.
    """
    weight_per_ft = ctx.extracted.get("weight_per_ft")
    footage = ctx.extracted.get("footage")
    if weight_per_ft is not None and footage is not None:
        total_weight = (Decimal(str(weight_per_ft)) * Decimal(str(footage))).quantize(Decimal("0.01"))
        ctx.extracted.set("total_weight", total_weight, 1.0)
        tier = _tier_for(total_weight)
        if tier is not None:
            name, margin = tier
            ctx.extracted.set("weight_tier", name, 1.0)
            ctx.extracted.set("weight_tier_margin", margin, 1.0)
            ctx.log(f"s6: weight_tier {name!r} ({margin}x) from computed weight {total_weight} lbs")
        else:
            ctx.log(f"s6: no margin tier covers computed weight {total_weight} lbs")

    ship_to_state = ctx.extracted.get("ship_to_state")
    rate = STATE_FREIGHT_RATE.get(ship_to_state) if ship_to_state else None
    if rate is not None:
        ctx.extracted.set("state_freight_rate", rate, 1.0)
    elif ship_to_state is not None:
        ctx.log(f"s6: no freight rate on file for state {ship_to_state!r}")

    ctx.extracted.set("ctl_adder", CTL_ADDER, 1.0)
    return ctx
