"""Windstream is one of the 5 personas that shipped with no `bill_to_name`
selector, so the field came from `resolve_bill_to_alias`'s roster rung and
`bill_to_mismatch` could never fire on a Windstream bill.

It is also the persona that carries TWO structurally different templates with
completely disjoint label vocabularies (see `test_windstream_enterprise_template.py`
for the measured table), so this selector has to work on both through
`anchor_alts` - the mechanism that file established for exactly this.

Re-measured page-1 word coordinates for the four Windstream PDFs with usable
page-1 text (`pdfplumber.extract_words` / `normalize.load_document`):

  Kinetic, `docs/persona-regeneration/09-windstream/document.pdf` (gold, native)

    top=  97.66 x0= 326.88  For Repair/Technical Support:  1-833-241-0100
    top= 107.26 x0= 326.88  Website:                       kineticbusiness.com
    top= 127.14 x0= 327.60  CHOCTAW TRAVEL MART            <- the value
    top= 136.79 x0= 327.60  PO BOX 1550
    top= 146.44 x0= 327.60  DURANT OK 74702-1550

  Enterprise, `Windstream_216713099_08272025_BILL.pdf` (native)

    top= 110.25 x0=  47.00  Check here for change of address(note changes below)
    top= 128.13 x0= 335.00  Y   101   1   N   2            <- form-field markers
    top= 144.66 x0=  47.00  GOLUB TOPs HQ                  <- the value
    top= 156.70 x0=  47.00  501 DUANESBURG RD

Both templates print the customer name directly BELOW a fixed boilerplate line
in its own column, which is plain `near-anchor` - no new region primitive is
needed. What is NOT true is the plan's premise that an "above-anchor" mirror of
`near-anchor` would help: on Kinetic the only label below the name is
`Account Summary` 94pt down (and, in the payment stub, `Check here for address
changes noted on reverse side.` 69pt below the second printing of the name),
both far outside `NEAR_ANCHOR_BELOW`'s 40pt, with the address block in between.

Neither named pattern serves both templates, which is why the pattern is a
shape rather than `text`/`text_block` - all four combinations were run against
the real documents:

    region        pattern      Kinetic (gold)                    Enterprise
    ------------------------------------------------------------------------
    near-anchor   text         'CHOCTAW TRAVEL MART'             'Y'
    near-anchor   text_block   'CHOCTAW TRAVEL MART\\nPO BOX      'GOLUB TOPs HQ'
                               1550\\nDURANT OK 74702-1550'
    label-block   text         'CHOCTAW TRAVEL MART'             'Y'
    label-block   text_block   (address bled in, as above)       (address bled in)

`text` reads Enterprise's stray `Y` form marker; `text_block` bleeds Kinetic's
address into the name. The shipped pattern
`([A-Za-z][A-Za-z0-9&.'-][A-Za-z0-9 &.'/-]{3,44})` is a party-name SHAPE - two
name characters with no space between them, then three to forty-four more - the
same remediation the guardrail file records for the sixteen cleared literal
patterns ("a shape described the field"). It skips `Y` and `101` and reads both
real names.

The three OCR'd Windstream samples (021942648, 205577168, 2389882) return None:
OCR renders the Kinetic anchor as `Website' kineticbusiness.com` and the
Enterprise one with an inserted space, so neither phrase resolves. That is a
miss, not a wrong answer - the roster rung still runs behind it, exactly as
today.
"""

from __future__ import annotations

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs

WIDTH = 612.0
HEIGHT = 792.0


def _windstream_bill_to_name_selector() -> dict:
    for pack in load_packs():
        if pack.name != "digitaldirection":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint", "").endswith("|windstream"):
                for selector in persona["field_selectors"]:
                    if selector.get("field") == "bill_to_name":
                        return selector
    raise AssertionError("windstream persona (or its bill_to_name selector) not found")


def _row(text: str, y0: float, x0: float, pitch: float = 2.2) -> list[Word]:
    """One printed row, laid out left to right with a realistic ~2pt gap so the
    words stay inside one `_cells` cell."""
    out: list[Word] = []
    x = x0
    for tok in text.split():
        width = 5.6 * len(tok)
        out.append(Word(text=tok, x0=x, y0=y0, x1=x + width, y1=y0 + 9.0))
        x += width + pitch
    return out


