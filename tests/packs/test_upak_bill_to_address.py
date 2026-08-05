"""U-Pak has no `bill_to_address` selector at all (`grep -n "bill_to_address"
src/docintel/packs/northstar/personas/upak.json` before this fix returned
nothing) - this is an ADD, not a regression fix. Absent a selector, the value
comes entirely from `ops.infer.resolve_bill_to_alias`'s `_block_under`
fallback, which starts from wherever `bill_to_name` matched on the page. Task
6's `bill_to_name` selector (anchor `"Bill To"`, region `near-anchor`) itself
only reaches `"NORTHSTAR RECYCLING COMPANY"` - the printed name wraps `LLC`
onto its OWN line 8pt below (real geometry, `docs/persona-regeneration/
05-upak/document.pdf`, page 1), past `near-anchor`'s fixed vertical floor. The
fallback then walks the lines under that truncated match and picks up the
wrapped `LLC` line itself as the first line of "the address", producing
`"LLC, 94 MAPLE ST"` - the trailing-fragment bug this fixes, with city/state/
zip dropped entirely because the fallback's own block-height ceiling is
exhausted by the extra line.

**Real-document geometry** (pdfplumber `extract_words()` on page 1):

    Bill To:                              x0=90.0  top=135.7
    NORTHSTAR RECYCLING COMPANY           x0=90.0  top=169.2
    LLC                                   x0=90.0  top=177.2
    94 MAPLE ST                           x0=90.0  top=185.2
    EAST LONGMEADOW MA 01028              x0=90.0  top=193.2

A separate `Location:` column sits alongside, at x0=355.1, y0=135.7 -
`SHEARER'S FOOD CANADA INC N.S / 745 SOUTH GATE / MASTER ACC / GUELPH ON N1G
4N4` - close enough in y (rows offset by 4pt from the bill-to column's own
rows) that a wide enough region could bleed it in.

`LLC` is the ONLY occurrence of that word on page 1 (confirmed via a full-page
word dump), and it repeats verbatim on every one of the document's 5 pages (a
repeated per-page bill-to header), all at the identical x0=90.0/y0=177.2 -
`anchor_occurrence` defaults to `"first"`, which is page 1's (and every
page's) only occurrence, so no override is needed. Anchoring
`bill_to_address` on `LLC` with `region: label-block` starts the block on the
`LLC` line itself, `label-block`'s skip mechanism drops the matched `LLC`
word (leaving nothing on that line), and the two lines below - `94 MAPLE ST`
and `EAST LONGMEADOW MA 01028` - are exactly gold's `bill_to_address`
content, with the company name lines excluded entirely.

Verified directly against the real PDF via `docintel.extract.pdf.read_pages`
before this test was written: the real document returns
`'94 MAPLE ST\\nEAST LONGMEADOW MA 01028'` (raw, pre-`join_lines_comma`) for
this exact selector.
"""

from __future__ import annotations

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs

WIDTH = 612.0
HEIGHT = 792.0


def _upak_bill_to_address_selector() -> dict:
    """The actual `bill_to_address` selector out of the shipped persona - read
    from the loaded pack, not re-typed."""
    for pack in load_packs():
        if pack.name != "northstar":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint") == "northstar|upak":
                for selector in persona["field_selectors"]:
                    if selector.get("field") == "bill_to_address":
                        return selector
    raise AssertionError("northstar|upak persona (or its bill_to_address selector) not found")


