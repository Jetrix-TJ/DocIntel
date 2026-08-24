"""Derivation ops - the F1 machinery (`selector-grammar.md` section 4.2).

This module is the reason the project exists. On 7 of the 10 corpus documents
`amount_payable == total_printed`, so reading the headline total looks correct
almost everywhere. On one corpus vendor it is wrong by a five-figure amount, and
on another by a few hundred dollars. `tests/test_f1_antiregression.py` exists to
stop anyone collapsing this back into "read the total".

**The rule, stated once.** What is payable is the *current* charges whenever a
balance is genuinely carried forward, and the *printed total* when nothing is.
Deciding which requires knowing what the printed prior balance means, and that
differs by vendor (F1b):

| `prior_balance_basis` | Carried balance is |
|---|---|
| `gross` | `prior_balance + payments_credits` - the payment is inside the prior |
| `net_of_payments` | `prior_balance` exactly as printed - payments already deducted |
| absent | **undeterminable**: review flag, never a default |

Measured against all five corpus documents that print a prior balance, the
closure `carried_balance + current_charges == total_printed` holds exactly.
Figures below are synthetic - this docstring should not double as an answer
key; what matters is the shape of the rule, not the numbers:

```
ExampleVendorA   1000.00 +  700.00 ==  1700.00   (net_of_payments)
ExampleVendorB     50.00 +   25.00 ==    75.00   (gross, no payment)
ExampleVendorC      0.00 +  100.00 ==   100.00   (gross, payment clears it)
ExampleVendorD      0.00 +  200.00 ==   200.00   (gross, payment clears it)
ExampleVendorE      0.00 +  300.00 ==   300.00   (gross, payment clears it)
```

Section 4.2 words that check as `prior_balance + current_charges != total_printed`.
That wording predates F1b and is only correct for `net_of_payments`, where the
carried balance *is* the prior; on the three `gross` documents the raw prior
double-counts a payment that has already been made. The check is therefore
written against the **carried** balance, which reduces to the spec's wording in
the `net_of_payments` case.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from docintel.core.models import JobContext
from docintel.core.money import parse_money

# Money closes to the cent or it does not close. This is a rounding tolerance,
# not a fudge factor: anything larger starts absorbing real discrepancies, which
# is exactly what a corpus document's unexplained gap between two printed
# totals must not be allowed to do (see the F8 disagreement below).
CLOSURE_TOLERANCE = Decimal("0.01")

GROSS = "gross"
NET_OF_PAYMENTS = "net_of_payments"


def _money(value: Any) -> Decimal | None:
    """Coerce an extracted value to Decimal, or None if it is not money-shaped.

    Never float arithmetic: the closure checks above demand exact equality, and
    a float tolerance is where that rots. A float arriving here (from a
    hand-written fixture, say) is routed through `str` so it keeps its printed
    precision rather than its binary approximation.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        parsed = parse_money(value)
        if parsed is not None:
            return parsed
        try:
            return Decimal(value.strip())
        except (InvalidOperation, ValueError):
            return None
    return None


def _field(ctx: JobContext, name: str) -> Decimal | None:
    """A money field, preferring an extracted value but accepting a derived one.

    `subtract_prior_balance_if_present` can supply `current_charges` when the
    document does not print it, and it must land in `derived` rather than
    `extracted` because nothing read it off a page. Looking in both here is what
    makes the two ops compose.
    """
    value = _money(ctx.extracted.get(name))
    if value is None:
        value = _money(ctx.derived.get(name))
    return value


def _refuse(ctx: JobContext, reason: str) -> JobContext:
    """Record that the payable could not be determined, and why.

    Explicitly sets both keys to None rather than leaving them absent: a
    consumer must be able to tell "we looked and could not decide" from "this
    pipeline never tried". U-PAK's gold label carries exactly this shape.
    """
    ctx.derived.set("amount_payable", None)
    ctx.derived.set("payable_basis", None)
    ctx.add_modifier("arith_balance_mismatch")
    ctx.review_flag = True
    ctx.log(f"s6: amount_payable not derived - {reason}")
    return ctx


def normalize_credit_sign(ctx: JobContext) -> JobContext:
    """Force `payments_credits` negative however it was printed (F4).

    The corpus prints a credit four different ways - `-84.50 cr`,
    `$612.30 CR`, `(45.00)`, and an unsigned column whose header says
    "Payments" - and `parse_money` already resolves the first three. The fourth
    is why this op exists: an unsigned 612.30 in a payments column would be
    *added* to the prior balance and double it.

    Must run before any arithmetic. `ops.ORDER` puts it first for that reason.
    """
    value = _money(ctx.extracted.get("payments_credits"))
    if value is None or value <= 0:
        return ctx
    quality = ctx.extracted.match_quality.get("payments_credits", 1.0)
    ctx.extracted.set("payments_credits", -value, quality)
    ctx.log("s6: normalize_credit_sign flipped an unsigned payments_credits negative")
    return ctx


