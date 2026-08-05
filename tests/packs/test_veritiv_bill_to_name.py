"""Veritiv is one of the 5 personas that shipped with no `bill_to_name`
selector, so the field came from `resolve_bill_to_alias`'s roster rung and
`bill_to_mismatch` could never fire on a Veritiv invoice.

The remediation plan recorded "customer name with no label, and Veritiv's own
header sits in the same box". Re-measured against all 7 real Veritiv PDFs, both
halves hold - and the same thing the plan missed on EDCO is true here: the
remittance stub is two columns on ONE set of rows, so the payee name is stable
layout furniture on the customer name's own line.

Real page-1 coordinates, `_AP Invoice 715-33905296 ... 4908.00000.pdf`
(`pdfplumber.extract_words`):

    top=  92.70 x0=  63.00  VERITIV OPERATING COMPANY   <- letterhead (line-head)
    top= 101.70 x0=  63.00  6120 South Gilmore Road ...
    top= 110.70 x0=  63.00  Fairfield, OH 45014
    top= 151.24 x0=  63.00  NORTHSTAR RECYCLING COMPANY LLC   <- the value
    top= 151.24 x0= 342.00  VERITIV OPERATING COMPANY         <- SAME ROW
    top= 160.20 x0=  63.00  94 MAPLE ST            P.O. BOX 409884
    top= 169.20 x0=  63.00  EAST LONGMEADOW,MA ... ATLANTA, GA. 30384-9884

Why nothing else reaches it, measured rather than assumed:

  * `top-left` / `header-block`: Veritiv's own letterhead at top=92.70 is the
    first line in every one of them.
  * `near-anchor` off `Fairfield, OH 45014` (the nearest same-column line
    above): the gap is 40.54pt and `NEAR_ANCHOR_BELOW` is 40.0pt - it misses by
    half a point, and it would be a city-name anchor anyway.
  * `label-block` off the letterhead: the 40.54pt gap is >2x the block's own
    9pt pitch, so the block ends at `Fairfield, OH 45014` (which is exactly
    what makes it the right region for `vendor_address`, as shipped).
  * an "above-anchor" mirror of `near-anchor`: there is no label BELOW the name
    either - only its own address block, then `Detach and return this portion
    with remittance.` at top=197.00 in a different column (x0=403.51).

So the selector is `same-row` off `VERITIV OPERATING COMPANY` with
`anchor_occurrence: "mid_line"`. The phrase occurs exactly twice on page 1 -
top=92.70 begins its line, top=151.24 does not - so `mid_line` is the precise
selector for the stub row. That is not GUARDRAIL 9's anchor-is-value: the
anchor is the VENDOR's name and the value is the CUSTOMER's, and `remit_address`
already anchors on the same phrase.
"""

from __future__ import annotations

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs

WIDTH = 612.0
HEIGHT = 792.0

PAYEE = ["VERITIV", "OPERATING", "COMPANY"]
PAYEE_X = [342.00, 375.99, 422.43]
PAYEE_X1 = [373.99, 420.43, 461.70]


def _veritiv_bill_to_name_selector() -> dict:
    for pack in load_packs():
        if pack.name != "northstar":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint") == "northstar|veritiv":
                for selector in persona["field_selectors"]:
                    if selector.get("field") == "bill_to_name":
                        return selector
    raise AssertionError("northstar|veritiv persona (or its bill_to_name selector) not found")


def _payee_words(y0: float, x0: float = 342.00) -> list[Word]:
    shift = x0 - PAYEE_X[0]
    return [
        Word(text=t, x0=x + shift, y0=y0, x1=x1 + shift, y1=y0 + 8.0)
        for t, x, x1 in zip(PAYEE, PAYEE_X, PAYEE_X1, strict=True)
    ]


