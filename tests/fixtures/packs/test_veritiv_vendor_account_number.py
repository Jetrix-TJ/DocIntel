"""Finding E regression: Veritiv's `vendor_account_number` selector must not be
keyed to a hardcoded leading zero.

The shipped pattern used to be `(0[0-9]{5})`, copied straight off the single
gold sample's account number (`068753`). A real second sample -
`docs/_AP Invoice 689-37525600    Veritiv Operating Company 3312.50000.pdf` -
prints account number `179502`, which has no leading zero, and a live
`docintel.cli process --json` run confirmed the field was dropped from the
output entirely (`missing_required` behavior for a `required: false` field:
it is just silently absent).

Nothing about the account number's shape requires a leading zero - the
account number is a plain 6-digit run sitting a short distance below/right of
the `Account No.` anchor's second occurrence in the header block (immediately
after the invoice date, on the `VERITIV OPERATING COMPANY` address line), so
`region: near-anchor` + `anchor: "Account No."` already narrows correctly
without the leading-zero literal doing any work.

There is no gold label for the `179502` sample, so this test is the synthetic
fixture that stands in for corpus coverage: it drives the REAL selector out of
the shipped persona through the REAL executor, against a minimal near-anchor
layout, and checks both the new account number and the original gold one in
the same test - so a "fix" that just added `179502` as a second alternative
next to `0[0-9]{5}` cannot pass this by accident the way it could pass a
corpus-only check.
"""

from __future__ import annotations

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs
from northstar import PACK as _NORTHSTAR_PACK

WIDTH = 612.0
HEIGHT = 792.0


def _veritiv_vendor_account_number_selector() -> dict:
    """The actual `vendor_account_number` selector out of the shipped persona.

    Read from the loaded pack rather than re-typed here - re-typing it would
    test a copy of the rule, not the rule itself, and could quietly drift from
    what ships.
    """
    for pack in load_packs() + [_NORTHSTAR_PACK]:
        if pack.name != "northstar":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint") == "northstar|veritiv":
                for selector in persona["field_selectors"]:
                    if selector.get("field") == "vendor_account_number":
                        return selector
    raise AssertionError("northstar|veritiv persona (or its vendor_account_number selector) not found")


def _header_page(account_number: str) -> PageText:
    """A minimal `Account No.` anchor with the account number sitting just
    below/right of it, and an unrelated date-shaped run nearby, the way the
    real header block does (invoice date immediately precedes the account
    number on the address line) - so the test would notice a pattern loose
    enough to grab the date fragment instead."""
    words = [
        Word(text="Account", x0=10.0, y0=20.0, x1=55.0, y1=30.0),
        Word(text="No.", x0=58.0, y0=20.0, x1=78.0, y1=30.0),
        Word(text="08/14/2025", x0=10.0, y0=45.0, x1=70.0, y1=55.0),
        Word(text=account_number, x0=75.0, y0=45.0, x1=75.0 + 6.0 * len(account_number), y1=55.0),
    ]
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def _ctx(page: PageText) -> JobContext:
    meta = (
        PageMeta(
            page_number=1,
            char_count=sum(len(w.text) for w in page.words),
            image_count=0,
            annot_count=0,
            role="primary",
        ),
    )
    return JobContext(
        document_id="d1", source_path="x.pdf", pages=(page,), page_meta=meta,
        doc_type="standard_invoice",
    )


def _extract_vendor_account_number(account_number: str) -> str | None:
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_veritiv_vendor_account_number_selector()],
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(_header_page(account_number)))
    return ctx.extracted.get("vendor_account_number")


def test_matches_an_account_number_with_no_leading_zero() -> None:
    """The bug: the real second sample prints `179502` and the old
    `0[0-9]{5}`-only pattern dropped the field on it entirely."""
    assert _extract_vendor_account_number("179502") == "179502"


def test_still_matches_the_original_leading_zero_account_number() -> None:
    """No regression on the one gold document (`068753`) that already passed
    this field."""
    assert _extract_vendor_account_number("068753") == "068753"


def test_does_not_bleed_into_the_neighbouring_invoice_date() -> None:
    """`08/14/2025` sits immediately before the account number on the same
    header line - a pattern widened past a plain 6-digit run (e.g. one that
    also swallowed slashes or extra digits) would be the first place that
    showed up."""
    assert _extract_vendor_account_number("179502") != "08/14/2025"


def test_does_not_match_a_five_digit_run() -> None:
    """The account number is 6 digits - a run one digit short must not be
    padded or accepted, since that would mean the class lost a digit count
    rather than just the leading-zero literal."""
    assert _extract_vendor_account_number("17950") is None
