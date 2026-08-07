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
from docintel.packs.digitaldirection import (
    aliases,
    conventions,
    fields,
    hooks,
    ladder,
    references,
    thresholds,
)
from docintel.packs.registry import normalize_name, primary_text
from docintel.pipeline.hooks import HookRegistry

PERSONA_DIR = os.path.join(os.path.dirname(__file__), "personas")

# Managed clients seen in the corpus. A secondary signal, not the claim: the
# client list grows every time Digital Direction signs one, whereas the carrier
# list is short and stable.
MANAGED_CLIENTS: tuple[str, ...] = (
    "clyde companies",
    "clyde administration",
    "city of dublin",
    "choctaw travel mart",
)


# How many words a line may carry and still be read as a bill-to block entry
# rather than prose or a line item. `BILL TO: CLYDE COMPANIES` is 4 words;
# `1x SIGNAGE FOR CITY OF DUBLIN PROJECT 2,400.00` - a real over-claim measured
# on 2026-08-07, where a print shop's invoice to a third party was claimed by
# this pack because a managed client was named in a line-item description - is 8.
_MAX_BILL_TO_LINE_WORDS = 6


def _managed_client_in_a_bill_to_block(ctx: JobContext) -> bool:
    """Whether a managed client is named on a SHORT line, not buried in prose.

    The secondary half of `claims`. It used to be a bare substring test over the
    whole primary text, which claims any document that mentions a client
    anywhere - including one that merely describes work done for them.

    **This path has no real-document coverage, and that is stated rather than
    hidden.** Measured across all 111 second-samples on 2026-08-07: every one of
    the 7 Digital Direction documents is claimed by its CARRIER alias, and
    exactly **zero** reach this fallback. So the word cutoff above is fitted to
    the over-claim it rejects and to the shape of a bill-to line, not to a real
    document that needs it - unlike every other constant in this pack. It is
    kept rather than deleted because the pack's growth path is a bill from a
    carrier not yet in the alias table, addressed to a client who is; deleting
    it would make that document `unclaimed_document` instead. The first real
    document to arrive through here should be used to re-derive the cutoff.
    """
    primary = {m.page_number for m in ctx.page_meta if m.role == "primary"}
    pages = [p for p in ctx.pages if p.page_number in primary] or list(ctx.pages)
    for page in pages:
        for line in page.lines():
            if len(line) > _MAX_BILL_TO_LINE_WORDS:
                continue
            haystack = normalize_name(" ".join(w.text for w in line))
            if any(client in haystack for client in MANAGED_CLIENTS):
                return True
    return False


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
        """
        text = primary_text(ctx)
        if aliases.canonical(text) is not None:
            return True
        return _managed_client_in_a_bill_to_block(ctx)

    def personas(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not os.path.isdir(PERSONA_DIR):
            return out
        for filename in sorted(os.listdir(PERSONA_DIR)):
            if not filename.endswith(".json"):
                continue
            with open(os.path.join(PERSONA_DIR, filename)) as fh:
                out.append(json.load(fh))
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
