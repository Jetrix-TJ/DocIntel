"""F9 regression: U-Pak's `please_pay` selector declared an `anchor` that its
`last-page` region silently ignored (region-only value pages return whole-page
spans and never consult `anchor`). The executor then took the first currency
figure on the last page - `Subtotal 8119.44` - instead of the real
`Please Pay AMOUNT ... $14740.85` row further down the same page. Confirmed
against the real 5-page source PDF: pages 1-4 print the same `Please Pay`
column header with a blank AMOUNT cell; only page 5 fills it in, and
`Subtotal` sits 81pt above that filled cell on page 5 itself.

This fixture models the two facts that matter: (1) an earlier page with the
same anchor and a blank value, and (2) the last page carrying both a
`Subtotal` figure ABOVE the totals band and the real `Please Pay` figure
INSIDE it.
"""

from __future__ import annotations

from decimal import Decimal

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs

WIDTH = 612.0
HEIGHT = 792.0


def _upak_please_pay_selector() -> dict:
    for pack in load_packs():
        if pack.name != "northstar":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint") == "northstar|upak":
                for selector in persona["field_selectors"]:
                    if selector.get("field") == "please_pay":
                        return selector
    raise AssertionError("northstar|upak persona (or its please_pay selector) not found")


def _blank_please_pay_page(number: int) -> PageText:
    words = [
        Word(text="Please", x0=528.0, y0=663.0, x1=550.0, y1=673.0),
        Word(text="Pay", x0=555.0, y0=663.0, x1=572.0, y1=673.0),
        Word(text="AMOUNT", x0=49.0, y0=675.0, x1=95.0, y1=685.0),
    ]
    return PageText(page_number=number, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def _filled_last_page(number: int) -> PageText:
    words = [
        Word(text="Subtotal", x0=462.0, y0=582.0, x1=505.0, y1=592.0),
        Word(text="8119.44", x0=541.0, y0=582.0, x1=580.0, y1=592.0),
        Word(text="Please", x0=528.0, y0=663.0, x1=550.0, y1=673.0),
        Word(text="Pay", x0=555.0, y0=663.0, x1=572.0, y1=673.0),
        Word(text="AMOUNT", x0=49.0, y0=675.0, x1=95.0, y1=685.0),
        Word(text="$14740.85", x0=532.0, y0=675.0, x1=580.0, y1=685.0),
    ]
    return PageText(page_number=number, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def _ctx(pages: tuple[PageText, ...]) -> JobContext:
    meta = tuple(
        PageMeta(
            page_number=p.page_number,
            char_count=sum(len(w.text) for w in p.words),
            image_count=0,
            annot_count=0,
            role="primary",
        )
        for p in pages
    )
    return JobContext(
        document_id="d1", source_path="x.pdf", pages=pages, page_meta=meta,
        doc_type="standard_invoice",
    )


def _extract_please_pay() -> Decimal | None:
    pages = (_blank_please_pay_page(1), _filled_last_page(2))
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_upak_please_pay_selector()],
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(pages))
    return ctx.extracted.get("please_pay")


def test_please_pay_reads_the_filled_last_page_amount_not_the_subtotal() -> None:
    assert _extract_please_pay() == Decimal("14740.85")
