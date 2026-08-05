"""Federal Recycling: `bill_to_address` truncates mid-string (gold
`"PO Box 188, East Longmeadow, MA 01028, UNITED STATES"`, real extraction
`"PO Box 188, East Longmeadow, MA 01"` before this fix). `vendor_address` and
`remit_address` are investigated below too (per the task brief) and found to
be genuinely unreachable with today's closed region/pattern/adjust
vocabulary - see the module docstring's "NOT FIXED" section for the evidence
this file also encodes as executable proof, and the task report for the
full writeup. Only `bill_to_address` ships a selector change here.

**Zero second-period sample.** `docs/corpus/gold/northstar-federal-recycling-
1330123.json` is EXCLUDED from draft-to-stable promotion evidence (`"excluded_
from_promotion": true`) and is the only Federal Recycling document in the
corpus - this fix is verified against that single gold document only, and
should be re-checked once a second sample exists.

**Real-document investigation** (`docs/CONTRA ONLY Everything already on AR
Federal Recycling 1330123.pdf`, OCR'd - zero text layer - via
`docintel.extract.ocr.ocr_pages`, page 1, `line_tolerance=3.0`):

There are TWO bill-to blocks on the page, a `FOR` column (left, x0=39.2) and a
`SHIP TO` column (right, x0=339.1), printed side by side. `bill_to_name`'s
existing selector (unrelated to this fix) anchors `SHIP TO` and correctly
reads `"Northstar-Bimbo-Market Street"`. But the SHIP TO column's OWN zip line
is OCR-garbled - `East Longmeadow, MA 01` (bottom=222.1) - the `028` is
genuinely missing from the OCR output, not a selector/region bug; confirmed by
reading `service_location` (already anchored on SHIP TO, unrelated to this
fix), which independently reproduces the same `MA 01` truncation. No selector
tuning on the SHIP TO column can produce the correct zip because the digits
are not there to read.

The FOR column (left) reads the zip correctly - `East Longmeadow, MA 01028` -
and also prints `UNITED STATES` on its own line below (`Y0=219.6`), gold's
last address token. This fix's selector anchors THAT column instead:

    FOR                                       x0=39.2  y0=170.6
    NorthstarBimbo=Market Street              x0=39.2  y0=185.4  (company name,
                                                                    OCR misread
                                                                    of the
                                                                    hyphens)
    PO Box 188                                x0=39.2  y0=196.9
    East Longmeadow, MA 01028                 x0=39.2  y0=208.1
    UNITED STATES                             x0=39.2  y0=219.6
    apayable@nsrecycle.com                    x0=38.9  y0=230.8  (bill_to_email
                                                                    - must NOT
                                                                    bleed in)

Anchoring on the two-word company-name line (`"NorthstarBimbo=Market
Street"`) means `label-block`/`near-anchor`'s skip mechanism drops the WHOLE
line (both matched words), so the block starts clean at `PO Box 188`.
`region: "near-anchor"` (NOT `label-block`) is required: `near-anchor`'s
fixed 40pt-below reach lands at y=225.4 (anchor y0 185.4 + 40), which
includes `UNITED STATES` (offset 34.2pt) but excludes the email line (offset
45.4pt, 5.4pt past the boundary). `label-block`'s gap-based stop does NOT
trigger here - the real line pitch is ~11.3pt throughout, including the gap
before the email line, so nothing tells `label-block` to stop before it and
it bleeds the email in (confirmed empirically before writing this fix).

**NOT FIXED, and why (read the real PDF confirmed both, no code changed for
either):**

`vendor_address` (gold `"7935 Clayton Rd, St. Louis, MO 63117"`): the address
block sits at x0=38.9, with NOTHING else on the page within the region
vocabulary's 12pt left-tolerance above or beside it (the letterhead sits at
x0=111.2+, 72pt away) - there is no anchor phrase available that is not part
of the address's own text. The only selector that would reach it is one
anchored on the address's own first line (`"7935 Clayton Rd"`), which
GUARDRAIL 9 (`tests/packs/test_no_hardcoded_values.py`) names verbatim as ITS
OWN canonical forbidden example (`{"field": "vendor_address", "anchor": "7935
Clayton Rd"}`) - and this persona's own notes record that exact selector was
already tried and removed for both that reason AND a functional one: the
block ran on into the phone number line (`St. Louis, MO 63117, 281-580-1242`
against gold's `7935 Clayton Rd, St. Louis, MO 63117`).

`remit_address` (gold `"Post Office Box 203505, Dallas, TX 75320-3505"`):
reachable content-wise (the payee name `"Federal International Recycling and
Waste Solutions, LLC"` sits directly above it, a legitimate non-value
anchor), but no region stops in the right place. `near-anchor` from that
payee-name anchor reaches 40pt below (to y=646.6) and bleeds in `TERMS &
CONDITIONS` (y0=642.2, only 4.6pt inside the boundary - the real gap before it
is 16.5pt, under both `near-anchor`'s fixed floor and `label-block`'s 24pt
gap-stop threshold, so neither region naturally stops there). Anchoring
earlier, on the genuine `"CHECK REMITTANCE"` label instead, moves the window
early enough to exclude `TERMS & CONDITIONS` but then INCLUDES the payee name
line instead (no skip applies to it - skip only drops the anchor's own
matched words) - trading one contamination for another. No anchor position
excludes both simultaneously with a single fixed-reach, downward-only region.
The closed grammar (`schema.FieldSelector` - anchor/anchor_alts/anchor_
occurrence/region/pattern/adjust/required, no line-count or stop-anchor
knob) has no way to bound a `text_block` capture to fewer lines than its
region's own reach. This is a Task 8 stretch-primitive candidate, not
something to improvise here.
"""

