"""Pack: Northstar Recycling — vendor AP invoices.

Spec: `docs/packs/northstar-recycling.md`. Corpus documents 1-6 of
`docs/corpus-analysis.md`: D.T.S.S., Veritiv, Complete Beverage, Federal
Recycling, U-Pak, EDCO.

**Defining characteristic:** commodity credits and service fees appear on the
same invoice with opposite signs, and the match key back to Northstar's system of
record is buried in free text under at least five different labels.
"""

from __future__ import annotations

import json
import os
from typing import Any

from docintel.core.models import JobContext
from docintel.packs.northstar import aliases, fields, hooks, ladder, references, thresholds
from docintel.packs.registry import normalize_name, primary_text
from docintel.pipeline.hooks import HookRegistry

PERSONA_DIR = os.path.join(os.path.dirname(__file__), "personas")

# How this pack recognizes a document as its own: the invoice is billed TO
# Northstar. Several spellings, because the corpus prints the company as
# `Northstar Recycling Company, LLC`, `NORTHSTAR RECYCLING COMPANY LLC`,
# `NorthStar Recycling Company, LLC` and `Northstar-Bimbo-Market Street`, and the
# PO Box appears without the company name at all on the EDCO remittance stub.
BILL_TO_MARKERS: tuple[str, ...] = (
    "northstar recycling",
    "northstar bimbo",
    "nsrecycle com",
    "po box 188 east longmeadow",
    "94 maple st east longmeadow",
)


class NorthstarPack:
    """The pack object the pipeline and the grammar validator both bind to."""

    name = "northstar"
    doc_types = fields.DOC_TYPES

    # The last rung of the F14 currency ladder. A pack POLICY, not something any
    # document says - which is exactly why it lives here and carries the
    # `currency_inferred_weak` penalty when it is what answered.
    default_currency = "USD"

    @property
    def thresholds(self) -> dict[str, float]:
        return dict(thresholds.THRESHOLDS)

    @property
    def vendor_aliases(self) -> dict[str, str]:
        return dict(aliases.LITERAL_ALIASES)

    # -- grammar.schema.Pack -------------------------------------------------

    def fields_for(self, doc_type: str) -> frozenset[str]:
        return fields.fields_for(doc_type)

    # The plan's name for the same thing. Kept as an alias rather than a second
    # implementation so the two can never disagree.
    field_set = fields_for

    def required_fields(self, doc_type: str) -> frozenset[str]:
        return fields.required_fields(doc_type)

    def derived_only_fields(self, doc_type: str) -> frozenset[str]:
        return fields.derived_only_fields(doc_type)

    def adjust_ops(self) -> frozenset[str]:
        """Pack-registered ops on top of the grammar's base enum.

        Empty, and that is the design working rather than a gap: every
        transformation Northstar's six documents need is already in section 4's
        closed enum. A pack op would be a business-logic change needing a PR and
        an eval, and nothing in this corpus asks for one.
        """
        return frozenset()

    # -- claiming ------------------------------------------------------------

    def claims(self, ctx: JobContext) -> bool:
        """Is this invoice billed to Northstar?

        The `bill_to_name` guard from the spec's field table, applied before any
        extraction. A vendor invoice that landed in the wrong AP inbox must not be
        processed as though it belonged here.
        """
        haystack = normalize_name(primary_text(ctx))
        return any(marker in haystack for marker in BILL_TO_MARKERS)

    # -- personas ------------------------------------------------------------

    def personas(self) -> list[dict[str, Any]]:
        """Every shipped persona, newest `rule_version` first is not attempted.

        Read from JSON on every call rather than cached: a persona is data, the
        files are small, and a cache here would mean an authoring session had to
        restart the process to see its own edit.
        """
        out: list[dict[str, Any]] = []
        if not os.path.isdir(PERSONA_DIR):
            return out
        for filename in sorted(os.listdir(PERSONA_DIR)):
            if not filename.endswith(".json"):
                continue
            with open(os.path.join(PERSONA_DIR, filename)) as fh:
                out.append(json.load(fh))
        return out

    # -- hooks ---------------------------------------------------------------

    def register_hooks(self, registry: HookRegistry) -> None:
        hooks.register(registry)


PACK = NorthstarPack()

__all__ = [
    "BILL_TO_MARKERS",
    "PACK",
    "PERSONA_DIR",
    "NorthstarPack",
    "aliases",
    "fields",
    "hooks",
    "ladder",
    "references",
    "thresholds",
]
