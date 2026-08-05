"""Northstar's hook registrations (pack spec section 5).

**Fewer hooks than the spec table lists, and each absence is deliberate.** The
spec was written before the grammar's closed op enum existed, and several rows
turned out to be things a persona already declares or the core already does. A
hook that duplicated one of those would run the same work twice - and for the
cross-checks that means double-counting a confidence boost.

| Spec row | Where it actually lives |
|---|---|
| `detectFlattenedAnnotations` | `s2_filter` (C1b). Generic, not pack-specific. |
| `assignPageRoles` | `s2_filter` (C1b). Same. |
| `northstarLadder` | **here**, at `classifySignals` |
| `resolveVendorAlias` | **here**, at `beforePersonaLookup` |
| `deriveAmountPayable` | deferred: no Northstar persona's `adjust` list calls it any more - `amount_payable` is DERIVED_ONLY and no longer registered. See the printed-fields-only spec. |
| `runArithmeticCrosschecks` | deferred: same reason - the crosscheck ops it named (`crosscheck_total_composition`, `crosscheck_balance_composition`, `crosscheck_line_sum`, `crosscheck_scanline`, `crosscheck_filename`) are gone from every persona's `adjust` list along with the arithmetic they scored. |
| `inferCurrency` | deferred: supplied `currency`, which printed-fields-only drops entirely - it was never ink on the page. |
| `collectReferences` | **here**, at `afterExtraction` |
| `northstarThresholds` | `ConfidenceGate` reads `ctx.pack.thresholds` |
| `attachAllocationMetadata` | already on the record: `service_location` is a field, `sub_account` a row group |
| `excludeAnnotatedFromGold` | the rule lifecycle, which runs beside the pipeline |
| `applyBillingConventions` | **here**, at `afterExtraction` |

The three that remain are the three that cannot be expressed any other way: a
classification ladder, a fingerprint derived from page text, and reference
patterns that are pack code rather than grammar.
"""

from __future__ import annotations

from docintel.core.models import JobContext
from docintel.core.senders import is_aggregator
from docintel.packs.northstar import aliases, conventions, ladder, references
from docintel.packs.registry import primary_text
from docintel.pipeline.hooks import HookRegistry, Next

PACK_NAME = "northstar"


def northstar_ladder(ctx: JobContext, next_: Next) -> JobContext:
    """The section 1 signal ladder. Fires inside Stage 3."""
    return next_(ladder.classify(ctx))


def resolve_vendor_fingerprint(ctx: JobContext, next_: Next) -> JobContext:
    """Set `sender_fingerprint` from the vendor alias table (F5).

    Read from **page text**, not from an extracted `vendor_name`: Stage 4 runs
    before Stage 5, so no field has been extracted yet. That ordering is not an
    inconvenience to work around - the persona is what tells Stage 5 how to
    extract, so the lookup key cannot depend on extraction having happened.

    The fingerprint is `<pack>|<canonical vendor>`. Collapsing every printed
    rendering of a vendor onto one canonical key is the whole point: without it
    Federal Recycling's letterhead and its remittance payee become two personas
    that never find each other.

    When the page text resolves nothing at all, fall back to the sender's email
    domain (weaker evidence than print, but still evidence) - unless the sender
    is an aggregator like bill.com, in which case every one of its customers'
    invoices would otherwise collapse onto a single "bill.com" persona. The
    printed-name lookup always runs first and wins when it finds anything.
    """
    canonical = aliases.canonical(primary_text(ctx))
    if canonical is None and not is_aggregator(ctx.sender_email or ""):
        canonical = aliases.canonical_from_domain(ctx.sender_email or "")
    if canonical is not None:
        ctx.sender_fingerprint = f"{PACK_NAME}|{canonical}"
    return next_(ctx)


def collect_references(ctx: JobContext, next_: Next) -> JobContext:
    """The section 3 reference patterns, with provenance (F11)."""
    return next_(references.collect(ctx))


def apply_billing_conventions(ctx: JobContext, next_: Next) -> JobContext:
    """Supply `prior_balance_basis` from the vendor's known convention (F1b)."""
    return next_(conventions.apply_prior_balance_basis(ctx))


def register(registry: HookRegistry) -> None:
    registry.register("classifySignals", northstar_ladder, PACK_NAME)
    registry.register("beforePersonaLookup", resolve_vendor_fingerprint, PACK_NAME)
    registry.register("afterExtraction", collect_references, PACK_NAME)
    registry.register("afterExtraction", apply_billing_conventions, PACK_NAME)
