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
| `deriveAmountPayable` | each persona's `adjust` list, run by Stage 6 |
| `runArithmeticCrosschecks` | same |
| `inferCurrency` | same |
| `collectReferences` | **here**, at `afterExtraction` |
| `northstarThresholds` | `ConfidenceGate` reads `ctx.pack.thresholds` |
| `attachAllocationMetadata` | already on the record: `service_location` is a field, `sub_account` a row group |
| `excludeAnnotatedFromGold` | the rule lifecycle, which runs beside the pipeline |
| `applyBillingConventions` | deferred: supplies `prior_balance_basis`, a derived classification. `conventions.py` stays in the tree; see the printed-fields-only spec. |

The three that remain are the three that cannot be expressed any other way: a
classification ladder, a fingerprint derived from page text, and reference
patterns that are pack code rather than grammar.
"""

from __future__ import annotations

from docintel.core.models import JobContext
from docintel.packs.northstar import aliases, ladder, references
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
    """
    canonical = aliases.canonical(primary_text(ctx))
    if canonical is not None:
        ctx.sender_fingerprint = f"{PACK_NAME}|{canonical}"
    return next_(ctx)


def collect_references(ctx: JobContext, next_: Next) -> JobContext:
    """The section 3 reference patterns, with provenance (F11)."""
    return next_(references.collect(ctx))


def register(registry: HookRegistry) -> None:
    registry.register("classifySignals", northstar_ladder, PACK_NAME)
    registry.register("beforePersonaLookup", resolve_vendor_fingerprint, PACK_NAME)
    registry.register("afterExtraction", collect_references, PACK_NAME)
