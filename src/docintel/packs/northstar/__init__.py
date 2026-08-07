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
import re
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

# A marker that is NOT specific enough to claim on its own, paired with the
# corroboration that makes it safe.
#
# Real Edco second samples print the company name with OCR/print typos
# (NORTHSTART, NORTHSTAR RECY, NORTHSTRAY) that miss every marker above, but the
# state+zip prints correctly in all 4 confirmed cases, even the one where the
# city name is also garbled (confirmed 2026-08-05 against
# all-docs/second-samples/edco/{176024OCT25,709223OCT25,823282AUG25,823282SEP25}).
# So the ZIP was added to `BILL_TO_MARKERS` - and a bare ZIP claims any document
# that prints it. Measured 2026-08-07: the pack claimed an unrelated vendor's
# invoice billed to a DIFFERENT company at that ZIP, and one billed to a company
# in Austin whose only tie to East Longmeadow was a SHIP-TO block. A wrong claim
# is worse than no claim (`registry.resolve_pack`): an unclaimed document is
# emitted and flagged for a human, while a wrongly-claimed one runs this pack's
# entire rulebook - its ladder, its personas, its thresholds - against somebody
# else's invoice.
#
# `northst` is the corroboration because it is the longest prefix every real
# rendering shares, typos included: NORTHSTAR / NORTHSTART / NORTHSTRAY /
# NORTHSTAR RECY. Measured across ALL 28 real Edco second samples on 2026-08-07:
# 28 of 28 contain it, including all 4 that depend on the ZIP because no other
# marker matches them. It rejects both over-claims above, and `NORTHWIND OFFICE
# SUPPLY` - a deliberate near-miss in tests/packs/test_claim_precision.py.
CORROBORATED_MARKERS: tuple[tuple[str, str], ...] = (("ma 01028", "northst"),)

# Goods can be delivered here on an invoice that is billed to somebody else.
# `94 maple st east longmeadow` and `po box 188 east longmeadow` are Northstar's
# real addresses, and a marker hit inside a SHIP-TO block says where a pallet
# went, not who owes the money - which is the opposite of what a bill-to guard
# is for. Measured 2026-08-07 across all 111 second-samples: 100 documents carry
# a marker on a primary-page line, and for **zero** of them is every such line a
# ship-to line. So vetoing that case costs nothing real.
_SHIP_TO = re.compile(r"\bship\s*to\b", re.I)


def _every_marker_hit_is_ship_to(ctx: JobContext) -> bool:
    """Whether every line-level marker hit sits in a ship-to block.

    Deliberately a VETO on the text-level match rather than a replacement for
    it. A marker can legitimately wrap across two visual lines and so match the
    joined text while matching no single line; rebuilding the whole guard
    line-by-line would silently drop those documents. When there is no
    line-level hit at all this returns False and the text-level answer stands
    unchanged - so the veto can only ever remove a claim it can see the
    evidence for.
    """
    primary = {m.page_number for m in ctx.page_meta if m.role == "primary"}
    pages = [p for p in ctx.pages if p.page_number in primary] or list(ctx.pages)
    hits = [
        text
        for page in pages
        for line in page.lines()
        if any(
            marker in normalize_name(text := " ".join(w.text for w in line))
            for marker in BILL_TO_MARKERS + tuple(m for m, _ in CORROBORATED_MARKERS)
        )
    ]
    return bool(hits) and all(_SHIP_TO.search(text) for text in hits)


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

    @property
    def display_names(self) -> dict[str, str]:
        """canonical key -> the name to report. See `aliases.DISPLAY_NAMES`."""
        return dict(aliases.DISPLAY_NAMES)

    @property
    def bill_to_roster(self) -> tuple[str, ...]:
        """Every rendering of this AP department's own name, for
        `resolve_bill_to_alias`.

        One party, many spellings - the variation is the vendors', not the
        client's. This is the pack's guard against an invoice that arrived in the
        wrong inbox, held in one place instead of copied into each persona. See
        `aliases.BILL_TO_RENDERINGS`.
        """
        return aliases.BILL_TO_RENDERINGS

    # -- grammar.schema.Pack -------------------------------------------------

    def fields_for(self, doc_type: str) -> frozenset[str]:
        return fields.fields_for(doc_type)

    # The plan's name for the same thing. Kept as an alias rather than a second
    # implementation so the two can never disagree.
    field_set = fields_for

    def required_fields(self, doc_type: str) -> frozenset[str]:
        return fields.required_fields(doc_type)

    def required_any_of(self, doc_type: str) -> tuple[frozenset[str], ...]:
        return fields.required_any_of(doc_type)

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

        Two tiers. A `BILL_TO_MARKERS` hit claims on its own - each of those
        names the company or an address specific enough that no other business
        prints it. A `CORROBORATED_MARKERS` hit needs its partner token as well,
        because on its own it would claim any document that merely mentions a
        ZIP code; see that constant for the measurement.
        """
        haystack = normalize_name(primary_text(ctx))
        matched = any(marker in haystack for marker in BILL_TO_MARKERS) or any(
            marker in haystack and corroboration in haystack
            for marker, corroboration in CORROBORATED_MARKERS
        )
        return matched and not _every_marker_hit_is_ship_to(ctx)

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
    "CORROBORATED_MARKERS",
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
