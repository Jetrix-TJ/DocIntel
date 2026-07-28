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

`applyBillingConventions` and `refineProseBalanceTags` are both deferred by the
printed-fields-only narrowing: the first supplies `prior_balance_basis`, a derived
classification, and the second retags on `carried_balance`, which Stage 6 no
longer produces. Both implementations stay in the tree.
"""

from __future__ import annotations

from docintel.core.models import JobContext
from docintel.packs.digitaldirection import aliases, ladder, references
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


def collect_references(ctx: JobContext, next_: Next) -> JobContext:
    """Promote the extracted identity fields into `reference_list` (F11).

    Registered at `beforeConfidenceGate`, NOT `afterExtraction`, and the
    difference is still load-bearing after the printed-fields-only narrowing -
    though the example that used to justify it is gone. `afterExtraction` fires
    *before* Stage 6 (`runner.HOOKS_BEFORE`), so a hook there reads the values
    Stage 5 captured rather than the values the record ends up carrying. It used
    to be Comcast's `account_number_normalized` that made the gap visible; that
    field is no longer registered, and today no DD persona declares a value op on
    a promoted identity field, so the two positions would currently agree.

    The position stays because the agreement is a coincidence of the current
    personas, not a property of the hook: a reference hit exists to be joined on,
    so it must be the value the record carries, and adding one normalizer to
    `account_number` must not silently change the reference list.

    Northstar's equivalent can run at `afterExtraction` because it scans page text
    and depends on nothing Stage 6 does.
    """
    return next_(references.collect(ctx))


def register(registry: HookRegistry) -> None:
    registry.register("classifySignals", telecom_ladder, PACK_NAME)
    registry.register("beforePersonaLookup", resolve_carrier_fingerprint, PACK_NAME)
    registry.register("beforeConfidenceGate", collect_references, PACK_NAME)
