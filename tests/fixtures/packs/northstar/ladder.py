"""Northstar's classification ladder and tags (pack spec section 1).

**First signal that fires wins, then the ladder stops** (spec Stage 3). Content
only, never the filename - three of the six corpus filenames state the answer
outright (`CONTRA ONLY ...`, `CANADIAN WITHOUT NOTES ...`, `... current charges
can be misleading, paying $69.62`) and a classifier that read them would score
well and teach nothing.

**Ladder order is load-bearing.** `contra_invoice` sits *above*
`invoice_with_attachment` because Federal Recycling is a single-page contra and
Complete Beverage is a multi-page invoice that also contains negative lines.
Testing "has attachments" first would classify any multi-page invoice with a
rebate line as an attachment case; testing "has negatives" first would classify
Complete Beverage as contra.

Tags are layered on and never change the type.
"""

from __future__ import annotations

import json
import os

from docintel.core.models import JobContext
from docintel.packs import declarative

# Compiled once at import, not once per document: `compile_classification`
# compiles regexes and resolves value predicates, and paying that on every
# invoice in a batch of thousands would be waste. Compiling at import also means
# a malformed spec fails when the pack is loaded rather than when the first
# document that would have matched arrives - the whole point of validating at
# load (see `packs.declarative`).
SPEC_PATH = os.path.join(os.path.dirname(__file__), "classification.json")

with open(SPEC_PATH) as _fh:
    LADDER, TAG_RULES = declarative.compile_classification(json.load(_fh))


def doc_type_for(ctx: JobContext) -> tuple[str, str]:
    """(doc_type, signal_that_fired). The section 1 ladder, in order."""
    return LADDER.doc_type_for(ctx)


def tags_for(ctx: JobContext) -> list[str]:
    """Every tag the document earns. Layered on; never changes the type."""
    return TAG_RULES.tags_for(ctx)


def classify(ctx: JobContext) -> JobContext:
    """Set `doc_type`, `signal_that_fired` and the tags. Idempotent."""
    doc_type, signal = doc_type_for(ctx)
    ctx.doc_type = doc_type
    ctx.signal_that_fired = signal
    ctx.classification_confidence = 0.95 if signal != "default" else 0.80
    for tag in tags_for(ctx):
        ctx.add_tag(tag)
    return ctx
