"""Finding 1 regression: Veritiv's `invoice_number` selector must not be keyed to
one prefix.

The shipped pattern used to be `(715-[0-9]{8})`, copied straight off the single
gold sample (`715-33905296`). Three of four newer real Veritiv invoices print
`689-` instead (e.g. `689-37525600`, confirmed against the PDF's own header
text, not the filename), and `715-` was never anything but this vendor's
current numbering block - nothing in the printed layout ties the field to that
one literal.

There is no gold label for the `689-` samples (see the task brief), so this
test is the synthetic fixture that stands in for corpus coverage: it drives the
REAL selector out of the shipped persona through the REAL executor, against a
minimal header-block page, and checks both the new prefix and the original one
in the same test - so a "fix" that just swaps which single literal is
hardcoded (e.g. adding `689-` as a second alternative next to `715-`) cannot
pass this by accident the way it could pass a corpus-only check.
"""

from __future__ import annotations

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import QUALITY_ANCHORED, Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs
from northstar import PACK as _NORTHSTAR_PACK

WIDTH = 612.0
HEIGHT = 792.0


def _veritiv_invoice_number_selector() -> dict:
    """The actual `invoice_number` selector out of the shipped persona.

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
                    if selector.get("field") == "invoice_number":
                        return selector
    raise AssertionError("northstar|veritiv persona (or its invoice_number selector) not found")


def _header_page(invoice_no: str) -> PageText:
    """A minimal `Invoice No. <value>` line inside the top-quarter header-block.

    Also carries an `Account No.` cell on the same line, the way the real
    layout does, so the test would notice a pattern greedy enough to bleed
    into a neighbouring field.
    """
    words = [
        Word(text="Invoice", x0=10.0, y0=20.0, x1=55.0, y1=30.0),
        Word(text="No.", x0=58.0, y0=20.0, x1=78.0, y1=30.0),
        Word(text=invoice_no, x0=82.0, y0=20.0, x1=82.0 + 6.0 * len(invoice_no), y1=30.0),
        Word(text="Account", x0=250.0, y0=20.0, x1=295.0, y1=30.0),
        Word(text="No.", x0=298.0, y0=20.0, x1=318.0, y1=30.0),
        Word(text="179502", x0=322.0, y0=20.0, x1=358.0, y1=30.0),
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


def _extract_invoice_number(invoice_no: str) -> str | None:
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_veritiv_invoice_number_selector()],
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(_header_page(invoice_no)))
    return ctx.extracted.get("invoice_number")


def test_matches_a_689_prefixed_invoice_number() -> None:
    """The bug: 3 of 4 newer real Veritiv invoices print this prefix and the
    old `715-`-only pattern returned `missing_required` on every one."""
    assert _extract_invoice_number("689-37525600") == "689-37525600"


def test_still_matches_the_original_715_prefixed_invoice_number() -> None:
    """No regression on the one gold document (`715-33905296`) that already
    passed this field."""
    assert _extract_invoice_number("715-33905296") == "715-33905296"


def test_does_not_bleed_into_the_neighbouring_account_number() -> None:
    """`179502` (Account No.) has no dash, so a prefix-class pattern that
    widened past `[0-9]{3}-[0-9]{8}` (e.g. dropped the dash or the digit
    counts) would be the first place that showed up."""
    assert _extract_invoice_number("689-37525600") != "179502"


def _extract_with_quality(invoice_no: str) -> tuple[str | None, float | None]:
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_veritiv_invoice_number_selector()],
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(_header_page(invoice_no)))
    return ctx.extracted.get("invoice_number"), ctx.extracted.match_quality.get("invoice_number")


def test_invoice_number_is_anchored_not_region_only() -> None:
    """The bug this fixes: region-only match_quality (0.90) sits under Veritiv's
    own 0.92 invoice_number threshold, so this field alone forces every Veritiv
    document to `medium` even when the value is correct. An anchored match
    (1.0) clears it."""
    _, quality = _extract_with_quality("689-37525600")
    assert quality == QUALITY_ANCHORED
