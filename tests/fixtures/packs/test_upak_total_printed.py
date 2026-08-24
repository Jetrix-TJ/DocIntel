"""U-Pak's `total_printed` selector used `region: "totals-block"` with no
`anchor`. Without an anchor, `totals-block`'s resolver (`_totals_on`,
`regions.py:397-421`) falls back to `_label_y`, which by design returns the
TOP of the LAST line matching `_TOTALS_RE` on the page (deliberately, to
skip past a table-header occurrence of a totals word and land on the real
figure - see `_label_y`'s own docstring).

The real 5-page source PDF's last page carries two distinct totals-style
labels: `Total Invoice 14789.77` (the real total) and, further down the same
page, the `Please Pay` / `AMOUNT ... 14740.85` row. Both match `_TOTALS_RE`
(`TOTAL` and `PLEASE PAY` respectively). `_label_y` picks the *later* one -
`Please Pay` - so the totals band ends up centred on the Please Pay row
instead of the Total Invoice row, and `total_printed` silently reads
`14740.85` (the Please Pay figure) instead of `14789.77` (the real printed
total).

This was discovered as a side effect of fixing `please_pay` itself (see
`test_upak_please_pay.py`): before that fix, `please_pay` was also wrong
(`8119.44`), so `derive_amount_payable`'s printed-vs-please_pay disagreement
check still tripped - for the wrong reason - and happened to still produce
the gold-matching refusal. Once `please_pay` reads correctly, it exactly
matches `total_printed`'s buggy value, the two now spuriously "agree", and
the refusal stops firing. The fix is to anchor `total_printed` on `"Total
Invoice"` - confirmed as the exact, single, unambiguous occurrence on the
real PDF's last page - so `_totals_on` uses the anchor's own y-position
instead of falling back to `_label_y`.
"""

from __future__ import annotations

from decimal import Decimal

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs
from northstar import PACK as _NORTHSTAR_PACK

WIDTH = 612.0
HEIGHT = 792.0


def _upak_total_printed_selector() -> dict:
    for pack in load_packs() + [_NORTHSTAR_PACK]:
        if pack.name != "northstar":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint") == "northstar|upak":
                for selector in persona["field_selectors"]:
                    if selector.get("field") == "total_printed":
                        return selector
    raise AssertionError("northstar|upak persona (or its total_printed selector) not found")


def _unrelated_first_page(number: int) -> PageText:
    words = [
        Word(text="Invoice", x0=49.0, y0=40.0, x1=90.0, y1=50.0),
        Word(text="#", x0=95.0, y0=40.0, x1=100.0, y1=50.0),
        Word(text="4378107", x0=105.0, y0=40.0, x1=150.0, y1=50.0),
    ]
    return PageText(page_number=number, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def _last_page_with_two_totals_labels(number: int) -> PageText:
    """Models the real page 5: `Total Invoice` above, `Please Pay` below it."""
    words = [
        Word(text="Total", x0=446.11, y0=642.68, x1=463.88, y1=650.68),
        Word(text="Invoice", x0=466.09, y0=642.68, x1=491.43, y1=650.68),
        Word(text="14789.77", x0=536.65, y0=642.68, x1=570.00, y1=650.68),
        Word(text="Please", x0=528.0, y0=663.7, x1=550.0, y1=673.7),
        Word(text="Pay", x0=555.0, y0=663.7, x1=572.0, y1=673.7),
        Word(text="AMOUNT", x0=49.0, y0=675.7, x1=95.0, y1=685.7),
        Word(text="14740.85", x0=532.0, y0=675.7, x1=580.0, y1=685.7),
        Word(text="$14740.85", x0=532.0, y0=675.7, x1=580.0, y1=685.7),
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


def _extract_total_printed() -> Decimal | None:
    pages = (_unrelated_first_page(1), _last_page_with_two_totals_labels(2))
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_upak_total_printed_selector()],
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(pages))
    return ctx.extracted.get("total_printed")


def test_total_printed_reads_the_total_invoice_row_not_the_please_pay_row() -> None:
    assert _extract_total_printed() == Decimal("14789.77")
