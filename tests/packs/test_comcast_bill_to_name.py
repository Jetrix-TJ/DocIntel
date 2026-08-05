"""Comcast is one of the 5 personas with no bill_to_name selector. Unlike
Edco/Veritiv, its own letterhead is graphical (no extracted words compete for
the top-left box), so a region-only match cleanly isolates the customer name
- confirmed by reading the real sample's page-1 word coordinates: nothing
else populates x<204,y<264 before the customer name's own row."""

from __future__ import annotations

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs

WIDTH = 612.0
HEIGHT = 792.0


def _comcast_bill_to_name_selector() -> dict:
    for pack in load_packs():
        if pack.name != "digitaldirection":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint", "").endswith("|comcast"):
                for selector in persona["field_selectors"]:
                    if selector.get("field") == "bill_to_name":
                        return selector
    raise AssertionError("comcast persona (or its bill_to_name selector) not found")


def _comcast_page(customer: str) -> PageText:
    words = [
        Word(text="Bill", x0=318.1, y0=15.9, x1=330.0, y1=25.9),  # right column - must not bleed in
        *[
            Word(text=tok, x0=35.0 + i * 70.0, y0=84.0, x1=35.0 + i * 70.0 + 65.0, y1=94.0)
            for i, tok in enumerate(customer.split())
        ],
        Word(text="Account", x0=35.0, y0=111.6, x1=71.8, y1=121.6),
    ]
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


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
            "field_selectors": [_comcast_bill_to_name_selector()],
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(_comcast_page(customer)))
    return ctx.extracted.get("bill_to_name")


def test_reads_the_customer_name_from_the_top_left_box() -> None:
    assert _extract_bill_to_name("CLYDE ADMINISTRATION") == "CLYDE ADMINISTRATION"


def test_does_not_bleed_in_the_right_column() -> None:
    assert _extract_bill_to_name("CLYDE ADMINISTRATION") != "Bill"


def _real_comcast_page1() -> PageText:
    """Page-1 word coordinates read directly off the real gold sample
    (`docs/persona-regeneration/08-comcast/document.pdf`, pdfplumber
    `extract_words`/`.chars`), not the brief's evenly-spaced synthetic tokens.

    The real print truncates the customer name at `Servi` (no trailing
    `ces`/`ces LLC` on the line below it, confirmed against `.chars`) - gold's
    `bill_to_name` is literally `"Clyde Administration Servi"`. This fixture
    reproduces that truncation, the real ~3.2pt inter-word gaps (well inside
    `CELL_GAP`, so the row is one cell), and the real right-column header
    block (`Bill date ...`, `Services from ...`, `Your monthly account
    summary`, `Previous balance 212.87`, `Credit Card Payment ... -212.87
    cr`) that all sit at x0 >= 317 above row 84 - the actual competing
    content a region-only, no-anchor selector has to not bleed from, not just
    the brief's single synthetic `Bill` probe word.
    """
    words = [
        # Right-column header block, all above the customer-name row (y0=84.0)
        # and all well right of the top-left box's x1=204.0 boundary.
        Word(text="Bill", x0=318.1, y0=15.9, x1=328.9, y1=23.9),
        Word(text="date", x0=331.2, y0=15.9, x1=347.0, y1=23.9),
        Word(text="Dec", x0=349.2, y0=15.9, x1=363.5, y1=23.9),
        Word(text="09,", x0=365.7, y0=15.9, x1=376.8, y1=23.9),
        Word(text="2025", x0=379.0, y0=15.9, x1=396.8, y1=23.9),
        Word(text="Services", x0=318.1, y0=24.8, x1=348.6, y1=32.8),
        Word(text="from", x0=350.9, y0=24.8, x1=367.3, y1=32.8),
        Word(text="Your", x0=317.0, y0=46.4, x1=339.6, y1=56.4),
        Word(text="monthly", x0=342.4, y0=46.4, x1=380.7, y1=56.4),
        Word(text="account", x0=383.5, y0=46.4, x1=422.2, y1=56.4),
        Word(text="summary", x0=425.0, y0=46.4, x1=469.3, y1=56.4),
        Word(text="Previous", x0=317.0, y0=67.2, x1=351.9, y1=76.2),
        Word(text="balance", x0=354.4, y0=67.2, x1=386.0, y1=76.2),
        Word(text="212.87", x0=542.4, y0=67.2, x1=569.9, y1=76.2),
        Word(text="Credit", x0=317.0, y0=79.6, x1=341.5, y1=88.6),
        Word(text="Card", x0=344.0, y0=79.6, x1=363.7, y1=88.6),
        Word(text="Payment", x0=366.2, y0=79.6, x1=401.7, y1=88.6),
        Word(text="-212.87", x0=538.9, y0=79.6, x1=569.9, y1=88.6),
        Word(text="cr", x0=573.6, y0=79.7, x1=581.4, y1=88.7),
        # The customer name row itself - real coordinates, truncated print.
        Word(text="Clyde", x0=35.0, y0=84.0, x1=66.1, y1=95.5),
        Word(text="Administration", x0=69.3, y0=84.0, x1=149.6, y1=95.5),
        Word(text="Servi", x0=152.8, y0=84.0, x1=180.2, y1=95.5),
        # What follows, in both columns - must not be reached or bled in.
        Word(text="New", x0=317.0, y0=93.1, x1=336.2, y1=102.1),
        Word(text="charges", x0=338.7, y0=93.1, x1=373.4, y1=102.1),
        Word(text="Account", x0=35.0, y0=111.6, x1=69.2, y1=121.1),
        Word(text="number", x0=71.8, y0=111.6, x1=103.3, y1=121.1),
    ]
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def test_reads_the_real_documents_truncated_customer_name() -> None:
    """Regression test for the actual real-document failure mode: with the
    real header block's coordinates in the fixture (not just one synthetic
    `Bill` probe), a selector that widened `top-left`'s box or matched a
    later line/cell would instead surface header text ("Bill date Dec 09,
    2025", "Your monthly account summary", ...) or the `Account number` line
    below. Gold's `bill_to_name` for this document is the truncated
    `"Clyde Administration Servi"` (the PDF itself never prints `ces`)."""
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_comcast_bill_to_name_selector()],
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(_real_comcast_page1()))
    value = ctx.extracted.get("bill_to_name")
    assert value == "Clyde Administration Servi"
    assert "Bill date" not in (value or "")
    assert "Account" not in (value or "")
