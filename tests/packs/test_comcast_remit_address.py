"""Comcast is missing a `remit_address` selector entirely (gold expects
`"PO Box 60533, City of Industry, CA 91716-0533"`, current extraction is
`None` - there is no selector for the field at all in `comcast.json`).

**Real-document investigation** (`docs/persona-regeneration/08-comcast/document.pdf`,
page 1, via `pdfplumber.extract_words()`): the word `COMCAST` (all-caps) appears
exactly once on page 1, at `x0=347.6, top=694.5`, immediately above a two-line
address block:

    COMCAST                              top=694.5
    PO BOX 60533                         top=703.6
    CITY OF INDUSTRY CA 91716-0533       top=712.7

This sits at the very bottom of the remittance stub, well below the existing
`remit_payee` selector's anchor (`"Make checks payable to"`, whose value
`Comcast` sits at `x0=543.9, top=653.5`, 41pt above and in a different column
- the two are NOT part of the same visual block, so `remit_payee`'s region
cannot simply be widened to reach this address).

Anchor matching is case-insensitive (`executor._norm`), so a plain `"COMCAST"`
anchor also matches the word `Comcast` (mixed case) printed three OTHER times
on page 1, all ABOVE the target block, in reading order:

    "Comcast Business services"  (New charges table row) x0=317.0 top=106.9
    "Your Comcast Business account online is..."          x0=342.2 top=294.7
    "Make checks payable to Comcast Do not send cash"      x0=543.9 top=653.5

The real block at top=694.5 is the LAST occurrence of the word on the page,
so `anchor_occurrence: "last"` is required - the default ("first") would
resolve to the "New charges" table row instead and either capture nothing
useful or the wrong block entirely. This follows the same SHAPE already
shipped for Windstream's and Veritiv's `remit_address` (anchor on the
payee's own printed name, `anchor_occurrence: "last"`, `region:
"label-block"`) - but it is NOT an equally-qualified instance of that
pattern: Windstream's primary anchor is the real label `"Remit Payment To"`
(bare `"WINDSTREAM"` is only a fallback `anchor_alts` entry), and Veritiv
anchors the full legal name `"VERITIV OPERATING COMPANY"`, not a bare brand
word. This selector's anchor is the single most generic string available -
plain `"COMCAST"`, no qualifying words - because no more specific real label
exists anywhere on the one known Comcast document.

**DISCLOSED RISK (found by second-round review): this is currently
unverifiable.** There are zero second-period Comcast samples anywhere in the
corpus. If some other real Comcast layout prints a 5th occurrence of the
word `Comcast`/`COMCAST` below this target block, `anchor_occurrence: "last"`
would silently resolve to that occurrence instead, with nothing in today's
corpus able to catch it. This risk is real and unmitigated as of this
writing - re-verify the moment any second Comcast sample becomes available.

This fixture reproduces all four real occurrences (not just the target one),
so a selector that reverted to the default occurrence, or that widened
`remit_payee`'s region instead of adding a real selector, would fail here.
"""

from __future__ import annotations

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs

WIDTH = 612.0
HEIGHT = 792.0


def _comcast_remit_address_selector() -> dict:
    """The actual `remit_address` selector out of the shipped persona - read
    from the loaded pack, not re-typed, so this test exercises the rule that
    ships rather than a copy of it."""
    for pack in load_packs():
        if pack.name != "digitaldirection":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint") == "digitaldirection|comcast":
                for selector in persona["field_selectors"]:
                    if selector.get("field") == "remit_address":
                        return selector
    raise AssertionError(
        "digitaldirection|comcast persona (or its remit_address selector) not found"
    )


def _row(text: str, x0: float, y0: float, y1: float) -> list[Word]:
    words = []
    x = x0
    for tok in text.split(" "):
        width = 7.2 * len(tok)
        words.append(Word(text=tok, x0=x, y0=y0, x1=x + width, y1=y1))
        x += width + 3.0
    return words


