"""EDCO was one of the 5 personas that shipped with no `bill_to_name` selector
(STATUS-SUMMARY.md §4.1); this file is the selector that closed its share of
that finding, and all five - `comcast`, `windstream`, `edco`, `upak`,
`veritiv` - carry one as of this branch, so the count is now zero.

Before it,
`derived.bill_to_name` came from `resolve_bill_to_alias`'s rung 2 (a name on
the pack roster HEADS a line on the page) and `bill_to_basis` read
`roster_page_text`. That rung can never disagree with the roster - it reads the
answer OFF the roster - so `bill_to_mismatch` could not fire on an EDCO bill no
matter who the bill was addressed to.

The premise the remediation plan recorded for this persona was "customer name
with no adjacent label, and EDCO's own letterhead sits in the same `top-left`
box, so a region-only match returns the vendor's name first". Both halves are
true, and re-measured here against 28 real EDCO PDFs. What the plan missed is
that the name is not alone on its row: EDCO prints the remittance stub as two
columns on ONE set of rows, customer left and payee right, so the payee name
is stable layout furniture sitting on the customer name's own line.

Real page-1 coordinates, `_AP Invoice 27267AUG25 ... 384.03000.pdf`
(`pdfplumber.extract_words`):

    top=  33.30 x0=  51.18  EDCO WASTE & RECYCLING SERVICE   <- letterhead
    top=  44.90 x0=  51.18  224 S LAS POSAS RD
    top=  56.90 x0=  51.18  SAN MARCOS, CA 92078 ...
    top= 157.20 x0=  63.10  25-1A 027267                     <- account no., varies
    top= 164.93 x0=  62.46  NORTHSTAR RECYCLING              <- the value
    top= 164.93 x0= 353.58  EDCO WASTE & RECYCLING SERVICE   <- SAME ROW
    top= 176.90 x0=  62.46  DR BRONNER'S           P.O. BOX 5488
    top= 188.90 x0=  62.46  PO BOX 188             BUENA PARK, CA 90622-5488
    top= 200.90 x0=  62.46  EAST LONGMEADOW MA 01028

So the selector is `same-row` off `EDCO WASTE & RECYCLING SERVICE` with
`anchor_occurrence: "mid_line"` - the occurrence at top=164.93 is the only one
that does not begin its line (top=33.30 is the letterhead and top=304.00 is
`EDCO WASTE & RECYCLING SERVICE FOR SERVICE AT:`, both line-heads). That is the
same anchor and the same occurrence rule `remit_address` already uses on this
persona, and it is not GUARDRAIL 9's anchor-is-value: the anchor is the VENDOR's
name and the value is the CUSTOMER's.

`_apply_field` drops the anchor's own words from the candidates, so the row
reduces to the customer's cell and `pattern: "text"` returns it.

Measured across all 28 real EDCO samples, this reads what is actually printed
rather than what the roster says - `SYSCO FOODS-SAN DIEGO` on 709223OCT25,
`NORTHSTAR RECYCLING CO` on 968397OCT25, and EDCO's own misprints
`NORTHSTRAY RECYCLING` (823282AUG25/SEP25) and `NORTHSTART RECYCLING`
(176024OCT25). Those four now raise `bill_to_mismatch`, which is the entire
point of moving the field off the roster rung.
"""

from __future__ import annotations

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs

WIDTH = 612.0
HEIGHT = 792.0

PAYEE = ["EDCO", "WASTE", "&", "RECYCLING", "SERVICE"]
PAYEE_X = [353.58, 385.25, 423.59, 433.04, 494.16]
PAYEE_X1 = [382.47, 420.81, 430.26, 491.38, 538.06]


def _edco_bill_to_name_selector() -> dict:
    for pack in load_packs():
        if pack.name != "northstar":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint") == "northstar|edco":
                for selector in persona["field_selectors"]:
                    if selector.get("field") == "bill_to_name":
                        return selector
    raise AssertionError("northstar|edco persona (or its bill_to_name selector) not found")


def _payee_words(y0: float, x0: float = 353.58) -> list[Word]:
    shift = x0 - PAYEE_X[0]
    return [
        Word(text=t, x0=x + shift, y0=y0, x1=x1 + shift, y1=y0 + 8.0)
        for t, x, x1 in zip(PAYEE, PAYEE_X, PAYEE_X1, strict=True)
    ]