def resolve_carried_balance(ctx: JobContext) -> JobContext:
    """Compute what is actually still owed from before this invoice (F1b).

    A missing basis is a **review flag and no value**, never a default. Guessing
    `gross` would double-subtract a payment on Centracom; guessing
    `net_of_payments` would carry a paid-off balance forward on Comcast. Both are
    wrong in opposite directions, which is precisely why there is no safe default.
    """
    prior = _money(ctx.extracted.get("prior_balance"))
    if prior is None:
        # No prior balance printed. That is not missing information - most
        # invoices simply do not carry one - so no basis is needed and nothing
        # is flagged.
        ctx.derived.set("carried_balance", Decimal("0"))
        return ctx

    basis = ctx.extracted.get("prior_balance_basis")
    if basis == NET_OF_PAYMENTS:
        # Printed net: payments are already deducted. Subtracting them again
        # would fail LOW, which is as wrong as F1 and much harder to notice.
        ctx.derived.set("carried_balance", prior)
        return ctx

    if basis == GROSS:
        payments = _money(ctx.extracted.get("payments_credits")) or Decimal("0")
        ctx.derived.set("carried_balance", prior + payments)
        return ctx

    ctx.review_flag = True
    ctx.log(
        "s6: prior_balance is present but prior_balance_basis is "
        f"{basis!r}; the carried balance is undeterminable and will not be guessed"
    )
    return ctx


def derive_amount_payable(ctx: JobContext) -> JobContext:
    """Decide what should actually be paid, and record why (F1).

    Never guesses. There are three separate ways this refuses, and each one is a
    real corpus document rather than a defensive hypothetical:

    1. **Two printed payables that disagree** - one corpus document prints
       `5,432.10` as its total and `5,400.00` as `Please Pay`, with the aging
       columns all zero and nothing on the page explaining the 32.10 difference
       (F8). A human has to resolve that; averaging it away or picking the
       smaller one would be inventing a business decision.
    2. **A prior balance whose basis could not be resolved** - see
       `resolve_carried_balance`.
    3. **Arithmetic that does not close** - `carried + current != printed`.
    """
    printed = _field(ctx, "total_printed")
    please_pay = _field(ctx, "please_pay")
    current = _field(ctx, "current_charges")
    prior = _money(ctx.extracted.get("prior_balance"))
    carried = _money(ctx.derived.get("carried_balance"))

    if (
        printed is not None
        and please_pay is not None
        and abs(printed - please_pay) > CLOSURE_TOLERANCE
    ):
        return _refuse(
            ctx,
            f"total_printed {printed} and please_pay {please_pay} disagree by "
            f"{abs(printed - please_pay)} with nothing on the document explaining it",
        )

    if prior is not None and carried is None:
        return _refuse(ctx, "a prior balance is printed but its basis is undeterminable")

    if carried is None:
        carried = Decimal("0")

    if carried != 0 and current is not None and printed is not None:
        if abs((carried + current) - printed) > CLOSURE_TOLERANCE:
            return _refuse(
                ctx,
                f"carried balance {carried} + current charges {current} != "
                f"printed total {printed}",
            )

    if carried != 0:
        if current is None:
            return _refuse(
                ctx,
                f"a balance of {carried} is carried forward but no current charges "
                "were found, so the payable cannot be separated from the total",
            )
        ctx.derived.set("amount_payable", current)
        ctx.derived.set("payable_basis", "current_charges")
        return ctx

    if printed is None:
        return _refuse(ctx, "no total_printed was extracted")

    # Nothing carried forward, so the printed total is what is owed. `please_pay`
    # agreeing with it (checked above) is corroboration, not a second source.
    ctx.derived.set("amount_payable", printed)
    ctx.derived.set("payable_basis", "total_printed")
    return ctx


def subtract_prior_balance_if_present(ctx: JobContext) -> JobContext:
    """Supply `current_charges` as `total_printed - carried_balance`.

    Only for documents that carry a balance but never print the current-charges
    line separately. Writes to `derived`, not `extracted`: nothing read this off
    a page, and `ExtractedFields` is for values that were.

    Does nothing when `current_charges` was extracted - a printed figure always
    beats a computed one, because the arithmetic that would produce it is exactly
    the arithmetic `derive_amount_payable` is about to check.
    """
    if ctx.extracted.get("current_charges") is not None:
        return ctx
    printed = _money(ctx.extracted.get("total_printed"))
    carried = _money(ctx.derived.get("carried_balance"))
    if printed is None or carried is None or carried == 0:
        return ctx
    ctx.derived.set("current_charges", printed - carried)
    ctx.log(f"s6: current_charges derived as {printed} - {carried}")
    return ctx


