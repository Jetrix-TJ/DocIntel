"""The pack protocol, the loader, and the rule that decides which pack owns a document.

**How a pack claims a document.** Not by the sender, and never by the filename.
A pack owns a document when the document is billed *to* that pack's organization,
which is a fact on the page. Northstar's pack claims an invoice addressed to
Northstar Recycling; Digital Direction's claims one addressed to Digital
Direction. That guard is why `bill_to_name` is a required field in both pack
specs: a vendor invoice that arrives in the wrong AP inbox must not be silently
processed as if it belonged there.

The sender decides which *persona* applies (Stage 4); the recipient decides which
*pack* applies (here). Conflating the two would mean a new vendor could not be
processed until someone told the system which pack it belonged to.
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


def register_all(registry: HookRegistry, packs: list[Pack] | None = None) -> None:
    """Give every pack its hooks. Called once when the pipeline is built."""
    for pack in packs if packs is not None else load_packs():
        pack.register_hooks(registry)


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