from __future__ import annotations

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs

WIDTH = 609.12
HEIGHT = 791.28


def _federal_recycling_bill_to_address_selector() -> dict:
    """The actual `bill_to_address` selector out of the shipped persona - read
    from the loaded pack, not re-typed."""
    for pack in load_packs():
        if pack.name != "northstar":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint") == "northstar|federal_recycling":
                for selector in persona["field_selectors"]:
                    if selector.get("field") == "bill_to_address":
                        return selector
    raise AssertionError(
        "northstar|federal_recycling persona (or its bill_to_address selector) not found"
    )


def _real_federal_recycling_page1() -> PageText:
    """Page-1 word coordinates read directly off the real gold sample via
    OCR (`docintel.extract.ocr.ocr_pages`), reproducing both bill-to columns
    (FOR/left and SHIP TO/right) and the trailing email line - not just the
    target block - so a selector that bled into either is caught."""
    words = [
        # Left column: "FOR" block (the one this fix anchors on).
        Word(text="FOR", x0=39.2, y0=170.6, x1=59.0, y1=177.8),
        Word(text="NorthstarBimbo=Market", x0=39.2, y0=185.4, x1=142.6, y1=192.6),
        Word(text="Street", x0=145.8, y0=185.4, x1=171.0, y1=192.6),
        Word(text="PO", x0=39.2, y0=196.9, x1=52.2, y1=204.1),
        Word(text="Box", x0=56.2, y0=196.9, x1=72.0, y1=204.1),
        Word(text="188", x0=76.0, y0=196.9, x1=90.7, y1=204.1),
        Word(text="East", x0=39.2, y0=208.1, x1=58.0, y1=215.3),
        Word(text="Longmeadow,", x0=61.6, y0=208.1, x1=121.0, y1=217.1),
        Word(text="MA", x0=125.3, y0=208.1, x1=139.3, y1=215.3),
        Word(text="01028", x0=145.1, y0=208.1, x1=171.4, y1=215.3),
        Word(text="UNITED", x0=39.2, y0=219.6, x1=74.5, y1=226.8),
        Word(text="STATES", x0=78.1, y0=219.6, x1=114.8, y1=226.8),
        Word(text="apayable@nsrecycle.com", x0=38.9, y0=230.8, x1=149.8, y1=240.1),
        # Right column: "SHIP TO" block - its zip is OCR-truncated ("01", no
        # "028") and must NOT be what this selector reaches.
        Word(text="SHIP", x0=338.8, y0=180.7, x1=360.7, y1=187.9),
        Word(text="TO", x0=364.0, y0=180.7, x1=376.9, y1=187.9),
        Word(text="Northstar-Bimbo-Market", x0=339.1, y0=192.2, x1=442.1, y1=199.4),
        Word(text="Street", x0=445.3, y0=192.2, x1=470.9, y1=199.4),
        Word(text="PO", x0=339.1, y0=203.8, x1=352.1, y1=211.0),
        Word(text="Box", x0=355.7, y0=203.8, x1=371.9, y1=211.0),
        Word(text="188", x0=375.5, y0=203.8, x1=390.2, y1=211.0),
        Word(text="East", x0=339.1, y0=214.9, x1=357.8, y1=222.1),
        Word(text="Longmeadow,", x0=361.1, y0=214.9, x1=420.8, y1=223.9),
        Word(text="MA", x0=425.2, y0=214.9, x1=438.8, y1=222.1),
        Word(text="01", x0=444.6, y0=214.9, x1=453.6, y1=222.1),
        Word(text="UNITED", x0=339.1, y0=226.1, x1=374.0, y1=233.3),
        Word(text="STATES", x0=377.6, y0=226.1, x1=414.7, y1=233.3),
    ]
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT, source="ocr")


def _ctx(page: PageText) -> JobContext:
    meta = (
        PageMeta(page_number=1, char_count=sum(len(w.text) for w in page.words),
                 image_count=0, annot_count=0, role="primary"),
    )
    return JobContext(document_id="d1", source_path="x.pdf", pages=(page,), page_meta=meta,
                       doc_type="contra_invoice", text_source="ocr")


def _extract_bill_to_address() -> str | None:
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "contra_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_federal_recycling_bill_to_address_selector()],
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(_real_federal_recycling_page1()))
    return ctx.extracted.get("bill_to_address")


def test_reads_the_full_untruncated_address_from_the_for_column() -> None:
    value = _extract_bill_to_address()
    assert value is not None
    lines = value.splitlines()
    assert lines == ["PO Box 188", "East Longmeadow, MA 01028", "UNITED STATES"]


def test_does_not_bleed_in_the_company_name_or_email() -> None:
    value = _extract_bill_to_address() or ""
    assert "NorthstarBimbo" not in value
    assert "apayable" not in value


def test_does_not_bleed_in_the_ship_to_columns_truncated_zip() -> None:
    """The bug this fix targets: the SHIP TO column's zip is missing `028`.
    A selector that (by accident) reached across into the right column
    instead of staying in the FOR column would reproduce that truncation."""
    value = _extract_bill_to_address() or ""
    assert "01028" in value
    assert value.count("01") == 1  # not also the SHIP TO column's bare "01"
