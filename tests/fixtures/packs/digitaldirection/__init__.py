"""Pack: Digital Direction — telecom expense management.

Spec: `docs/packs/digital-direction.md`. Corpus documents 7-10: Centracom,
Comcast, Windstream, Lumen.

**Defining characteristic:** every carrier lays out its bill differently, most
print no invoice number at all, and the headline `Total Amount Due` routinely
includes a prior balance. The riskiest document in the entire corpus is in this
pack - Centracom, where reading the headline total overpays by $20,123.80.

**This pack claims by the CARRIER, not by the bill-to.** Northstar's pack can use
a bill-to guard because all six of its documents are billed to Northstar. Digital
Direction is a telecom expense manager processing bills for several managed
clients - `CLYDE COMPANIES`, `City of Dublin`, `Choctaw Travel Mart` - so there is
no single recipient to guard on. What every one of its documents has in common is
that the sender is a known carrier, which is the pack's domain by definition.

The managed-client list is kept as a secondary signal, because the pack spec asks
for `bill_to_name` to be a guard, and a carrier bill addressed to somebody who is
not a client is a real event worth flagging.
"""

from __future__ import annotations

import json
import os
from typing import Any

from docintel.core.models import JobContext
from docintel.packs import claims, registry
from . import (
    aliases,
    conventions,
    fields,
    hooks,
    ladder,
    references,
    thresholds,
)
from docintel.pipeline.hooks import HookRegistry

PERSONA_DIR = os.path.join(os.path.dirname(__file__), "personas")

# Compiled once at import from the same spec file the ladder uses.
# `MANAGED_CLIENTS` is read back out of the spec rather than duplicated beside
# it, so the roster cannot drift from the rule that uses it.
with open(ladder.SPEC_PATH) as _fh:
    _SPEC = json.load(_fh)
CLAIM_GUARD = claims.compile_claim(
    _SPEC["claim"], aliases=aliases.LITERAL_ALIASES, pack_name="digitaldirection"
)
MANAGED_CLIENTS: tuple[str, ...] = tuple(
    v
    for r in _SPEC["claim"]["rules"]
    if r["kind"] == "roster_on_short_line"
    for v in r["values"]
)




class DigitalDirectionPack:
    name = "digitaldirection"
    doc_types = fields.DOC_TYPES

    # Every corpus bill is USD. The last rung of the F14 ladder, and it carries
    # `currency_inferred_weak` when it is what answered.
    default_currency = "USD"

    @property
    def thresholds(self) -> dict[str, float]:
        return dict(thresholds.THRESHOLDS)

    @property
    def vendor_aliases(self) -> dict[str, str]:
        return dict(aliases.LITERAL_ALIASES)

    @property
    def display_names(self) -> dict[str, str]:
        """canonical key -> the name to report. See `aliases.DISPLAY_NAMES`."""
        return dict(aliases.DISPLAY_NAMES)

    @property
    def bill_to_roster(self) -> tuple[str, ...]:
        """The managed clients, for `resolve_bill_to_alias`.

        A client roster is business data, which is why it lives in the pack rather
        than in the personas that used to hardcode it: one table serves all four
        carriers, and onboarding a client is a config change instead of four rule
        rewrites. See `aliases.MANAGED_CLIENTS`.
        """
        return aliases.MANAGED_CLIENTS

    def fields_for(self, doc_type: str) -> frozenset[str]:
        return fields.fields_for(doc_type)

    field_set = fields_for

    def required_fields(self, doc_type: str) -> frozenset[str]:
        return fields.required_fields(doc_type)

    def required_any_of(self, doc_type: str) -> tuple[frozenset[str], ...]:
        return fields.required_any_of(doc_type)

    def derived_only_fields(self, doc_type: str) -> frozenset[str]:
        return fields.derived_only_fields(doc_type)

    def adjust_ops(self) -> frozenset[str]:
        """No pack ops. Every transformation these four bills need is already in
        the grammar's closed section 4 enum."""
        return frozenset()

    def claims(self, ctx: JobContext) -> bool:
        """Is the sender a carrier this pack manages?

        Carrier first, managed client second - see the module docstring for why
        the bill-to cannot be the primary guard here.

        The rules live in `classification.json` and are compiled by
        `packs.claims`, so onboarding a carrier or a client is a data change.
        """
        return CLAIM_GUARD.claims(ctx)

    def personas(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if os.path.isdir(PERSONA_DIR):
            for filename in sorted(os.listdir(PERSONA_DIR)):
                if not filename.endswith(".json"):
                    continue
                with open(os.path.join(PERSONA_DIR, filename)) as fh:
                    out.append(json.load(fh))
        # A new carrier's persona, from a directory the CALLER owns - see
        # registry.load_extra_personas's own docstring for why this lives
        # outside the installed package rather than beside PERSONA_DIR.
        out.extend(registry.load_extra_personas(self.name))
        return out

    def register_hooks(self, registry: HookRegistry) -> None:
        hooks.register(registry)


PACK = DigitalDirectionPack()

__all__ = [
    "MANAGED_CLIENTS",
    "PACK",
    "PERSONA_DIR",
    "DigitalDirectionPack",
    "aliases",
    "conventions",
    "fields",
    "hooks",
    "ladder",
    "references",
    "thresholds",
]
