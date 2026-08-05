"""U-Pak is one of the 5 personas with no bill_to_name selector at all
(STATUS-SUMMARY.md §4.1), so `bill_to_mismatch` can never fire regardless of
who a document is billed to. The real gold PDF prints `Bill To:` directly
above the customer name, left-aligned - the same shape Lumen's shipped,
working `bill_to_name` selector already handles."""

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
