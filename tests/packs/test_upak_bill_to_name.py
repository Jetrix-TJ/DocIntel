"""U-Pak was one of the 5 personas that shipped with no `bill_to_name` selector
at all (STATUS-SUMMARY.md §4.1), so `bill_to_mismatch` could never fire
regardless of who a document was billed to. This file is the selector that
closed its share of that finding; all five - `comcast`, `windstream`, `edco`,
`upak`, `veritiv` - carry one as of this branch, so the count is now zero.

The real gold PDF prints `Bill To:` directly above the customer name,
left-aligned - the same shape Lumen's shipped, working `bill_to_name` selector
already handles.

KNOWN DEFECT, found by the whole-branch review that replayed all 12 real
second-period samples (`all-docs/second-samples/u_pak/*.pdf`) and unresolved as
of this commit: on 3 of those 12 the `text_block` capture is not the party name.
See `src/docintel/packs/northstar/personas/upak.json`'s `notes` for the measured
detail and why no in-vocabulary selector fixes it."""

from __future__ import annotations

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs

WIDTH = 612.0
HEIGHT = 792.0


def _upak_bill_to_name_selector() -> dict:
    for pack in load_packs():
        if pack.name != "northstar":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint") == "northstar|upak":
                for selector in persona["field_selectors"]:
                    if selector.get("field") == "bill_to_name":
                        return selector
    raise AssertionError("northstar|upak persona (or its bill_to_name selector) not found")


def _bill_to_page(company: str) -> PageText:
    words = [
        Word(text="Bill", x0=90.0, y0=135.7, x1=104.6, y1=145.7),
        Word(text="To:", x0=104.6, y0=135.7, x1=118.0, y1=145.7),
        *[
            Word(text=tok, x0=90.0 + i * 60.0, y0=169.2, x1=90.0 + i * 60.0 + 55.0, y1=179.2)
            for i, tok in enumerate(company.split())
        ],
    ]
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def _ctx(page: PageText) -> JobContext:
    meta = (
        PageMeta(page_number=1, char_count=sum(len(w.text) for w in page.words),
                 image_count=0, annot_count=0, role="primary"),
    )
    return JobContext(document_id="d1", source_path="x.pdf", pages=(page,), page_meta=meta,
                       doc_type="standard_invoice")


def _extract_bill_to_name(company: str) -> str | None:
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_upak_bill_to_name_selector()],
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(_bill_to_page(company)))
    return ctx.extracted.get("bill_to_name")


def test_reads_the_printed_bill_to_name() -> None:
    assert _extract_bill_to_name("NORTHSTAR RECYCLING COMPANY LLC") == "NORTHSTAR RECYCLING COMPANY LLC"


def test_reads_a_different_printed_bill_to_name() -> None:
    """The whole point: a name that is NOT on the roster must still be read,
    or bill_to_mismatch can never fire."""
    assert _extract_bill_to_name("SOME OTHER COMPANY LLC") == "SOME OTHER COMPANY LLC"


def _bill_to_page_with_same_row_label(company: str) -> PageText:
    """Reproduces the real gold PDF's hazard: `Bill To:` shares its row with an
    unrelated `Location:` label 265pt to the right (real geometry: `Bill`/`To:`
    at x0=90.0/104.6, `Location:` at x0=355.1, all at y0=135.7), well inside
    `near-anchor`'s 300pt horizontal reach. `pattern: "text"` returns the first
    non-empty line-candidate in the region - which is the anchor's own row,
    still carrying `Location:` after `Bill`/`To:` are excluded as the matched
    anchor - so it reads the neighbouring label instead of the customer name
    on the row below. `pattern: "text_block"`'s column-cut logic is what
    excludes `Location:` from the block. This is the actual bug that
    `_bill_to_page` above (single label, no same-row neighbour) cannot catch."""
    words = [
        Word(text="Bill", x0=90.0, y0=135.7, x1=104.6, y1=145.7),
        Word(text="To:", x0=104.6, y0=135.7, x1=118.0, y1=145.7),
        Word(text="Location:", x0=355.1, y0=135.7, x1=391.0, y1=145.7),
        *[
            Word(text=tok, x0=90.0 + i * 60.0, y0=169.2, x1=90.0 + i * 60.0 + 55.0, y1=179.2)
            for i, tok in enumerate(company.split())
        ],
    ]
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def test_does_not_read_a_same_row_neighbouring_label() -> None:
    """The real gold PDF prints `Bill To:` and `Location:` on the same row,
    265pt apart - both inside near-anchor's 300pt horizontal reach. A selector
    using `pattern: "text"` (the brief's original proposal, and Lumen's
    shipped shape) reads `Location:` off that shared row instead of the
    customer name printed on the line below. This is what forced the switch
    to `pattern: "text_block"` (whose column-cut logic drops the neighbouring
    label). Reverting to `pattern: "text"` must fail this test."""
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_upak_bill_to_name_selector()],
            "layout_fingerprint": {},
        }
    )
    page = _bill_to_page_with_same_row_label("NORTHSTAR RECYCLING COMPANY")
    ctx = Executor(persona).apply(_ctx(page))
    value = ctx.extracted.get("bill_to_name")
    assert value == "NORTHSTAR RECYCLING COMPANY"
    assert "Location:" not in (value or "")
