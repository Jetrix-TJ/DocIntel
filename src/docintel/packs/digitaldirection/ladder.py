"""Digital Direction's classification ladder and tags (pack spec section 2).

**This pack has no `statement_of_account` type at all, and that is the point.**

Centracom's page 1 is titled `Account Summary` and the word "statement" appears
twice (`Balance from last statement`). A statement signal placed above the default
would misclassify it and run the wrong persona's rules - which on that document
means a $20,123.80 error (F9). The rule the pack spec settles on:

> A document with a payable amount and service line items is a bill, whatever its
> header says.

If a statement type is ever needed it must require the **absence** of a
current-charges block, not the presence of the word.

`prior_balance_cleared` fires on three of the four documents. That is the F1
illusion made explicit as a tag: the pipeline records that it *checked* and found
the prior netted out, rather than never having looked.

The fourth is Centracom, and the tag pair is only worth having because it gets
that one right. Classification emits `prior_balance_present` on any anchor and
`retag_prior_balance` upgrades it to `cleared` only when the printed payment
exactly offsets the printed prior - never on the presence of a payment anchor,
which Centracom also prints while owing 20,123.80.
"""

from __future__ import annotations

import re
from decimal import Decimal

from docintel.core.models import JobContext
from docintel.packs.digitaldirection import aliases
from docintel.packs.registry import all_text, primary_text

_CREDIT_MEMO = re.compile(r"\b(credit memo|adjustment notice)\b", re.I)
_DISCONNECT = re.compile(
    r"\b(disconnect notice|service will be disconnected|suspension notice)\b", re.I
)
_CURRENT_CHARGES = re.compile(
    r"\b(current charges|new charges|subtotal current charges|current charges due)\b", re.I
)

# Any of the prior-balance anchors the pack spec's section 3 enumerates. Used for
# the tag AND for the section 6 override: a prior-balance ANCHOR present with no
# prior-balance VALUE extracted is a review case, because failing to find a prior
# balance is far more dangerous than finding a wrong one - the failure mode is a
# silent overpayment.
PRIOR_BALANCE_ANCHORS = re.compile(
    r"\b(previous balance|previous bill|previous statement balance|"
    r"balance from last statement|previous balance due)\b", re.I
)
_AGING = re.compile(r"\b(past due|amount past due|30 days\b.*\b60 days)\b", re.I)
_MAX_PAST_DUE_LINE_WORDS = 8
_SCANLINE = re.compile(r"\b\d{18,}\b")


def doc_type_for(ctx: JobContext) -> tuple[str, str]:
    """(doc_type, signal_that_fired). Three types, and `telecom_bill` is default."""
    text = primary_text(ctx)

    if _CREDIT_MEMO.search(text):
        return "credit_memo", "credit_memo_title"

    # Suspension language AND no current-charge block. Both halves are required:
    # a bill that merely warns about future disconnection is still a bill.
    if _DISCONNECT.search(text) and not _CURRENT_CHARGES.search(text):
        return "disconnect_notice", "suspension_without_current_charges"

    return "telecom_bill", "default"


def tags_for(ctx: JobContext) -> list[str]:
    text = primary_text(ctx)
    everything = all_text(ctx)
    tags: list[str] = []

    if PRIOR_BALANCE_ANCHORS.search(text):
        # Anchor text alone CANNOT tell cleared from present, and guessing on a
        # payment anchor gets Centracom exactly backwards: it prints
        # `Payments Received` and its prior is still 20,123.80 outstanding.
        #
        # So classification emits only the conservative half of the pair - a
        # prior balance is printed and, until something proves otherwise, still
        # owed. `refine_prior_balance_tags` (registered at
        # `beforeConfidenceGate`, hooks.py) upgrades it to
        # `prior_balance_cleared` once the printed amounts show the payment
        # netted it out. If that hook never runs, the surviving claim is the
        # safe one.
        tags.append("prior_balance_present")

    if _short_line_has(ctx, _AGING, _MAX_PAST_DUE_LINE_WORDS) or re.search(
        r"\b30 DAYS\b.*\b60 DAYS\b", everything, re.I
    ):
        tags.append("past_due")

    if aliases.count_printed_names(text) >= 2:
        tags.append("multi_brand_sender")

    if _SCANLINE.search(everything):
        tags.append("has_scanline")

    if _has_promo_block(ctx):
        tags.append("promo_content")

    return tags