def _real_edco_page1(customer: str) -> PageText:
    """The real stub geometry: letterhead at the top (a `top-left` competitor),
    the varying account number directly above the customer name (no use as an
    anchor), the customer name beside the payee name on one row, and the
    line-head `... FOR SERVICE AT:` occurrence further down that `mid_line`
    must not pick."""
    words = [
        # Letterhead - the reason a region-only `top-left` read returns EDCO.
        *_payee_words(33.30, x0=51.18),
        Word(text="224", x0=51.18, y0=44.90, x1=68.0, y1=52.9),
        Word(text="S", x0=70.5, y0=44.90, x1=76.0, y1=52.9),
        Word(text="LAS", x0=78.5, y0=44.90, x1=96.0, y1=52.9),
        Word(text="POSAS", x0=98.5, y0=44.90, x1=133.0, y1=52.9),
        Word(text="RD", x0=135.5, y0=44.90, x1=153.45, y1=52.9),
        # The account number above the name: varies per document, so it is not
        # an anchor a persona could name.
        Word(text="25-1A", x0=63.10, y0=157.20, x1=79.11, y1=165.2),
        Word(text="027267", x0=80.78, y0=157.20, x1=100.79, y1=165.2),
        # The customer name, beside the payee name on ONE row.
        *[
            Word(text=tok, x0=62.46 + i * 65.0, y0=164.93, x1=62.46 + i * 65.0 + 62.0,
                 y1=172.93)
            for i, tok in enumerate(customer.split())
        ],
        *_payee_words(164.93),
        # The bill-to address block under the name, and the payee's beside it.
        Word(text="PO", x0=62.46, y0=188.90, x1=74.0, y1=196.9),
        Word(text="BOX", x0=76.5, y0=188.90, x1=93.4, y1=196.9),
        Word(text="188", x0=95.9, y0=188.90, x1=113.7, y1=196.9),
        Word(text="P.O.", x0=353.58, y0=176.90, x1=372.0, y1=184.9),
        Word(text="BOX", x0=374.5, y0=176.90, x1=391.4, y1=184.9),
        Word(text="5488", x0=393.9, y0=176.90, x1=422.51, y1=184.9),
        # `... FOR SERVICE AT:` - a THIRD occurrence of the anchor phrase, and a
        # line-head one, so `mid_line` must skip it.
        *_payee_words(304.00, x0=43.98),
        Word(text="FOR", x0=380.0, y0=304.00, x1=398.0, y1=312.0),
        Word(text="SERVICE", x0=400.5, y0=304.00, x1=440.0, y1=312.0),
        Word(text="AT:", x0=442.5, y0=304.00, x1=458.48, y1=312.0),
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
            "field_selectors": [_edco_bill_to_name_selector()],
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(_real_edco_page1(customer)))
    return ctx.extracted.get("bill_to_name")


def test_reads_the_printed_bill_to_name() -> None:
    assert _extract_bill_to_name("NORTHSTAR RECYCLING") == "NORTHSTAR RECYCLING"


def test_reads_a_party_that_is_not_on_the_roster() -> None:
    """The whole point of moving off the roster rung: 709223OCT25 really is
    billed to `SYSCO FOODS-SAN DIEGO`, and the roster rung would have reported
    `Northstar Recycling` for it. `bill_to_mismatch` can only fire if the
    selector reads what is printed."""
    assert _extract_bill_to_name("SYSCO FOODS-SAN DIEGO") == "SYSCO FOODS-SAN DIEGO"


def test_does_not_return_the_payee_name_sharing_the_row() -> None:
    """`same-row` is a full-page-width band, so the payee name is inside the
    span. It is excluded only because `_apply_field` puts the anchor's words in
    `skip` - which is also why the anchor has to be the payee and not, say, a
    label above the name.

    The equality assertion is deliberate: `"EDCO" not in None` is vacuously
    true, so a bare negative check here would pass against an empty record and
    report coverage it does not have."""
    value = _extract_bill_to_name("NORTHSTAR RECYCLING")
    assert value == "NORTHSTAR RECYCLING"
    assert "EDCO" not in value


def test_does_not_return_the_letterhead() -> None:
    """The measured failure of the region-only alternative: `top-left` (and
    every other top region) returns EDCO's own letterhead at top=33.30 first.

    Equality first, for the same reason as above: a lone `!=` passes on a miss."""
    value = _extract_bill_to_name("NORTHSTAR RECYCLING")
    assert value == "NORTHSTAR RECYCLING"
    assert value != "EDCO WASTE & RECYCLING SERVICE"


def test_mid_line_skips_both_line_head_occurrences() -> None:
    """The anchor phrase occurs three times on a real EDCO page. Only the
    middle one shares a row with the customer name; the other two begin their
    lines, so neither `"first"` nor `"last"` can reach it. If the selector
    ever loses `anchor_occurrence: "mid_line"`, `"first"` resolves to the
    letterhead row (which has no customer name on it) and this returns None."""
    assert _edco_bill_to_name_selector().get("anchor_occurrence") == "mid_line"
    assert _extract_bill_to_name("NORTHSTAR RECYCLING") == "NORTHSTAR RECYCLING"