def prefer_current_charges_line(ctx: JobContext) -> JobContext:
    """When several current-charge anchors matched, keep the operative one.

    Section 4.1 defines this as "take the one nearest the totals block". The
    executor does not record where each of an `all_matches` list came from, so
    proximity is approximated by document order: the **last** match, because a
    recap of current charges appears above the totals block and the operative
    figure appears in it.

    That approximation is honest but it is an approximation. Making it exact
    needs the executor to carry a position per captured value; no corpus persona
    requires that yet, and adding the field speculatively would be dead weight
    on every other selector.
    """
    value = ctx.extracted.get("current_charges")
    if not isinstance(value, list) or not value:
        return ctx
    quality = ctx.extracted.match_quality.get("current_charges", 1.0)
    ctx.extracted.set("current_charges", value[-1], quality)
    ctx.log(
        f"s6: prefer_current_charges_line kept the last of {len(value)} matches"
    )
    return ctx


def derive_document_identity(ctx: JobContext) -> JobContext:
    """The key downstream dedup joins on (F6). NOT an `adjust` op - see `ops`.

    Three of the ten corpus documents print no invoice number at all, so an
    identity built only from one would silently starve the duplicate decision for
    30% of the corpus. The ladder, and `identity_basis` records which rung fired:

    1. `invoice_number` -> basis `invoice_number`
    2. an account number plus the billing period -> basis `account_period`
    3. Stage 1's `soft_fingerprint` (sender + filename + byte size), when even
       that was set -> basis `soft_fingerprint`. Deliberately the WEAKEST rung:
       it identifies "the same file arrived again", not "the same business
       document" - two different documents from the same sender that happen
       to share a filename and byte count would collide. That is exactly why
       this basis is distinguishable from the other two (a consumer, e.g. the
       review UI, can and should treat it as a lower-confidence hint), and why
       `IdentityIndex` only ever sets the advisory `possible_duplicate_of`
       field - never `review_flag`/`lane` - regardless of which rung fired.
    4. none of the above -> all three keys are set to None, so a consumer can
       tell that the pipeline looked and still could not build anything (Stage
       1 could not even read the file's size, or ran with no source path at
       all - see `s1_intake.py`).

    Without rung 3, a document that extracts no invoice number, no account
    number, and no billing period - the exact case a hard-miss/collapsed
    persona produces - could never be flagged as a possible duplicate of
    itself even when it is, byte-for-byte, the identical file reprocessed
    (a retried webhook, a re-uploaded attachment). `soft_fingerprint` was
    computed for exactly this at Stage 1 ("clusters likely duplicates, never
    rejects them") but, before this rung existed, was never actually read by
    anything.

    The account number is **normalized** before it goes into the key. One
    corpus vendor prints its account number as `1234 56 789 0123456` and its
    gold identity is `1234567890123456`; a key built from the printed form
    would not join against the same account written without spaces, which is
    the whole failure F6 describes.
    """
    invoice_number = ctx.extracted.get("invoice_number")
    if invoice_number is not None and str(invoice_number).strip():
        ctx.derived.set("document_identity", str(invoice_number).strip())
        ctx.derived.set("identity_basis", "invoice_number")
        return ctx

    account = (
        ctx.extracted.get("account_number")
        or ctx.extracted.get("vendor_account_number")
    )
    period = ctx.extracted.get("bill_date") or ctx.extracted.get("invoice_date")
    if account is not None and period is not None:
        ctx.derived.set(
            "document_identity", f"{_normalize_account(account)}|{_iso(period)}"
        )
        ctx.derived.set("identity_basis", "account_period")
        return ctx

    soft_fingerprint = ctx.derived.get("soft_fingerprint")
    if soft_fingerprint:
        ctx.derived.set("document_identity", f"soft:{soft_fingerprint}")
        ctx.derived.set("identity_basis", "soft_fingerprint")
        ctx.log(
            "s6: document_identity fell back to Stage 1's soft_fingerprint - "
            "no invoice number or account/period was extracted"
        )
        return ctx

    ctx.derived.set("document_identity", None)
    ctx.derived.set("identity_basis", None)
    ctx.log(
        "s6: no document_identity could be built - neither an invoice number, "
        "an account number with a billing period, nor a soft_fingerprint was "
        "available"
    )
    return ctx


def _normalize_account(value: Any) -> str:
    """The joinable form of an account number (F6).

    `patterns.account_number` already produces both forms, so an
    `AccountNumber` is asked for its `normalized`; a bare string is normalized
    the same way rather than trusted as-is.
    """
    normalized = getattr(value, "normalized", None)
    if isinstance(normalized, str):
        return normalized
    return "".join(ch for ch in str(value) if ch.isalnum())


def _iso(value: Any) -> str:
    """The ISO form of a date field, or its raw text if it never parsed.

    An unparsed date still identifies a document - one corpus vendor prints its
    due date as a recurring ordinal-day phrase rather than a calendar date, and
    that phrase is stable across months even though it is not a calendar date -
    so it is better in the key than dropping the rung entirely.
    """
    iso = getattr(value, "iso", None)
    if isinstance(iso, str):
        return iso
    raw = getattr(value, "raw", None)
    if isinstance(raw, str):
        return raw
    return str(value)
