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
from docintel.packs import signals

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
    r"balance from last statement|previous balance due|previous total)\b", re.I
)
_AGING = re.compile(r"\b(past due|amount past due|30 days\b.*\b60 days)\b", re.I)
# The aging column header, matched anywhere in the document rather than on a
# short line. Preserved verbatim from the pre-migration code. Note that `.` does
# not cross a newline without `re.S` and page text is newline-joined, so this
# cannot pair a "30 DAYS" on one page with a "60 DAYS" on another - it is a
# single-line match in practice, which is why it is nearly redundant with
# `_AGING`'s own third alternative.
_AGING_COLUMNS = re.compile(r"\b30 DAYS\b.*\b60 DAYS\b", re.I)
_MAX_PAST_DUE_LINE_WORDS = 8
_SCANLINE = re.compile(r"\b\d{18,}\b")


def doc_type_for(ctx: JobContext) -> tuple[str, str]:
    """(doc_type, signal_that_fired). Three types, and `telecom_bill` is default.

    Composed from `packs.signals` primitives so the ladder can be expressed as
    data; the patterns and the rung order remain this pack's policy.

    **Known defect on the first rung, deliberately preserved.** It uses
    `pattern_in_scope`, a bare search, while returning the signal name
    `credit_memo_title` - so a bill that merely MENTIONS a credit memo is
    classified as one, which on this pack loads the wrong persona. Northstar's
    identical rung was fixed with `title_near_top` on 2026-08-06 and this one
    never was. The fix is a parked task and is not applied here, because this
    migration's correctness proof is a byte-identical `replay-gold` and folding
    a behaviour change into it would destroy that proof.
    """
    if signals.pattern_in_scope(ctx, _CREDIT_MEMO, scope="primary"):
        return "credit_memo", "credit_memo_title"

    # Suspension language AND no current-charge block. Both halves are required:
    # a bill that merely warns about future disconnection is still a bill.
    if signals.pattern_in_scope(
        ctx, _DISCONNECT, scope="primary"
    ) and not signals.pattern_in_scope(ctx, _CURRENT_CHARGES, scope="primary"):
        return "disconnect_notice", "suspension_without_current_charges"

    return "telecom_bill", "default"


def tags_for(ctx: JobContext) -> list[str]:
    tags: list[str] = []

    if signals.pattern_in_scope(ctx, PRIOR_BALANCE_ANCHORS, scope="primary"):
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

    # `primary_only=False` preserves this check's existing all-pages scope.
    # It is a KNOWN defect, not a considered widening: page 3 of
    # `Windstream_041069076` - a supporting page - prints the 5-word prose
    # fragment "any past due Internet balance.", which no word cutoff can
    # reject, and it tags a bill whose gold says `prior_balance_cleared`.
    # Northstar's identical check is correctly primary-scoped and corroborated.
    # Narrowing this one is a parked behaviour change, kept out of a migration
    # whose proof is a byte-identical `replay-gold`.
    if signals.short_label_line(
        ctx, _AGING, _MAX_PAST_DUE_LINE_WORDS, primary_only=False
    ) or signals.pattern_in_scope(ctx, _AGING_COLUMNS, scope="all"):
        tags.append("past_due")

    if signals.distinct_printed_aliases_at_least(ctx, count=2, scope="primary"):
        tags.append("multi_brand_sender")

    if signals.pattern_in_scope(ctx, _SCANLINE, scope="all"):
        tags.append("has_scanline")

    if signals.pattern_in_scope(ctx, _PROMO_MARKERS, scope="page1"):
        tags.append("promo_content")

    return tags


_PROMO_MARKERS = re.compile(
    r"go kinetic business|gokineticbusiness\.com|scan the qr code|"
    r"mybusiness\.gokinetic\.com|google play or the app store",
    re.I,
)
"""A closed enumeration of the "Kinetic Business by Windstream" promotional
insert's own wording, cited to two real documents:

- `Windstream_021942648_09022025_BILL.pdf` (second-samples): page 1 is a
  genuine full-page "Go Kinetic Business" ad, OCR'd to one raster. Carries
  "Go Kinetic Business", "my.gokineticbusiness.com", "scan the QR code",
  "mybusiness.gokinetic.com", and "Google Play or the App Store".
- The gold corpus's own `promo_content` document, account `041069076`
  ("Half of page 1 is an advertisement" per its gold note): a different,
  milder instance of the same template that carries only the shared
  boilerplate footer - "Go to mybusiness.gokinetic.com or download our
  mobile app by visiting Google Play or the App Store" - not the QR/download
  preamble the other document has. Both real documents are covered only
  because the enumeration keys on the footer they share, not the fuller
  block that just one of them prints.

Grepped every second-sample page 1 (Windstream, Lumen, Comcast, Centracom)
plus the gold PDF: these phrases appear on exactly the two documents above
and nowhere else in the corpus.
"""



def retag_prior_balance(ctx: JobContext) -> JobContext:
    """Refine `prior_balance_present` to `prior_balance_cleared`, on printed money.

    The anchor text alone cannot tell them apart: Centracom prints both a prior
    balance and a payment, and its prior is still 20,123.80 outstanding.

    This used to read `derived.carried_balance`, back when the printed-fields-only
    narrowing had unregistered the derivation that produces it. `carried_balance`
    is produced again (Task 11), but this function still reads the two printed
    amounts directly rather than the derived value - both inputs, `prior_balance`
    and `payments_credits`, are ink on the page, so the distinction survives here
    without depending on Stage 6's derivation order.

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


def retag_missing_invoice_number(ctx: JobContext) -> JobContext:
    """Tag `no_invoice_number` when extraction found none (spec section 2).

    Three of this pack's four carriers print no invoice number at all - the
    document's identity falls back to account plus billing period - and that is
    a fact a downstream consumer needs, because it is the reason two months of
    the same account are not duplicates of each other.

    **Registered at `beforeConfidenceGate`, not computed in `tags_for`.** Stage 3
    runs before extraction, so a classification-time version of this could only
    ever report whether an anchor was PRINTED, which is a different claim. The
    same reasoning that puts `retag_prior_balance` at this socket puts this one
    here: the value that matters is the one the record ends up carrying, after
    Stage 6's value ops, not the one Stage 5 captured.

    An empty or whitespace-only value counts as missing. A selector that matched
    its anchor and captured nothing has not found an invoice number, and the
    record must not imply that it did.

    Unlike `retag_prior_balance` there is no pair to refine here and no
    conservative half to leave standing: the absence of a value IS the finding.
    """
    value = ctx.extracted.get("invoice_number")
    if value is None or not str(value).strip():
        ctx.add_tag("no_invoice_number")
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
