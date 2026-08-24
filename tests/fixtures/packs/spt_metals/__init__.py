"""Pack: SPT Metals, Inc. - carbon bar distribution, weight-tiered pricing.

Onboarded to prove the classification/derivation architecture generalizes
past telecom billing (every other pack's F1 payable-derivation math). The
formula (`grammar.ops.pricing.derive_price_per_foot`) is structurally
unrelated: Weight/ft x Base Cost/lb x Margin x CTL Factor, plus a flat
energy surcharge, plus weight x a per-state freight rate - where the margin
tier is decided from the ORDER'S ACTUAL COMPUTED WEIGHT, never from
whatever tier the vendor's own invoice claims.

**Data-only for classification and extraction, exactly like `acme_freight`**
(`pack.json`: claim, ladder, field sets, thresholds - all data). The one
thing a `DataPack` cannot do is register a pack-specific hook, and this pack
needs one: `conventions.py::apply_pricing_conventions`, supplying the
weight-tier margin table, the CTL adder, and the per-state freight rate -
none of which are ever printed on an SPT invoice, the same
`digitaldirection.conventions.apply_prior_balance_basis` precedent. So this
is a thin wrapper around a `DataPack`, delegating the entire
`registry.Pack` protocol to it and adding exactly one extra hook
registration - not a rewrite of the ~1,150-line module-pack pattern for one
extra fact.
"""

from __future__ import annotations

import os
from typing import Any

from docintel.core.models import JobContext
from docintel.packs import datapack
from . import conventions
from docintel.pipeline.hooks import HookRegistry, Next

_HERE = os.path.dirname(os.path.abspath(__file__))
_SPEC_PATH = os.path.join(_HERE, "pack.json")


def _apply_pricing_conventions(ctx: JobContext, next_: Next) -> JobContext:
    return next_(conventions.apply_pricing_conventions(ctx))


PACK_NAME = "spt_metals"


def _resolve_fingerprint(ctx: JobContext, next_: Next) -> JobContext:
    """`spt_metals|spt_metals` unconditionally.

    Unlike digitaldirection (one pack, several carriers), this pack claims
    for exactly one vendor - by the time this fires, `ctx.pack` is already
    this pack (the gate on `_ClaimGatedRegistry` only calls hooks registered
    here once `resolve_pack` has matched the claim in `pack.json`), so there
    is nothing to disambiguate.
    """
    ctx.sender_fingerprint = f"{PACK_NAME}|spt_metals"
    return next_(ctx)


class SPTMetalsPack:
    """`registry.Pack`, delegated to a `DataPack` plus one `afterExtraction` hook."""

    def __init__(self) -> None:
        self._data = datapack.load_pack_file(_SPEC_PATH)

    @property
    def name(self) -> str:
        return self._data.name

    @property
    def doc_types(self) -> tuple[str, ...]:
        return self._data.doc_types

    @property
    def thresholds(self) -> dict[str, float]:
        return self._data.thresholds

    @property
    def default_currency(self) -> str:
        return self._data.default_currency

    @property
    def vendor_aliases(self) -> dict[str, str]:
        return self._data.vendor_aliases

    @property
    def display_names(self) -> dict[str, str]:
        return self._data.display_names

    @property
    def bill_to_roster(self) -> tuple[str, ...]:
        return self._data.bill_to_roster

    def fields_for(self, doc_type: str) -> frozenset[str]:
        return self._data.fields_for(doc_type)

    field_set = fields_for

    def required_fields(self, doc_type: str) -> frozenset[str]:
        return self._data.required_fields(doc_type)

    def required_any_of(self, doc_type: str) -> tuple[frozenset[str], ...]:
        return self._data.required_any_of(doc_type)

    def derived_only_fields(self, doc_type: str) -> frozenset[str]:
        return self._data.derived_only_fields(doc_type)

    def adjust_ops(self) -> frozenset[str]:
        """No pack-exclusive ops. `derive_price_per_foot` is registered in
        the shared, globally-available `grammar.ops.OPS` - any future
        weight-tiered vendor can reuse it with its own convention tables."""
        return self._data.adjust_ops()

    def personas(self) -> list[dict[str, Any]]:
        return self._data.personas()

    def claims(self, ctx: JobContext) -> bool:
        return self._data.claims(ctx)

    def register_hooks(self, registry: HookRegistry) -> None:
        self._data.register_hooks(registry)  # the ladder (classifySignals)
        registry.register("beforePersonaLookup", _resolve_fingerprint, self.name)
        registry.register("afterExtraction", _apply_pricing_conventions, self.name)


PACK = SPTMetalsPack()

__all__ = ["PACK", "SPTMetalsPack", "conventions"]
