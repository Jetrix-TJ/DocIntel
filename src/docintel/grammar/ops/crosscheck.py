"""Consistency ops (`selector-grammar.md` section 4.3) - **scoring only**.

Not one of these may change a value. They raise a per-field boost when the
document corroborates itself and apply a confidence modifier when it does not.
The division of labour against `derive` matters: `derive_amount_payable`
*refuses* on bad arithmetic because it has to decide a number;
`crosscheck_balance_composition` *scores* the same arithmetic because confidence
is a separate question from correctness. Both are listed in section 4 and both
are needed.

Boosts are capped (`core.confidence.BOOST_CAP` 1.10, ceiling 0.99) because
corroboration is not proof: three agreeing renderings of an OCR'd number can
still all be wrong the same way.

**Measured composition facts.** The two corpus documents that print a subtotal
compose their totals differently, and no single formula covers both:

```
U-PAK    subtotal 8119.44 + charges 6670.33                     == 14789.77
         (its 2325.69 H.S.T. is already inside those parts)
Veritiv  subtotal 4608.45 +                    tax 299.55       ==  4908.00
```

So `crosscheck_total_composition` tries every plausible decomposition and boosts
if **any** closes, flagging only when none does. Picking one formula would
false-flag whichever vendor did not use it, and a false mismatch on a correct
extraction is worse than a missed corroboration - it trains reviewers to ignore
the flag.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from docintel.core.models import JobContext
from docintel.extract import scanline as scanline_mod
from docintel.grammar.ops.derive import CLOSURE_TOLERANCE, _field, _money

# Columns of a row group that hold an amount rather than a rate or a count.
# Matches `scorecard.LINE_ITEM_AMOUNT_COLUMNS` by intent: summing `unit_price`
# would be meaningless.
AMOUNT_COLUMNS = frozenset({"amount", "charges", "balance", "total"})

# Digits below this are too short for "appears in the filename" to mean anything
# (F17): a 2-digit total matches almost any filename containing a date.
_MIN_FILENAME_DIGITS = 3

# What a human might have named the file after, most specific first.
#
# `amount_payable` and `account_number` were missing and their absence was
# expensive. Two corpus filenames name exactly those:
#
#   EDCO 77087APR25 current charges can be misleading, paying $69.62.pdf
#        ^ vendor account                                     ^ the PAYABLE, 69.62
#   Centracom_0384043574_01012026_BILL.pdf
#             ^ the account number
#
# Checking only `invoice_number` and `total_printed` reported `disagree` on both -
# and since `filename_disagree` is a document-wide modifier, that x0.95 dragged
# EVERY field below its threshold and routed five documents to `medium` when their
# gold expects `high`. A wrong crosscheck is not a cosmetic problem.
#
# `amount_payable` is read from `derived`, which is the only place it can be.
FILENAME_CANDIDATES: tuple[str, ...] = (
    "invoice_number",
    "account_number",
    "vendor_account_number",
    "amount_payable",
    "total_printed",
)


def _plain(value: Any) -> str:
    """A value's own text, never its repr.

    An `AccountNumber` reaches here whenever a persona used the `account_number`
    pattern, and `str()` on it yields the dataclass repr - so its digits came back
    DOUBLED (raw and normalized concatenated) and never matched a filename.
    Comcast's `Comcast_8495 44 462 0365242_...pdf` was reported as a disagreement
    with its own account number in the name.
    """
    for attribute in ("normalized", "raw"):
        text = getattr(value, attribute, None)
        if isinstance(text, str):
            return text
    return str(value)


def _boost(ctx: JobContext, field: str) -> None:
    ctx.boosts[field] = ctx.boosts.get(field, 0) + 1


def _row_sum(rows: list[dict[str, Any]] | None) -> Decimal | None:
    """Signed sum of every amount column across a row group, or None if empty."""
    if not rows:
        return None
    total = Decimal("0")
    seen = False
    for row in rows:
        for column, value in row.items():
            if column not in AMOUNT_COLUMNS:
                continue
            amount = _money(value)
            if amount is not None:
                total += amount
                seen = True
    return total if seen else None


def _closes(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= CLOSURE_TOLERANCE


def crosscheck_line_sum(ctx: JobContext) -> JobContext:
    """Sum of the line items against the printed subtotal (F8).

    Requires a printed `subtotal`. Only two corpus documents print one and only
    Veritiv also has transcribable line items, where 4608.45 closes exactly.

    That requirement is what keeps EDCO out of this check. EDCO's statement table
    prints its own `CURRENT CHARGES:` summary row *inside* the table body, so its
    amount columns sum to 805.54 against a printed total of 367.96 - faithfully
    transcribed and not an error. EDCO prints no subtotal, so the op skips it
    rather than flagging a document that is entirely correct.
    """
    subtotal = _field(ctx, "subtotal")
    line_sum = _row_sum(ctx.row_groups.get("line_items"))
    if subtotal is None or line_sum is None:
        return ctx

    if _closes(line_sum, subtotal):
        _boost(ctx, "subtotal")
        return ctx
    ctx.add_modifier("arith_lines_mismatch")
    ctx.log(f"s6: line items sum to {line_sum} against a printed subtotal of {subtotal}")
    return ctx


def crosscheck_total_composition(ctx: JobContext) -> JobContext:
    """Does the printed total decompose into the parts the document lists (F8)?

    Boosts if any plausible decomposition closes - see the module docstring for
    why "any" rather than one fixed formula.
    """
    printed = _field(ctx, "total_printed")
    subtotal = _field(ctx, "subtotal")
    if printed is None or subtotal is None:
        return ctx

    charges = _row_sum(ctx.row_groups.get("charges")) or Decimal("0")
    tax = _field(ctx, "tax_amount") or Decimal("0")
    candidates = {
        subtotal + charges,
        subtotal + tax,
        subtotal + charges + tax,
    }

    if any(_closes(candidate, printed) for candidate in candidates):
        _boost(ctx, "total_printed")
        return ctx
    ctx.add_modifier("arith_total_mismatch")
    ctx.log(
        f"s6: printed total {printed} matches no decomposition of subtotal "
        f"{subtotal}, charges {charges} and tax {tax}"
    )
    return ctx


def crosscheck_balance_composition(ctx: JobContext) -> JobContext:
    """Carried balance plus current charges against the printed total (F8).

    Scores the same arithmetic `derive_amount_payable` refuses on, and against
    the **carried** balance for the same reason: on the three `gross` documents
    the raw prior double-counts a payment already made.
    """
    printed = _field(ctx, "total_printed")
    current = _field(ctx, "current_charges")
    carried = _money(ctx.derived.get("carried_balance"))
    if printed is None or current is None or carried is None or carried == 0:
        return ctx

    if _closes(carried + current, printed):
        _boost(ctx, "total_printed")
        _boost(ctx, "current_charges")
        return ctx
    # 0.80 and a review flag - the harshest modifier in the enum, because this is
    # the arithmetic that decides what gets paid.
    ctx.add_modifier("arith_balance_mismatch")
    ctx.review_flag = True
    ctx.log(
        f"s6: carried {carried} + current {current} != printed {printed}"
    )
    return ctx


def crosscheck_scanline(ctx: JobContext) -> JobContext:
    """Do the stub's machine-readable digits corroborate what was read (F7)?

    Only the four fields `scanline.CORROBORATABLE_FIELDS` permits are tried, and
    `corroborates` raises on anything else rather than answering a question the
    scan line has no business answering. Centracom's scan line encodes the
    *misleading* headline total, so a scan line "confirming" the payable would
    confirm the wrong number.
    """
    if not ctx.scanline:
        return ctx

    declared = _declared_asserts(ctx)
    if not declared:
        # No scanline selector, or one that asserts nothing. Section 1.3 makes the
        # `asserts` array the persona's statement about WHICH fields this
        # particular stub vouches for; with no statement there is nothing to check.
        return ctx

    for field in sorted(declared):
        value = ctx.extracted.get(field)
        if value is None:
            continue
        if not scanline_mod.is_corroboratable(value):
            # Too few digits to conclude anything either way. Silence is the only
            # honest answer - see `scanline.is_corroboratable`.
            ctx.log(
                f"s6: {field}={value!r} has too few digits for the scan line to "
                "corroborate; neither boosted nor flagged"
            )
            continue
        if scanline_mod.corroborates(ctx.scanline, value, field):
            _boost(ctx, field)
        else:
            ctx.add_field_modifier(field, "scanline_mismatch")
            ctx.log(f"s6: {field}={value!r} does not appear in the scan line digits")
    return ctx


def _declared_asserts(ctx: JobContext) -> set[str]:
    """The fields the persona's scanline selector says this stub corroborates.

    **The persona decides, not this op.** An earlier version looped over all of
    `scanline.CORROBORATABLE_FIELDS`, which overrode the persona's own declaration
    and produced a false mismatch on Windstream: its scan line embeds `250719`, a
    BILLING CYCLE date matching neither its bill date (07-22) nor its due date
    (08-11), and its persona correctly asserts only `total_printed` and
    `account_number`. Checking `due_date` anyway applied `scanline_mismatch` to a
    correctly-extracted field and cost the document its lane.

    Section 1.3's permitted set is still the ceiling - the validator enforces it at
    write time (V7). This is the persona choosing from within it.
    """
    declared: set[str] = set()
    for selector in getattr(ctx.persona, "field_selectors", ()) or ():
        for assertion in getattr(selector, "asserts", ()) or ():
            name = getattr(assertion, "field", None)
            if name in scanline_mod.CORROBORATABLE_FIELDS:
                declared.add(name)
    return declared


def crosscheck_duplicate_anchor(ctx: JobContext) -> JobContext:
    """The same figure printed twice - in the body and on the stub (F12).

    Agreement corroborates; disagreement is a review flag, never a silent pick.
    Only meaningful on a field captured with `capture: all_matches`, which is how
    a persona says "this label appears more than once and I want to see both".
    """
    for field, value in list(ctx.extracted.values.items()):
        if not isinstance(value, list) or len(value) < 2:
            continue
        distinct = {str(item) for item in value}
        if len(distinct) == 1:
            _boost(ctx, field)
            continue
        ctx.review_flag = True
        ctx.log(
            f"s6: {field} was printed more than once with different values "
            f"{sorted(distinct)}; a human must decide which is meant"
        )
    return ctx


def crosscheck_filename(ctx: JobContext) -> JobContext:
    """Does the filename agree with what was extracted (F17)?

    Records `filename_crosscheck` as `agree`, `disagree` or `absent` rather than
    only a boolean, because the three states mean genuinely different things to a
    reviewer. This corpus is the reason it matters: one file is literally named
    *"current charges can be misleading, paying $69.62"*, and a human's filename
    is real evidence about intent.

    Never authoritative. A filename is a human note, so a disagreement lowers
    confidence by the gentlest modifier in the enum (0.95) and changes no value.
    """
    filename = (ctx.source_path or "").rsplit("/", 1)[-1]
    haystack = "".join(ch for ch in filename if ch.isdigit())

    # A filename with almost no digits can neither agree nor disagree. Lumen's is
    # `Lumen - 5-QXH7QKM7.pdf`, whose only digit is the `5` in its account key -
    # calling that a disagreement applied a document-wide x0.95 to every field and
    # cost the document its lane. Same principle as `scanline.is_corroboratable`.
    if len(haystack) < _MIN_FILENAME_DIGITS:
        ctx.derived.set("filename_crosscheck", "absent")
        return ctx

    checked = False
    for field in FILENAME_CANDIDATES:
        value = ctx.extracted.get(field)
        if value is None:
            value = ctx.derived.get(field)
        if value is None:
            continue
        digits = "".join(ch for ch in _plain(value) if ch.isdigit())
        if len(digits) < _MIN_FILENAME_DIGITS:
            continue
        checked = True
        if digits in haystack:
            ctx.derived.set("filename_crosscheck", "agree")
            _boost(ctx, field)
            return ctx

    if not checked or not haystack:
        ctx.derived.set("filename_crosscheck", "absent")
        return ctx

    ctx.derived.set("filename_crosscheck", "disagree")
    ctx.add_modifier("filename_disagree")
    ctx.log(f"s6: nothing extracted appears in the filename {filename!r}")
    return ctx
