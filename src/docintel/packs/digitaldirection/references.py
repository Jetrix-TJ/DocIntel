"""Reference patterns for Digital Direction — a different shape from Northstar's.

The pack spec's §1 comparison table states the reason outright:

| | Northstar AP | Digital Direction telecom |
|---|---|---|
| Match key | **Buried in free text** | **The account / circuit number, printed plainly** |

So Northstar's module scans page text for keys hidden under five different labels
(`NS # 2561194`, `WORK ORDER#: 4342903`, a bare 7-digit `Reference` column). This
one does the opposite: the keys are already extracted as first-class identity
fields, and what is missing is their **provenance as reference hits** so downstream
matching can join on them.

Promoting an extracted field rather than re-scanning text is what the pack shape
asks for: these keys are printed plainly and are already captured as identity
fields, so re-scanning would re-derive a value the pipeline is holding and would
have to re-decide, per carrier, which label owns it.

Getting the joinable form is a separate job, and it happens here rather than
upstream. Comcast prints its account number `8495 44 462 0365242`; its gold
reference hit is `8495444620365242` (F6). `_first` strips internal whitespace and
nothing else. Until the printed-fields-only narrowing a separate
`account_number_normalized` field was tried ahead of `account_number`; it was a
derived name and is gone, and the stripping moved into this module rather than
being lost with it.

Whitespace only, deliberately - not `AccountNumber.normalized`, which strips
hyphens too. Lumen's `5-QXH7QKM7` keeps its hyphen in gold, so the two carriers
disagree about what a separator is and only the spaces are safe to drop.

Every gold label in this pack sets `reference_list_complete: false`, because pages
2-N carry per-line service detail nobody transcribed. The scorecard therefore
compares as a superset: finding MORE keys than the label records is fine, finding
fewer is not.
"""

from __future__ import annotations

from docintel.core.models import JobContext, ReferenceHit
from docintel.grammar.ops.base import strip_internal_whitespace

# (pattern_id, fields to read, label to record). Order is the order hits appear.
# Each entry lists the fields to try in order, so a carrier that prints its key
# under a name another does not still resolves to one hit.
PROMOTED: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("invoice_number", ("invoice_number",), "Invoice Number"),
    ("account", ("account_number",), "Account Number"),
    ("circuit_id", ("circuit_id",), "Special Circuit"),
    ("telephone", ("telephone_number",), "Telephone Number"),
)


def collect(ctx: JobContext) -> JobContext:
    """Promote every extracted identity field into `reference_list`, deduplicated."""
    page = ctx.pages[0].page_number if ctx.pages else 1
    seen = {(h.value, h.pattern_id) for h in ctx.reference_list}

    for pattern_id, field_names, label in PROMOTED:
        value = _first(ctx, field_names)
        if value is None:
            continue
        key = (value, pattern_id)
        if key in seen:
            continue
        seen.add(key)
        ctx.reference_list.append(
            ReferenceHit(
                value=value,
                source_field=label,
                page=page,
                pattern_id=pattern_id,
            )
        )
    return ctx


def _first(ctx: JobContext, field_names: tuple[str, ...]) -> str | None:
    """The first of `field_names` that was extracted, in its joinable form.

    A reference hit exists to be joined on, so the printed form is stripped of
    internal whitespace - `8495 44 462 0365242` becomes `8495444620365242`, which
    is Comcast's gold hit (F6).

    **Not** `AccountNumber.normalized`, which also strips hyphens. Lumen's account
    number is printed `5-QXH7QKM7` and its gold hit keeps the hyphen, so
    `normalized` would give `5QXH7QKM7` and miss - the hyphen is part of that key
    rather than layout. Whitespace is the only separator the page adds for
    legibility, so it is the only one safe to remove here.

    The record still shows what the document printed: `fields.account_number`
    keeps the `AccountNumber` and Stage 8 crosses it as its printed form
    (`core/contract.py`). Only the reference hit joins.
    """
    for name in field_names:
        value = ctx.extracted.get(name)
        if value is None:
            continue
        printed = str(getattr(value, "raw", value)).strip()
        joinable = str(strip_internal_whitespace(printed))
        if joinable:
            return joinable
    return None