def _short_line_has(ctx: JobContext, pattern: re.Pattern[str], max_words: int) -> bool:
    """Whether `pattern` appears on a SHORT line rather than buried in prose."""
    for page in ctx.pages:
        for line in page.lines():
            if len(line) > max_words:
                continue
            if pattern.search(" ".join(w.text for w in line)):
                return True
    return False


def _has_promo_block(ctx: JobContext) -> bool:
    """A large image or advertising block on page 1 (F9, Windstream).

    Read from `PageMeta.image_count`, which Stage 2 already records. Two or more
    images on page 1 is an advertising block rather than a logo - a carrier
    letterhead is one image.
    """
    for meta in ctx.page_meta:
        if meta.page_number == 1 and meta.image_count >= 2:
            return True
    return False


def retag_prior_balance(ctx: JobContext) -> JobContext:
    """Refine `prior_balance_present` to `prior_balance_cleared`, on printed money.

    The anchor text alone cannot tell them apart: Centracom prints both a prior
    balance and a payment, and its prior is still 20,123.80 outstanding.

    This used to read `derived.carried_balance`, which the printed-fields-only
    narrowing no longer produces. Both inputs it uses now are ink on the page -
    `prior_balance` and `payments_credits` - so the distinction survives inside
    the narrowed scope instead of being discarded with the derivation.

    The test is that the printed payment exactly offsets the printed prior:

    | doc | prior | payments | sum | tag |
    |---|---:|---:|---:|---|
    | Comcast | 212.87 | -212.87 | 0 | cleared |
    | Lumen | 249.84 | -249.84 | 0 | cleared |
    | Windstream | 1231.74 | -1231.74 | 0 | cleared |
    | Centracom | 20123.80 | -24120.20 | -3996.40 | **present** |

    Centracom is the case that matters and the reason the test is equality with
    zero rather than "a payment was printed". Its `prior_balance` is ALREADY net
    of the payment (44,244.00 printed as last statement, less 24,120.20 paid),
    so the payment does not offset it a second time and the sum is nowhere near
    zero. Every other carrier's prior is gross.

    Clearing has to be PROVEN. Anything else - either amount missing, an
    unparseable value, a non-zero remainder - leaves `prior_balance_present`
    standing, because "still owed" is the claim that is safe to be wrong about.
    """
    if "prior_balance_present" not in ctx.tags:
        # No prior-balance anchor fired, so there is no pair to refine and
        # nothing here may invent one.
        return ctx
    if not _prior_balance_is_cleared(ctx):
        return ctx
    ctx.tags.remove("prior_balance_present")
    ctx.add_tag("prior_balance_cleared")
    return ctx


def _prior_balance_is_cleared(ctx: JobContext) -> bool:
    """Whether the printed payment exactly offsets the printed prior balance."""
    prior = _as_decimal(ctx.extracted.get("prior_balance"))
    if prior is None:
        return False
    if prior == 0:
        return True
    payments = _as_decimal(ctx.extracted.get("payments_credits"))
    if payments is None:
        return False
    return prior + payments == 0


def _as_decimal(value: object) -> Decimal | None:
    """Money as `Decimal`, never `float`. `None` for anything that will not parse."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None


def classify(ctx: JobContext) -> JobContext:
    doc_type, signal = doc_type_for(ctx)
    ctx.doc_type = doc_type
    ctx.signal_that_fired = signal
    ctx.classification_confidence = 0.95 if signal != "default" else 0.85
    for tag in tags_for(ctx):
        ctx.add_tag(tag)
    return ctx
