"""Finding C regression: Windstream's `bill_to_address` selector must not be
anchored to a single managed client's name.

The shipped selector anchored only on the literal `"CHOCTAW TRAVEL MART"` -
one of four clients in `aliases.MANAGED_CLIENTS`
(`src/docintel/packs/digitaldirection/aliases.py`). A real second sample,
`docs/Windstream_021942648_09022025_BILL.pdf`, is billed to "TOPS MARKETS
LLC" - not on the roster at all - and its `bill_to_address` came back empty.

**Tier 1 (a generic, client-name-independent label) was tried first and
rejected on real-document evidence.** Both real Kinetic-template documents
(`Windstream_041069076_07222025_BILL.pdf`, Choctaw; `Windstream_021942648_
09022025_BILL.pdf`, Tops) were read via `load_document`. The only candidate
label sitting structurally above the bill-to block is `Website:` (native) /
`Website'` (OCR misread of the colon), one line above the client's name. But
`label-block`'s skip mechanism (`executor.py::_candidates`) only excludes the
literal ANCHOR's own matched words, never the rest of a line - so anchoring
above the name leaves the name itself unskipped, and the resulting value
became `"CHOCTAW TRAVEL MART, PO BOX 1550, DURANT OK 74702-1550"` instead of
gold's `"PO Box 1550, Durant, OK 74702-1550"` (see the field's twin,
`bill_to_name`, for why the name is a SEPARATE fact, not part of this one).
That is a regression on the one currently-passing document, confirmed via a
live `docintel.cli process --json` run - not a hypothetical. No adjust op in
the closed grammar (`schema.BASE_ADJUST_OPS`) drops a `text_block`'s first
line, so there is no way to keep a generic anchor AND exclude the name.

**Tier 2 (roster fallback) is what ships.** `anchor_alts` widens the selector
to the other three `MANAGED_CLIENTS` entries verbatim (anchor matching is
case-insensitive, so the roster's mixed-case spelling is used as-is). This
fixes any FUTURE Windstream bill to a KNOWN managed client, regardless of
which of the four prints. It explicitly does NOT fix `021942648` (Tops
Markets, not on the roster) - onboarding a real new client is a business-data
decision, out of scope for this fix (see the task brief's scope boundary) -
so that document's `bill_to_address` staying empty is the CORRECT, honest
outcome, verified below.

This test drives the REAL selector out of the shipped persona through the
REAL executor, against minimal label-block layouts modelled on the real
geometry (client name line, then a PO Box line, then a city/state/zip line),
for all four roster entries plus one client that IS NOT on the roster - so a
"fix" that just swapped which single literal is hardcoded cannot pass this by
accident.
"""

from __future__ import annotations

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs
from digitaldirection import PACK as _DIGITALDIRECTION_PACK

WIDTH = 612.0
HEIGHT = 792.0


def _windstream_bill_to_address_selector() -> dict:
    """The actual `bill_to_address` selector out of the shipped persona.

    Read from the loaded pack rather than re-typed here - re-typing it would
    test a copy of the rule, not the rule itself, and could quietly drift from
    what ships.
    """
    for pack in load_packs() + [_DIGITALDIRECTION_PACK]:
        if pack.name != "digitaldirection":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint") == "digitaldirection|windstream":
                for selector in persona["field_selectors"]:
                    if selector.get("field") == "bill_to_address":
                        return selector
    raise AssertionError(
        "digitaldirection|windstream persona (or its bill_to_address selector) not found"
    )


def _bill_to_block(name: str, po_box: str, city_state_zip: str) -> PageText:
    """A minimal label-block: a client-name line, then a PO Box line, then a
    city/state/zip line - the real shape both Kinetic-template samples print
    (`docs/Windstream_041069076...` for Choctaw, `docs/Windstream_021942648...`
    for Tops), all left-aligned in the same narrow column the real invoices
    use (~x0=327)."""
    def _row(text: str, y: float) -> list[Word]:
        words = []
        x = 327.0
        for tok in text.split(" "):
            width = 7.0 * len(tok)
            words.append(Word(text=tok, x0=x, y0=y, x1=x + width, y1=y + 9.0))
            x += width + 6.0
        return words

    words = [
        *_row(name, 127.0),
        *_row(po_box, 137.0),
        *_row(city_state_zip, 147.0),
    ]
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def _ctx(page: PageText) -> JobContext:
    meta = (
        PageMeta(
            page_number=1,
            char_count=sum(len(w.text) for w in page.words),
            image_count=0,
            annot_count=0,
            role="primary",
        ),
    )
    return JobContext(
        document_id="d1", source_path="x.pdf", pages=(page,), page_meta=meta,
        doc_type="telecom_bill",
    )


def _extract_bill_to_address(name: str, po_box: str, city_state_zip: str) -> str | None:
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "telecom_bill",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_windstream_bill_to_address_selector()],
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(_bill_to_block(name, po_box, city_state_zip)))
    return ctx.extracted.get("bill_to_address")


def test_still_matches_choctaw_travel_mart() -> None:
    """No regression on the one gold document (`Windstream_041069076`,
    Choctaw) that already passed this field - the primary anchor is
    unchanged."""
    assert (
        _extract_bill_to_address("CHOCTAW TRAVEL MART", "PO BOX 1550", "DURANT OK 74702-1550")
        == "PO BOX 1550\nDURANT OK 74702-1550"
    )


def test_matches_clyde_administration_servi_via_anchor_alt() -> None:
    """The bug: a Windstream bill to any OTHER roster client had no matching
    anchor at all. `Clyde Administration Servi` is the first `anchor_alts`
    entry."""
    assert (
        _extract_bill_to_address("Clyde Administration Servi", "PO BOX 1955", "OREM UT 84059-1955")
        == "PO BOX 1955\nOREM UT 84059-1955"
    )


def test_matches_clyde_companies_via_anchor_alt() -> None:
    assert (
        _extract_bill_to_address("Clyde Companies", "PO BOX 1955", "OREM UT 84059-1955")
        == "PO BOX 1955\nOREM UT 84059-1955"
    )


def test_matches_city_of_dublin_via_anchor_alt() -> None:
    assert (
        _extract_bill_to_address("City of Dublin", "PO BOX 2005", "DUBLIN OH 43017-3219")
        == "PO BOX 2005\nDUBLIN OH 43017-3219"
    )


def test_a_client_not_on_the_roster_is_an_honest_miss() -> None:
    """Scope boundary: `021942648`'s real client is `TOPS MARKETS LLC`, not on
    `aliases.MANAGED_CLIENTS`. Onboarding a real client is a business-data
    decision, not a mechanical fix - so this must return None, not guess."""
    assert _extract_bill_to_address("TOPS MARKETS LLC", "PO BOX 1027", "BUFFALO NY 14240-1027") is None
