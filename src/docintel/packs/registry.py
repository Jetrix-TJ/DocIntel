"""The pack protocol, the loader, and the rule that decides which pack owns a document.

**How a pack claims a document.** Never by the filename, and never by asking a
human. A pack owns a document when the document belongs to that pack's *domain*,
which is a fact on the page - but what makes it that pack's domain differs by
pack, so `claims` is the pack's own decision rather than a rule imposed here.

The two shipped packs illustrate why the choice cannot be centralized:

* **Northstar** is an AP department. Every invoice it handles is billed *to*
  Northstar, so its guard is the bill-to - and `bill_to_name` is a required field
  precisely so a vendor invoice that arrived in the wrong inbox is not silently
  processed as though it belonged there.
* **Digital Direction** is a telecom expense manager. Its bills are addressed to
  several managed clients (`CLYDE COMPANIES`, `City of Dublin`, `Choctaw Travel
  Mart`), so there is no single recipient to guard on. What every one of its
  documents shares is that the sender is a known carrier, which is its domain by
  definition.

The sender still decides which *persona* applies (Stage 4). Keeping that separate
from the pack decision is what lets a brand-new vendor be processed at all, rather
than waiting for someone to declare which pack it belongs to.
"""

from __future__ import annotations

import importlib
import json
import os
from typing import Any, Protocol, runtime_checkable

from docintel.core.models import JobContext
from docintel.core.senders import normalize_name as normalize_name
from docintel.packs import datapack, signals
from docintel.pipeline.hooks import HookRegistry

# `normalize_name` is re-exported (not re-defined) for existing callers
# (`digitaldirection.__init__`, `.aliases`, `northstar.__init__`, `.aliases`)
# that import it from this module. The implementation lives in `core.senders`
# now - `core` is the lower layer and packs already depend on it, so this is
# the direction that cannot cycle. `core.senders` used to import FROM here,
# which only avoided an `ImportError` at interpreter start because pack
# modules are loaded lazily inside `load_packs()`; one module-level pack
# import in this file, or `pipeline/hooks.py` ever importing `core.senders`,
# would have turned that into a real cycle.

# Packs are named rather than discovered by directory scan. A pack is a
# deliberate business decision with a spec in docs/packs/, so it should not
# become active because someone dropped a folder in place.
PACK_MODULES: tuple[str, ...] = (
    "docintel.packs.northstar",
    "docintel.packs.digitaldirection",
    "docintel.packs.spt_metals",
)

# Data-only packs: a directory holding `pack.json` and `personas/`, with no
# Python at all. Listed here for exactly the reason modules are listed above -
# a pack is a deliberate business decision, so it must not become active because
# somebody dropped a folder on disk. What the declarative work changed is the
# COST of that decision (a config file instead of ~1,200 lines across eight
# modules), not whether one gets made.
#
# Paths are relative to this file's directory.
PACK_FILES: tuple[str, ...] = ("acme_freight/pack.json",)


@runtime_checkable
class Pack(Protocol):
    """What the pipeline and the grammar validator need from a pack.

    Deliberately narrow. `fields_for` / `required_fields` / `derived_only_fields`
    / `adjust_ops` are exactly the four members `grammar.schema.Pack` requires,
    so a pack object can be handed straight to `validate_persona` - which is what
    makes "every shipped persona passes V1-V13" a testable claim rather than an
    intention.
    """

    @property
    def name(self) -> str: ...

    @property
    def doc_types(self) -> tuple[str, ...]: ...

    @property
    def thresholds(self) -> dict[str, float]: ...

    @property
    def default_currency(self) -> str: ...

    @property
    def vendor_aliases(self) -> dict[str, str]: ...

    @property
    def display_names(self) -> dict[str, str]: ...

    def fields_for(self, doc_type: str) -> frozenset[str]: ...

    def required_fields(self, doc_type: str) -> frozenset[str]: ...

    def required_any_of(self, doc_type: str) -> tuple[frozenset[str], ...]: ...

    def derived_only_fields(self, doc_type: str) -> frozenset[str]: ...

    def adjust_ops(self) -> frozenset[str]: ...

    def personas(self) -> list[dict[str, Any]]: ...

    def claims(self, ctx: JobContext) -> bool: ...

    def register_hooks(self, registry: HookRegistry) -> None: ...


def load_packs() -> list[Pack]:
    """Every registered pack, in declaration order.

    Order matters for `resolve_pack`: the first pack that claims a document wins,
    so a more specific pack must be listed before a more general one.
    """
    packs: list[Pack] = []
    for module_path in PACK_MODULES:
        module = importlib.import_module(module_path)
        pack = module.PACK
        packs.append(pack)
    here = os.path.dirname(os.path.abspath(__file__))
    for relative in PACK_FILES:
        packs.append(datapack.load_pack_file(os.path.join(here, relative)))
    return packs


