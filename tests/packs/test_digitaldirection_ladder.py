"""The prior-balance tag pair, and why anchor text cannot decide it.

Written after a whole-branch review found the pipeline shipping
`prior_balance_cleared` on Centracom against $20,123.80 outstanding. The cause
was `tags_for` guessing `cleared` from a payment anchor while its refinement hook
was unregistered, and the reason nothing caught it is that Centracom's gold
`tags` assertion is a SUPERSET check which was already red on two other tags: a
wrong tag appearing among the extras is invisible to a superset.

So the tags are pinned here as an exact pair, in both halves - the conservative
default that classification emits, and the upgrade the printed amounts justify.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from docintel.core.models import PageMeta, PageText, Word, new_context
from docintel.packs.digitaldirection.ladder import retag_prior_balance, tags_for


def _page(text: str, number: int = 1) -> PageText:
    words: list[Word] = []
    for row, line in enumerate(text.split("|")):
        y = 100.0 + row * 14.0
        for i, tok in enumerate(line.split()):
            words.append(
                Word(text=tok, x0=10.0 + 40.0 * i, y0=y, x1=45.0 + 40.0 * i, y1=y + 10.0)
            )
    return PageText(
        page_number=number, words=tuple(words), width=612.0, height=792.0,
        source="native",
    )


def _ctx(text: str):
    ctx = new_context("d", "/x.pdf")
    ctx.pages = (_page(text),)
    ctx.page_meta = (PageMeta(1, 100, 0, 0, "primary"),)
    return ctx


def _prior_tags(tags: list[str]) -> list[str]:
    return [t for t in tags if t.startswith("prior_balance_")]


# --------------------------------------------------------------------------
# Classification emits the conservative half only
# --------------------------------------------------------------------------


CENTRACOM_LIKE = (
    "Account Summary|Balance from last statement 44,244.00|"
    "Payments Received -24,120.20|Previous Balance 20,123.80|"
    "Current Charges 13,752.60"
)


def test_a_prior_balance_anchor_alone_claims_present_not_cleared() -> None:
    assert _prior_tags(tags_for(_ctx("Previous Balance 100.00"))) == [
        "prior_balance_present"
    ]


def test_a_payment_anchor_does_not_make_classification_claim_cleared() -> None:
    """The exact shape of the C1 regression.

    Centracom prints `Payments Received` AND carries 20,123.80 forward. A
    classifier that reads `cleared` off the payment anchor states the opposite of
    the truth on the corpus document the whole pack exists to get right.
    """
    assert _prior_tags(tags_for(_ctx(CENTRACOM_LIKE))) == ["prior_balance_present"]


def test_no_prior_anchor_means_no_prior_tag_at_all() -> None:
    assert _prior_tags(tags_for(_ctx("Current Charges 13,752.60"))) == []


# --------------------------------------------------------------------------
# The refinement, on printed amounts
# --------------------------------------------------------------------------


# (name, prior_balance, payments_credits, expected tag). The first three are the
# corpus's cleared documents; Centracom is the one that must not join them, and
# its prior is already NET of the payment, which is what breaks any rule based on
# a payment merely existing.
CORPUS = [
    ("comcast", Decimal("212.87"), Decimal("-212.87"), "prior_balance_cleared"),
    ("lumen", Decimal("249.84"), Decimal("-249.84"), "prior_balance_cleared"),
    ("windstream", Decimal("1231.74"), Decimal("-1231.74"), "prior_balance_cleared"),
    ("centracom", Decimal("20123.80"), Decimal("-24120.20"), "prior_balance_present"),
]


@pytest.mark.parametrize(("name", "prior", "payments", "expected"), CORPUS)
def test_the_four_corpus_documents_retag_as_gold_labels_them(
    name: str, prior: Decimal, payments: Decimal, expected: str
) -> None:
    ctx = _ctx(CENTRACOM_LIKE)
    ctx.add_tag("prior_balance_present")
    ctx.extracted.set("prior_balance", prior, 1.0)
    ctx.extracted.set("payments_credits", payments, 1.0)
    assert _prior_tags(retag_prior_balance(ctx).tags) == [expected], name


def test_clearing_must_be_proven_so_a_missing_payment_stays_present() -> None:
    ctx = _ctx(CENTRACOM_LIKE)
    ctx.add_tag("prior_balance_present")
    ctx.extracted.set("prior_balance", Decimal("212.87"), 1.0)
    assert _prior_tags(retag_prior_balance(ctx).tags) == ["prior_balance_present"]


def test_a_missing_prior_balance_stays_present() -> None:
    ctx = _ctx(CENTRACOM_LIKE)
    ctx.add_tag("prior_balance_present")
    ctx.extracted.set("payments_credits", Decimal("-212.87"), 1.0)
    assert _prior_tags(retag_prior_balance(ctx).tags) == ["prior_balance_present"]


def test_a_zero_prior_balance_is_cleared_without_a_payment() -> None:
    ctx = _ctx(CENTRACOM_LIKE)
    ctx.add_tag("prior_balance_present")
    ctx.extracted.set("prior_balance", Decimal("0.00"), 1.0)
    assert _prior_tags(retag_prior_balance(ctx).tags) == ["prior_balance_cleared"]


def test_refinement_never_invents_a_tag_on_a_document_with_no_anchor() -> None:
    """`retag_prior_balance` refines a pair; it does not create one. A carrier
    that prints no prior-balance anchor makes no claim either way."""
    ctx = _ctx("Current Charges 13,752.60")
    ctx.extracted.set("prior_balance", Decimal("0.00"), 1.0)
    assert _prior_tags(retag_prior_balance(ctx).tags) == []


def test_the_refinement_is_actually_wired_into_the_pipeline() -> None:
    """The half the unit tests above cannot see.

    `retag_prior_balance` was correct code the whole time it was unregistered -
    every unit test of it would have passed while the pipeline shipped the
    unrefined guess. What broke was the WIRING, so the wiring is pinned too.

    `beforeConfidenceGate`, not `afterExtraction`: the amounts must be the ones
    Stage 6's value ops produced, not the ones Stage 5 captured.
    """
    from docintel.packs.registry import register_all
    from docintel.pipeline.hooks import HookRegistry

    registry = HookRegistry()
    register_all(registry)
    assert (
        "digitaldirection.refine_prior_balance_tags"
        in registry.registered("beforeConfidenceGate")
    ), (
        "nothing refines the prior-balance tag pair, so the anchor-text guess is "
        "the pipeline's final answer - see this module's docstring"
    )


def test_money_comparison_is_decimal_not_float() -> None:
    """0.1 + 0.2 != 0.3 in binary floating point. A prior of 0.30 offset by a
    payment of -0.10 and -0.20 must still net to exactly zero."""
    ctx = _ctx(CENTRACOM_LIKE)
    ctx.add_tag("prior_balance_present")
    ctx.extracted.set("prior_balance", Decimal("0.1") + Decimal("0.2"), 1.0)
    ctx.extracted.set("payments_credits", Decimal("-0.3"), 1.0)
    assert _prior_tags(retag_prior_balance(ctx).tags) == ["prior_balance_cleared"]