def _real_upak_page1() -> PageText:
    """Page-1 word coordinates read directly off the real gold sample
    (`docs/persona-regeneration/05-upak/document.pdf`), including the
    competing `Location:` column so a region wide/tall enough to bleed it in
    is caught."""
    words = [
        Word(text="Bill", x0=90.0, y0=135.7, x1=102.4, y1=143.7),
        Word(text="To:", x0=104.6, y0=135.7, x1=117.1, y1=143.7),
        Word(text="Location:", x0=355.1, y0=135.7, x1=391.0, y1=143.7),
        # Right column (Location:) - close in y to the bill-to rows below,
        # must not be reached or bled in.
        Word(text="SHEARER'S", x0=355.1, y0=165.2, x1=400.6, y1=173.2),
        Word(text="FOOD", x0=402.8, y0=165.2, x1=425.9, y1=173.2),
        Word(text="CANADA", x0=428.1, y0=165.2, x1=461.4, y1=173.2),
        Word(text="INC", x0=463.6, y0=165.2, x1=477.4, y1=173.2),
        Word(text="N.S", x0=479.6, y0=165.2, x1=492.9, y1=173.2),
        # Bill-to block.
        Word(text="NORTHSTAR", x0=90.0, y0=169.2, x1=139.7, y1=177.2),
        Word(text="RECYCLING", x0=142.0, y0=169.2, x1=188.6, y1=177.2),
        Word(text="COMPANY", x0=190.8, y0=169.2, x1=231.2, y1=177.2),
        Word(text="745", x0=355.1, y0=173.2, x1=368.4, y1=181.2),
        Word(text="SOUTH", x0=370.6, y0=173.2, x1=398.6, y1=181.2),
        Word(text="GATE", x0=400.8, y0=173.2, x1=422.6, y1=181.2),
        Word(text="LLC", x0=90.0, y0=177.2, x1=104.7, y1=185.2),
        Word(text="MASTER", x0=355.1, y0=181.2, x1=388.4, y1=189.2),
        Word(text="ACC", x0=390.6, y0=181.2, x1=407.5, y1=189.2),
        Word(text="94", x0=90.0, y0=185.2, x1=98.9, y1=193.2),
        Word(text="MAPLE", x0=101.1, y0=185.2, x1=128.2, y1=193.2),
        Word(text="ST", x0=130.4, y0=185.2, x1=140.6, y1=193.2),
        Word(text="GUELPH", x0=355.1, y0=189.2, x1=387.9, y1=197.2),
        Word(text="ON", x0=390.2, y0=189.2, x1=402.2, y1=197.2),
        Word(text="N1G", x0=406.6, y0=189.2, x1=423.0, y1=197.2),
        Word(text="4N4", x0=425.2, y0=189.2, x1=439.9, y1=197.2),
        Word(text="EAST", x0=90.0, y0=193.2, x1=110.9, y1=201.2),
        Word(text="LONGMEADOW", x0=113.1, y0=193.2, x1=172.6, y1=201.2),
        Word(text="MA", x0=174.8, y0=193.2, x1=186.8, y1=201.2),
        Word(text="01028", x0=191.2, y0=193.2, x1=213.5, y1=201.2),
        # Something further below - must not bleed in either.
        Word(text="Account", x0=465.0, y0=229.9, x1=501.0, y1=238.9),
        Word(text="No.", x0=503.5, y0=229.9, x1=517.9, y1=238.9),
    ]
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def _ctx(page: PageText) -> JobContext:
    meta = (
        PageMeta(page_number=1, char_count=sum(len(w.text) for w in page.words),
                 image_count=0, annot_count=0, role="primary"),
    )
    return JobContext(document_id="d1", source_path="x.pdf", pages=(page,), page_meta=meta,
                       doc_type="standard_invoice")


def _extract_bill_to_address() -> str | None:
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_upak_bill_to_address_selector()],
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(_real_upak_page1()))
    return ctx.extracted.get("bill_to_address")


def test_reads_the_address_lines_under_the_wrapped_company_name() -> None:
    value = _extract_bill_to_address()
    assert value is not None
    lines = value.splitlines()
    assert lines == ["94 MAPLE ST", "EAST LONGMEADOW MA 01028"]


def test_does_not_bleed_in_the_company_name_or_llc_fragment() -> None:
    value = _extract_bill_to_address() or ""
    assert "NORTHSTAR" not in value
    assert "LLC" not in value


def test_does_not_bleed_in_the_location_column() -> None:
    value = _extract_bill_to_address() or ""
    assert "SHEARER" not in value
    assert "GUELPH" not in value
    assert "Account" not in value
