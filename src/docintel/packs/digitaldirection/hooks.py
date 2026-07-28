"""Digital Direction's hook registrations (pack spec section 5).

Same shape as the Northstar pack, and the same reasoning about which spec rows
turned out to live elsewhere: `deriveAmountPayable`, `runArithmeticCrosschecks`
and `crosscheckScanline` are all persona `adjust` declarations run by Stage 6, and
registering them here as well would double-count every confidence boost.

`requireTwoBillingCycles` belongs to the rule lifecycle, which runs beside the
pipeline. It is worth restating why it exists though: telecom bills are monthly
and their CONTENT varies (usage, one-off charges) while their LAYOUT does not, so
a single low-confidence bill is weak evidence of rule drift and two consecutive
months is strong evidence. The AP-oriented pile-up trigger is too twitchy for a
monthly rhythm.
"""

from __future__ import annotations

from docintel.core.models import JobContext
from docintel.packs.digitaldirection import aliases, conventions, ladder, references
from docintel.packs.registry import primary_text
from docintel.pipeline.hooks import HookRegistry, Next

PACK_NAME = "digitaldirection"


def telecom_ladder(ctx: JobContext, next_: Next) -> JobContext:
    """The section 2 ladder - three types, and deliberately no statement type."""
    return next_(ladder.classify(ctx))


def resolve_carrier_fingerprint(ctx: JobContext, next_: Next) -> JobContext:
    """`<pack>|<canonical carrier>`, from page text (F5).

    Lumen prints three names on one page and Windstream two. Collapsing them here
    is what stops one carrier becoming three personas.
    """
    carrier = aliases.canonical(primary_text(ctx))
    if carrier is not None:
        ctx.sender_fingerprint = f"{PACK_NAME}|{carrier}"
    return next_(ctx)


def apply_billing_conventions(ctx: JobContext, next_: Next) -> JobContext:
    """Supply `prior_balance_basis` from the carrier's convention (F1b)."""
    return next_(conventions.apply_prior_balance_basis(ctx))


def collect_references(ctx: JobContext, next_: Next) -> JobContext:
    """Promote the extracted identity fields into `reference_list` (F11).

    Registered at `beforeConfidenceGate`, NOT `afterExtraction`, and the
    difference is load-bearing. These hits are the extracted fields themselves, and
    `afterExtraction` fires *before* Stage 6 runs the value ops - so Comcast's
    `account_number_normalized` would still read `8495 44 462 0365242` with its
    printed spacing intact, and the reference hit would be unjoinable (F6).

    Northstar's equivalent can run at `afterExtraction` because it scans page text
    and depends on nothing Stage 6 does.
    """
    return next_(references.collect(ctx))


def refine_prior_balance_tags(ctx: JobContext, next_: Next) -> JobContext:
    """`prior_balance_present` vs `_cleared`, decided on the carried balance.

    Runs at `beforeConfidenceGate` rather than `afterExtraction`, because it needs
    `carried_balance` and that is produced by Stage 6.
    """
    return next_(ladder.retag_prior_balance(ctx))


def register(registry: HookRegistry) -> None:
    registry.register("classifySignals", telecom_ladder, PACK_NAME)
    registry.register("beforePersonaLookup", resolve_carrier_fingerprint, PACK_NAME)
    registry.register("afterExtraction", apply_billing_conventions, PACK_NAME)
    registry.register("beforeConfidenceGate", collect_references, PACK_NAME)
    registry.register("beforeConfidenceGate", refine_prior_balance_tags, PACK_NAME)