def resolve_pack(ctx: JobContext, packs: list[Pack] | None = None) -> Pack | None:
    """The pack whose organization this document is billed to, or None.

    None is a real answer, not a failure: an invoice addressed to somebody else
    should be processed generically and flagged, not forced into whichever pack
    happened to be first. Stage 3 records that as the `unclaimed_document` tag.
    """
    for pack in packs if packs is not None else load_packs():
        if pack.claims(ctx):
            return pack
    return None


# Sockets that fire BEFORE Stage 3 has resolved a pack. A hook on one of these
# cannot be gated on the claim, because there is nothing to gate on yet.
_UNGATED_SOCKETS: frozenset[str] = frozenset({"beforeIntake", "afterFilter"})


class _ClaimGatedRegistry:
    """A HookRegistry facade that gates one pack's hooks on that pack's claim.

    **Without this, adding a second pack silently breaks the first.** Every hook
    in a `HookRegistry` runs on every document, so Northstar's ladder would set
    `doc_type: standard_invoice` and Digital Direction's would immediately
    overwrite it with `telecom_bill` - after which every Northstar persona lookup
    misses and six documents fall back to the vision path. That is exactly what
    happened when the second pack was registered, and only the scorecard noticed:
    DTSS dropped from 23 passing assertions to 4.

    The gate lives here rather than in each pack's hooks because it is a registry
    invariant. A pack author should not have to remember it, and a pack that
    forgot would break a *different* pack - the worst kind of coupling.
    """

    def __init__(self, registry: HookRegistry, pack: Pack) -> None:
        self._registry = registry
        self._pack = pack

    def register(self, socket: str, fn: Any, pack: str) -> None:
        if socket in _UNGATED_SOCKETS:
            self._registry.register(socket, fn, pack)
            return

        owner = self._pack

        def gated(ctx: JobContext, next_: Any) -> JobContext:
            if ctx.pack is not owner:
                return next_(ctx)
            return fn(ctx, next_)

        # Keep the original name so `HookRegistry.registered` stays readable.
        gated.__name__ = getattr(fn, "__name__", "hook")
        self._registry.register(socket, gated, pack)


def register_all(registry: HookRegistry, packs: list[Pack] | None = None) -> None:
    """Give every pack its hooks, each gated on that pack having claimed.

    Called once when the pipeline is built.
    """
    for pack in packs if packs is not None else load_packs():
        pack.register_hooks(_ClaimGatedRegistry(registry, pack))  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Shared helpers for pack implementations
# --------------------------------------------------------------------------


def primary_text(ctx: JobContext) -> str:
    """Text of the pages a field value may be read from (grammar section 7).

    Pack ladders and guards use this rather than every page, for the same reason
    extraction does: a supporting Bill of Lading may name a different company,
    carry a different tax regime, or show a different total, and none of those
    are statements about the invoice it is attached to.

    The page SELECTION - including the fall back to every page when Stage 2 has
    not assigned roles yet - lives in `signals.primary_pages`, which this joins.
    It used to be implemented here as well, and two copies of a rule that happen
    to agree today is not a contract: `signals` is the closed registry a
    declarative ladder compiles against, so the selection has to be one thing.
    """
    return "\n".join(page.text for page in signals.primary_pages(ctx))


def load_basis_overlay(pack_dir: str) -> dict[str, str]:
    """A reviewer's confirmed `prior_balance_basis` decisions, read fresh.

    Same discipline as `DataPack.personas()`: read from disk on every call, no
    cache, because a decision made through the review UI (see `docintel.webui`)
    must take effect on the very next document with no restart - that is the
    whole point of separating this from the hardcoded `PRIOR_BALANCE_BASIS`
    table each pack's `conventions.py` still owns.

    Deliberately a SEPARATE, smaller trust tier, not a replacement for that
    table: `conventions.py` documents its own reasoning for why a wrong entry
    there must be a reviewed code change. An overlay entry is reachable only
    through an explicit reviewer "confirm" action (never agent-writable, never
    inferred), but it is still data on disk rather than code - a lower bar than
    a PR, appropriate for unblocking one vendor quickly, with promotion into the
    audited table as the deliberate next step once it's trusted.

    Missing file (the common case - most packs will never need an override) or
    a malformed one both return {} rather than raising: a broken overlay must
    never crash extraction for every vendor in the pack, only fail to help the
    one new vendor it was meant for.
    """
    path = os.path.join(pack_dir, "prior_balance_basis.local.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def all_text(ctx: JobContext) -> str:
    """Every page. For reference patterns, which legitimately run everywhere."""
    return "\n".join(page.text for page in ctx.pages)