def _kinetic_page1(customer: str) -> PageText:
    """Real Kinetic geometry: the fixed vendor-contact block, then the customer
    address block 19.9pt below it in the same column. The `1-833-241-0100` and
    `kineticbusiness.com` values sit at x0=470.88 on their own rows - inside
    `near-anchor`'s 300pt horizontal reach, which is why the anchor has to be
    the WHOLE `Website: kineticbusiness.com` line: anchoring on `Website:`
    alone leaves `kineticbusiness.com` as the region's first candidate."""
    words = [
        *_row("For Repair/Technical Support:", 97.66, 326.88),
        Word(text="1-833-241-0100", x0=470.88, y0=95.00, x1=527.80, y1=104.0),
        Word(text="Website:", x0=326.88, y0=107.26, x1=358.00, y1=115.3),
        Word(text="kineticbusiness.com", x0=470.88, y0=104.59, x1=542.46, y1=113.6),
        *_row(customer, 127.14, 327.60),
        *_row("PO BOX 1550", 136.79, 327.60),
        *_row("DURANT OK 74702-1550", 146.44, 327.60),
        *_row("Account Summary", 221.30, 327.96),
    ]
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT,
                    source="native")


def _enterprise_page1(customer: str) -> PageText:
    """Real Enterprise geometry, including the `Y 101 1 N 2` form-marker row
    between the anchor and the name. Only `Y` (x0=335.00) falls inside
    `near-anchor`'s x1 (47.00 + 300 = 347.00); the rest are past it. `Y` is
    what `pattern: "text"` returns, and what the shape pattern must skip."""
    words = [
        *_row("Check here for change of address(note changes below)", 110.25, 47.00,
              pitch=1.94),
        Word(text="Y", x0=335.00, y0=128.13, x1=342.20, y1=137.1),
        Word(text="101", x0=385.00, y0=128.13, x1=406.60, y1=137.1),
        Word(text="1", x0=435.00, y0=128.13, x1=442.20, y1=137.1),
        Word(text="N", x0=485.00, y0=128.13, x1=492.20, y1=137.1),
        Word(text="2", x0=535.00, y0=128.13, x1=542.20, y1=137.1),
        *_row(customer, 144.66, 47.00, pitch=2.5),
        *_row("501 DUANESBURG RD", 156.70, 47.00),
        *_row("SCHENECTADY, NY 123061058", 168.70, 47.00),
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


def _extract(page: PageText) -> str | None:
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_windstream_bill_to_name_selector()],
            "layout_fingerprint": {},
        }
    )
    return Executor(persona).apply(_ctx(page)).extracted.get("bill_to_name")


def test_reads_the_kinetic_customer_name() -> None:
    """Gold for `digitaldirection-windstream-041069076` is `Choctaw Travel
    Mart`, printed `CHOCTAW TRAVEL MART`."""
    assert _extract(_kinetic_page1("CHOCTAW TRAVEL MART")) == "CHOCTAW TRAVEL MART"


def test_reads_the_enterprise_customer_name_through_the_alt() -> None:
    """The Enterprise template shares no label vocabulary with Kinetic, so it
    only reads at all through `anchor_alts` - and only if the form-marker row
    between anchor and name is skipped."""
    assert _extract(_enterprise_page1("GOLUB TOPs HQ")) == "GOLUB TOPs HQ"


def test_does_not_return_the_enterprise_form_marker() -> None:
    """`pattern: "text"` returns `Y` here, measured on the real
    `Windstream_216713099_08272025_BILL.pdf`. That is the regression this
    pattern exists to prevent."""
    assert _extract(_enterprise_page1("GOLUB TOPs HQ")) != "Y"


def test_does_not_bleed_the_kinetic_address_into_the_name() -> None:
    """`pattern: "text_block"` returns the whole three-line block here, measured
    on the real gold PDF. The name field must stay the name."""
    value = _extract(_kinetic_page1("CHOCTAW TRAVEL MART")) or ""
    assert "PO BOX" not in value
    assert "DURANT" not in value


def test_does_not_return_the_vendors_own_website_line() -> None:
    """`kineticbusiness.com` sits at x0=470.88 on the anchor's own row, well
    inside `near-anchor`'s 300pt reach. It is excluded only because the anchor
    phrase covers the WHOLE line and `_apply_field` drops the anchor's words -
    shortening the anchor to `Website:` reintroduces it."""
    value = _extract(_kinetic_page1("CHOCTAW TRAVEL MART")) or ""
    assert "kineticbusiness" not in value


def test_reads_a_party_that_is_not_on_the_roster() -> None:
    """The point of the whole selector: `GOLUB TOPs HQ` is not on Digital
    Direction's roster, so reading it is what lets `bill_to_mismatch` fire.
    The roster rung it replaces could only ever agree with the roster."""
    assert _extract(_enterprise_page1("SOME OTHER COMPANY")) == "SOME OTHER COMPANY"
