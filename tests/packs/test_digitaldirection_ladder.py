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
from docintel.packs.digitaldirection.ladder import doc_type_for, retag_prior_balance, tags_for


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


def test_previous_total_phrase_tags_prior_balance_present() -> None:
    """Real Windstream Enterprise template bug: prints 'Previous Total' (not
    any of the five phrases already covered), with a genuine unresolved
    carryover. Missing this tag is a silent-overpayment risk (same class as
    F1) — the printed prior balance would never be checked."""
    ctx = _ctx("WINDSTREAM ENTERPRISE|Previous Total $2.99|New Charges $116.00")
    assert "prior_balance_present" in tags_for(ctx)


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


# --------------------------------------------------------------------------
# The ladder itself - two branches with no corpus document and, until now,
# no test at all: nothing would have noticed if either stopped firing.
# --------------------------------------------------------------------------


def test_a_credit_memo_title_wins_over_everything() -> None:
    ctx = _ctx("COMCAST BUSINESS|Credit Memo|Billing Account Number 8495|"
               "Current Charges 412.00")
    assert doc_type_for(ctx) == ("credit_memo", "credit_memo_title")


def test_suspension_language_without_current_charges_is_a_disconnect_notice() -> None:
    ctx = _ctx("COMCAST BUSINESS|DISCONNECT NOTICE|Billing Account Number 8495|"
               "Balance Due 1,204.00")
    assert doc_type_for(ctx) == ("disconnect_notice", "suspension_without_current_charges")


def test_a_bill_that_merely_warns_about_disconnection_is_still_a_bill() -> None:
    """Both halves of the signal are required. A bill carrying suspension
    language AND a current-charges block is a bill - misclassifying it would
    run the wrong persona's rules, which on Centracom costs $20,123.80.
    """
    ctx = _ctx("COMCAST BUSINESS|Service will be disconnected if unpaid|"
               "Current Charges 412.00|Billing Account Number 8495")
    assert doc_type_for(ctx) == ("telecom_bill", "default")


def test_an_account_summary_naming_statements_is_still_a_bill() -> None:
    """Centracom's real shape: page 1 titled `Account Summary`, the word
    "statement" printed twice. This pack has no `statement_of_account` type
    at all, and that is intentional (see the module docstring) - a statement
    signal ahead of the default would misclassify exactly this document and
    run the wrong persona's rules, a $20,123.80 error on the corpus.
    """
    ctx = _ctx("CENTRACOM|Account Summary|Balance from last statement 1,204.00|"
               "Current Charges 412.00|Billing Account Number 8495")
    assert doc_type_for(ctx) == ("telecom_bill", "default")


# --------------------------------------------------------------------------
# `_has_promo_block` - content, not image_count/char_count. Three real
# Windstream/Lumen documents proved neither signal can carry this alone:
# `021942648` and `205577168` are identical on both (image_count=1,
# char_count=0 - a raw scan has no native text layer regardless of content),
# and `216713099` false-fires on `image_count>=2` with 5 ordinary logo images
# and nothing promotional on the page.
# --------------------------------------------------------------------------


def test_full_page_ocr_ad_with_one_collapsed_image_still_tags_promo_content() -> None:
    """Real Windstream bug (`021942648`): a genuine full-page ad, OCR'd,
    collapses to `image_count=1, char_count=0` - identical, on both of the old
    signals, to a real scanned bill (see the third test below). Only the
    page's own marketing copy - "Go Kinetic Business", the QR/download
    preamble, and the "mybusiness.gokinetic.com ... Google Play or the App
    Store" footer - actually identifies it.
    """
    ctx = _ctx(
        "kinetic business by windstream|Account Summary|"
        "Do More with Go Kinetic Business|"
        "Now you can enjoy all the benefits of Go Kinetic Business|"
        "Visit my.gokineticbusiness.com or scan the QR code to download the mobile app|"
        "Go to mybusiness.gokinetic.com or download our mobile app by visiting Google Play or the App Store|"
        "Current Charges Due 09/25/25 279.52|Total Amount Due 279.52"
    )
    ctx.page_meta = (PageMeta(1, 0, 1, 0, "primary"),)
    assert "promo_content" in tags_for(ctx)


def test_the_shared_kinetic_footer_alone_tags_promo_content_gold_041069076() -> None:
    """The gold corpus's own `promo_content` document (`041069076`, "Half of
    page 1 is an advertisement" per its gold note) does not carry the QR-code
    preamble `021942648` has - only the shared "download the mobile app ...
    Google Play or the App Store" footer block. That alone must be enough:
    this document is the reason the tag exists, and it was silently missing
    it (26/29 on `replay-gold`) before this fix, because `image_count == 1`
    on this native, high-char_count page could never have satisfied any
    image_count/char_count threshold.
    """
    ctx = _ctx(
        "kinetic business by windstream|Account Summary|"
        "Current Charges Due 08/11/25 1230.14|Total Amount Due 1230.14|"
        "Go to mybusiness.gokinetic.com or download our mobile app by visiting Google Play or the App Store"
    )
    ctx.page_meta = (PageMeta(1, 2180, 1, 0, "primary"),)
    assert "promo_content" in tags_for(ctx)


def test_ordinary_page_with_several_small_logo_images_does_not_tag_promo_content() -> None:
    """Real Windstream bug (`216713099`): 5 incidental small header/logo
    images plus normal invoice content, no ad copy anywhere on the page -
    `image_count >= 2` alone used to false-fire on exactly this document.
    """
    ctx = _ctx(
        "WINDSTREAM ENTERPRISE|Account Summary Invoice 77176782|"
        "Previous Total 646.69|Payments Applied Thank You -646.69|"
        "Monthly Charges 575.00|New Charges Due by Sep 15 2025 647.01|"
        "Windstream Portal|Manage your Windstream services directly|"
        "Total Invoice Amount 647.01"
    )
    ctx.page_meta = (PageMeta(1, 2990, 5, 0, "primary"),)
    assert "promo_content" not in tags_for(ctx)


def test_a_scanned_single_image_ordinary_bill_does_not_tag_promo_content() -> None:
    """Real Windstream bug (`205577168`) and both real Lumen invoices: a
    genuine bill scanned as ONE full-page raster reads `image_count=1,
    char_count=0` - identical to the real ad on both of the old signals.
    Only the marketing copy tells them apart, and an ordinary bill page
    prints none of it.
    """
    ctx = _ctx(
        "WINDSTREAM ENTERPRISE|Account Summary Invoice 77170792|"
        "Previous Total 5.12|Payments Applied Thank You -2.13|"
        "Monthly Charges 0.00|Total Invoice Amount 4.82|"
        "Windstream Portal|Manage your Windstream services directly"
    )
    ctx.page_meta = (PageMeta(1, 0, 1, 0, "primary"),)
    assert "promo_content" not in tags_for(ctx)
