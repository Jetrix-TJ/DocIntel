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

Promoting an extracted field rather than re-scanning text is not a shortcut - it is
the only way to get the right value on Comcast. Its account number is printed
`8495 44 462 0365242` and its gold reference hit is `8495444620365242`, the
joinable form (F6). A text scan would capture the printed spacing and fail to join.

Every gold label in this pack sets `reference_list_complete: false`, because pages
2-N carry per-line service detail nobody transcribed. The scorecard therefore
compares as a superset: finding MORE keys than the label records is fine, finding
fewer is not.
"""

from __future__ import annotations

from docintel.core.models import JobContext, ReferenceHit

# (pattern_id, field to read, label to record). Order is the order hits appear.
#
# `account_number_normalized` is tried before `account_number` for F6's reason: the
# printed form and the joinable form are two different facts, and a reference hit
# exists to be joined on.
PROMOTED: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("invoice_number", ("invoice_number",), "Invoice Number"),
    ("account", ("account_number_normalized", "account_number"), "Account Number"),
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
    """The first of `field_names` that was extracted, as a plain string.

    `str()` rather than the raw object because an `AccountNumber` reaches here
    whenever a persona used the `account_number` pattern, and a reference hit is
    a joinable string by definition.
    """
    for name in field_names:
        value = ctx.extracted.get(name)
        if value is None:
            continue
        text = str(getattr(value, "raw", value)).strip()
        if text:
            return text
    return None
