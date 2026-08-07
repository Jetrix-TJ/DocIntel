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

`applyBillingConventions` is registered here, at `afterExtraction`. It
supplies `prior_balance_basis` from the carrier's known convention
(`conventions.py`), which `resolve_carried_balance` (Stage 6) needs.

`refineProseBalanceTags` is NOT deferred, though an earlier pass of the narrowing
unregistered it on the grounds that it retagged on `carried_balance`. That left
`ladder.tags_for`'s unrefined guess as the pipeline's final answer, and the guess
is made on anchor text - which says `prior_balance_cleared` on Centracom while
20,123.80 is outstanding. It is re-registered here reading the two PRINTED
amounts instead, which is squarely inside the narrowed scope.
"""

from __future__ import annotations

from docintel.core.models import JobContext
from docintel.core.senders import is_aggregator
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

    If page text resolves nothing at all - a letterhead-only logo with no other
    printed mention, say - fall back to the sender's email domain, unless the
    sender is an aggregator (bill.com, Ariba, QuickBooks): keying an aggregator's
    shared domain would collapse every carrier that bills through it onto one
    persona. The page-text lookup always runs first and wins when it finds
    anything; the domain is weaker evidence, used only when print gives nothing.
    """
    carrier = aliases.canonical(primary_text(ctx))
    if carrier is None and not is_aggregator(ctx.sender_email or ""):
        carrier = aliases.canonical_from_domain(ctx.sender_email or "")
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


def apply_billing_conventions(ctx: JobContext, next_: Next) -> JobContext:
    """Supply `prior_balance_basis` from the carrier's known convention (F1b)."""
    return next_(conventions.apply_prior_balance_basis(ctx))


def refine_prior_balance_tags(ctx: JobContext, next_: Next) -> JobContext:
    """Upgrade `prior_balance_present` to `prior_balance_cleared` on the amounts.

    `beforeConfidenceGate` rather than `afterExtraction` for the same reason
    `collect_references` is: the amounts it reads must be the ones the record
    carries, after Stage 6's value ops (`normalize_credit_sign` in particular -
    a payment printed `212.87CR` is not a negative number until that has run).
    """
    return next_(ladder.retag_prior_balance(ctx))


def refine_invoice_number_tag(ctx: JobContext, next_: Next) -> JobContext:
    """`no_invoice_number`, which only extraction can decide (spec section 2).

    Registered at `beforeConfidenceGate` for the same reason as
    `refine_prior_balance_tags` and `collect_references`: `afterExtraction` fires
    *before* Stage 6 (`runner.HOOKS_BEFORE`), so a hook there reads the values
    Stage 5 captured rather than the values the record ends up carrying. Adding
    a value op to `invoice_number` - a normalizer that strips a prefix, say -
    must not be able to change whether this tag fires, and at `afterExtraction`
    it could.

    Registration order within the socket is deliberately not relied on:
    `collect_references` reads `ctx.extracted` and `ctx.reference_list` and never
    touches `ctx.tags`, so there is no dependency between the two to encode.
    """
    return next_(ladder.retag_missing_invoice_number(ctx))


def register(registry: HookRegistry) -> None:
    registry.register("classifySignals", telecom_ladder, PACK_NAME)
    registry.register("beforePersonaLookup", resolve_carrier_fingerprint, PACK_NAME)
    registry.register("afterExtraction", apply_billing_conventions, PACK_NAME)
    registry.register("beforeConfidenceGate", refine_prior_balance_tags, PACK_NAME)
    registry.register("beforeConfidenceGate", refine_invoice_number_tag, PACK_NAME)
    registry.register("beforeConfidenceGate", collect_references, PACK_NAME)
