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
import re
from typing import Any, Protocol, runtime_checkable

from docintel.core.models import JobContext
from docintel.pipeline.hooks import HookRegistry

# Packs are named rather than discovered by directory scan. A pack is a
# deliberate business decision with a spec in docs/packs/, so it should not
# become active because someone dropped a folder in place.
PACK_MODULES: tuple[str, ...] = (
    "docintel.packs.northstar",
    "docintel.packs.digitaldirection",
)


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

    def fields_for(self, doc_type: str) -> frozenset[str]: ...

    def required_fields(self, doc_type: str) -> frozenset[str]: ...

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
    """
    primary = {m.page_number for m in ctx.page_meta if m.role == "primary"}
    if not primary:
        # No roles assigned yet. Falling back to every page is right here rather
        # than fail-closed: a classifier that classifies nothing is worse than
        # one that occasionally reads a supporting page, and Stage 2 always
        # assigns roles before Stage 3 in the real pipeline.
        return "\n".join(page.text for page in ctx.pages)
    return "\n".join(p.text for p in ctx.pages if p.page_number in primary)


def all_text(ctx: JobContext) -> str:
    """Every page. For reference patterns, which legitimately run everywhere."""
    return "\n".join(page.text for page in ctx.pages)


def normalize_name(value: str) -> str:
    """Collapse a printed company name to a comparable form.

    Punctuation is dropped rather than kept, because the corpus prints the same
    company as `D.T.S.S. Inc.`, `D T S S INC` and `DTSS` - and an alias table
    keyed on punctuation would need an entry per rendering.
    """
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