def _real_comcast_page1() -> PageText:
    """Page-1 word coordinates read directly off the real gold sample
    (`docs/persona-regeneration/08-comcast/document.pdf`, pdfplumber
    `extract_words`), reproducing every real occurrence of `Comcast`/`COMCAST`
    on the page - not just the target block - so a selector using the
    default (`first`) anchor occurrence, or one that bleeds in the payee-stub
    line, is caught."""
    words = [
        # 1st occurrence: "New charges" table row (mid-line, line-head).
        *_row("Comcast Business services", 317.0, 106.9, 115.9),
        Word(text="217.89", x0=542.4, y0=106.9, x1=569.9, y1=115.9),
        # 2nd occurrence: marketing prose, mid-line (not line-head).
        Word(text="Your", x0=316.9, y0=294.7, x1=339.1, y1=305.7),
        Word(text="Comcast", x0=342.2, y0=294.7, x1=385.2, y1=305.7),
        Word(text="Business", x0=388.2, y0=294.7, x1=431.0, y1=305.7),
        Word(text="account", x0=434.1, y0=294.7, x1=472.4, y1=305.7),
        # Remittance stub: bill-to block, then the "Make checks payable to
        # Comcast" line (3rd occurrence, mid-line).
        Word(text="CLYDE", x0=36.6, y0=634.5, x1=63.3, y1=642.5),
        Word(text="ADMINISTRATION", x0=65.5, y0=634.5, x1=133.9, y1=642.5),
        Word(text="SERVI", x0=136.2, y0=634.5, x1=160.2, y1=642.5),
        Word(text="ATTN", x0=36.6, y0=643.6, x1=57.5, y1=651.6),
        Word(text="CLYDE", x0=59.7, y0=643.6, x1=86.4, y1=651.6),
        Word(text="COMPANIES-IT", x0=88.6, y0=643.6, x1=146.4, y1=651.6),
        Word(text="PO", x0=36.6, y0=652.7, x1=48.2, y1=660.7),
        Word(text="BOX", x0=50.4, y0=652.7, x1=67.3, y1=660.7),
        Word(text="1955", x0=69.5, y0=652.7, x1=87.3, y1=660.7),
        Word(text="Make", x0=468.6, y0=653.5, x1=485.2, y1=660.5),
        Word(text="checks", x0=487.1, y0=653.5, x1=508.7, y1=660.5),
        Word(text="payable", x0=510.6, y0=653.5, x1=534.1, y1=660.5),
        Word(text="to", x0=536.0, y0=653.5, x1=542.0, y1=660.5),
        Word(text="Comcast", x0=543.9, y0=653.5, x1=571.3, y1=660.5),
        Word(text="Do", x0=575.2, y0=653.5, x1=583.9, y1=660.5),
        Word(text="OREM,", x0=36.6, y0=661.8, x1=62.8, y1=669.8),
        Word(text="UT", x0=65.0, y0=661.8, x1=75.7, y1=669.8),
        Word(text="84059-1955", x0=77.9, y0=661.8, x1=120.6, y1=669.8),
        Word(text="not", x0=468.6, y0=661.5, x1=478.3, y1=668.5),
        Word(text="send", x0=480.3, y0=661.5, x1=495.0, y1=668.5),
        Word(text="cash", x0=497.0, y0=661.5, x1=511.4, y1=668.5),
        # 4th (LAST) occurrence: the real target block.
        Word(text="COMCAST", x0=347.6, y0=694.5, x1=387.6, y1=702.5),
        Word(text="PO", x0=347.6, y0=703.6, x1=359.2, y1=711.6),
        Word(text="BOX", x0=361.4, y0=703.6, x1=378.3, y1=711.6),
        Word(text="60533", x0=380.5, y0=703.6, x1=402.8, y1=711.6),
        Word(text="CITY", x0=347.6, y0=712.7, x1=365.9, y1=720.7),
        Word(text="OF", x0=368.1, y0=712.7, x1=379.2, y1=720.7),
        Word(text="INDUSTRY", x0=381.4, y0=712.7, x1=422.3, y1=720.7),
        Word(text="CA", x0=424.5, y0=712.7, x1=435.6, y1=720.7),
        Word(text="91716-0533", x0=442.3, y0=712.7, x1=485.0, y1=720.7),
        # The scanline, below everything - must not bleed in.
        Word(text="849544462036524200221119", x0=39.6, y0=754.1, x1=212.4, y1=764.1),
    ]
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def _ctx(page: PageText) -> JobContext:
    meta = (
        PageMeta(page_number=1, char_count=sum(len(w.text) for w in page.words),
                 image_count=0, annot_count=0, role="primary"),
    )
    return JobContext(document_id="d1", source_path="x.pdf", pages=(page,), page_meta=meta,
                       doc_type="telecom_bill")


def _extract_remit_address() -> str | None:
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "telecom_bill",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_comcast_remit_address_selector()],
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(_real_comcast_page1()))
    return ctx.extracted.get("remit_address")


def test_reads_the_real_documents_remit_address_block() -> None:
    value = _extract_remit_address()
    assert value is not None
    lines = value.splitlines()
    assert lines == ["PO BOX 60533", "CITY OF INDUSTRY CA 91716-0533"]


def test_does_not_bleed_in_the_payee_stub_or_bill_to_block() -> None:
    value = _extract_remit_address() or ""
    assert "CLYDE" not in value
    assert "checks" not in value
    assert "New" not in value


def test_does_not_resolve_to_the_first_occurrence() -> None:
    """The default `anchor_occurrence` ("first") would land on the 'New
    charges' table row, not the address block - guards against a selector
    that drops the required `anchor_occurrence: "last"`."""
    value = _extract_remit_address() or ""
    assert "services" not in value
    assert "217.89" not in value