def _real_veritiv_page1(customer: str) -> PageText:
    """Real page-1 geometry: the letterhead block (`top-left`'s first line and
    `label-block`'s anchor for `vendor_address`), the 40.54pt gap that puts the
    customer name half a point outside `near-anchor`'s reach from
    `Fairfield, OH 45014`, and the two-column stub row itself."""
    words = [
        # Letterhead: line-head occurrence #1 of the anchor phrase.
        *_payee_words(92.70, x0=63.00),
        Word(text="6120", x0=63.00, y0=101.70, x1=85.0, y1=109.7),
        Word(text="South", x0=87.0, y0=101.70, x1=113.0, y1=109.7),
        Word(text="Gilmore", x0=115.0, y0=101.70, x1=150.0, y1=109.7),
        Word(text="Road", x0=152.0, y0=101.70, x1=175.0, y1=109.7),
        Word(text="Fairfield,", x0=63.00, y0=110.70, x1=98.0, y1=118.7),
        Word(text="OH", x0=100.0, y0=110.70, x1=113.0, y1=118.7),
        Word(text="45014", x0=115.0, y0=110.70, x1=127.54, y1=118.7),
        # The stub row: customer left, payee right, one row. Real inter-word
        # gaps are ~2pt, so the customer's words stay one `_cells` cell.
        *[
            Word(text=tok, x0=63.00 + i * 51.0, y0=151.24, x1=63.00 + i * 51.0 + 49.0,
                 y1=159.24)
            for i, tok in enumerate(customer.split())
        ],
        *_payee_words(151.24),
        # The bill-to address under the name, payee's remit address beside it.
        Word(text="94", x0=63.00, y0=160.20, x1=74.0, y1=168.2),
        Word(text="MAPLE", x0=76.0, y0=160.20, x1=110.0, y1=168.2),
        Word(text="ST", x0=112.0, y0=160.20, x1=124.0, y1=168.2),
        Word(text="P.O.", x0=342.00, y0=160.20, x1=360.0, y1=168.2),
        Word(text="BOX", x0=362.0, y0=160.20, x1=379.0, y1=168.2),
        Word(text="409884", x0=381.0, y0=160.20, x1=418.0, y1=168.2),
    ]
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT,
                    source="native")


def _ctx(page: PageText) -> JobContext:
    meta = (
        PageMeta(page_number=1, char_count=sum(len(w.text) for w in page.words),
                 image_count=0, annot_count=0, role="primary"),
    )
    return JobContext(document_id="d1", source_path="x.pdf", pages=(page,), page_meta=meta,
                      doc_type="standard_invoice")


def _extract_bill_to_name(customer: str) -> str | None:
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_veritiv_bill_to_name_selector()],
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(_real_veritiv_page1(customer)))
    return ctx.extracted.get("bill_to_name")


def test_reads_the_printed_bill_to_name() -> None:
    """Gold for `northstar-veritiv-715-33905296` is the full printed rendering,
    `Northstar Recycling Company LLC` - `LLC` does not wrap to its own line the
    way it does on U-PAK, so nothing is truncated here."""
    assert _extract_bill_to_name("NORTHSTAR RECYCLING COMPANY LLC") == (
        "NORTHSTAR RECYCLING COMPANY LLC"
    )


def test_reads_a_party_that_is_not_on_the_roster() -> None:
    """Without this, `bill_to_mismatch` cannot fire: the roster rung reads the
    name off the roster and so always agrees with it."""
    assert _extract_bill_to_name("SOME OTHER COMPANY LLC") == "SOME OTHER COMPANY LLC"


def test_does_not_return_the_payee_name_sharing_the_row() -> None:
    value = _extract_bill_to_name("NORTHSTAR RECYCLING COMPANY LLC")
    assert "VERITIV" not in (value or "")


def test_does_not_return_the_letterhead() -> None:
    """What `top-left`, `header-block` and `first-page` all return instead."""
    assert _extract_bill_to_name("NORTHSTAR RECYCLING COMPANY LLC") != (
        "VERITIV OPERATING COMPANY"
    )


def test_mid_line_is_what_reaches_the_stub_row() -> None:
    """`"first"` resolves to the letterhead, whose row carries no customer
    name; only the non-line-head occurrence shares a row with the value."""
    assert _veritiv_bill_to_name_selector().get("anchor_occurrence") == "mid_line"
