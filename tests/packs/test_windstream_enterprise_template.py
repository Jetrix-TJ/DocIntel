"""Finding 3 regression: Windstream prints TWO structurally different bills,
and `windstream.json` only encoded one of them.

Measured, by reading page 1 of all four real Windstream PDFs through
`normalize.load_document` and asking `executor._runs` which of the persona's
anchor phrases actually occur (the disjointness this file's last test re-checks
synthetically):

                                     Kinetic     Kinetic     Enterprise  Enterprise
                                     (gold)
    anchor phrase                    041069076   021942648   216713099   205577168
    text_source                      native      ocr         native      ocr
    ------------------------------------------------------------------------------
    "Account number"                     2           1           -           -
    "Invoice date"                       1           1           -           -
    "Due date"                           1           1           -           -
    "Previous Bill"                      1           1           -           -
    "Payments/Adjustments"               1           1           -           -
    "Current Charges Due"                1           -           -           -
    "Total Amount Due"                   1           1           -           -
    "check payable to"                   1           -           -           -
    "Account Invoice Total"              -           -           2           2
    "TOTAL INVOICE AMOUNT"               -           -           1           1
    "Previous Total"                     -           -           1           1
    "Payments Applied"                   -           -           1           1
    "New Charges"                        -           -           1           1
    "Due by"                             -           -           1           1
    "Remit Payment To"                   -           -           1           1
    "WINDSTREAM"                         2           4           9           9

The two label vocabularies are **completely disjoint** but for the brand name
itself. That is the whole finding: on `Windstream_205577168_08222025_BILL.pdf`
and `Windstream_216713099_08272025_BILL.pdf` every one of the persona's
selectors missed, and the ONE field that populated did so through the
`WINDSTREAM` anchor - which, being the vendor's own name, matched a word inside
a prose sentence ("Manage your Windstream services directly and review...") and
returned a paragraph of boilerplate as `remit_address`. One garbled field out
of twelve was not a near-miss; it was a total miss plus a false positive.

Two things follow, and both are what this file tests:

1. The Enterprise wording goes in as `anchor_alts`, the grammar's existing
   alternate-label mechanism (`selector-grammar.md` section 1, `anchor_alts`;
   `executor._resolve_anchor` tries them in declaration order only when the
   primary anchor fails to resolve). Because the vocabularies are disjoint, the
   alts are unreachable on a Kinetic bill and the primaries are unreachable on
   an Enterprise bill - the two templates cannot interfere, which is exactly
   what makes one persona able to carry both.

2. `remit_address` is the one selector where that argument does NOT hold,
   because its anchor is the brand name and the brand name is on both
   templates. So its ordering is inverted: the Enterprise template's real
   label, `Remit Payment To`, becomes the primary, and the bare `WINDSTREAM`
   brand-name anchor drops to the alt - which keeps the Kinetic behaviour byte
   for byte (no Kinetic bill carries `Remit Payment To`, so the alt still fires
   there) while stopping the prose match on Enterprise bills.

Both fixtures below are built from the REAL word coordinates of the real
documents (dumped from the text layer), not from invented geometry, because
every region resolver involved - `near-anchor`, `label-block` - is measured in
points and would be trivially satisfiable by a fixture with convenient spacing.
The Enterprise fixture takes its geometry from the native sample (216713099,
whose text layer gives exact coordinates) and its amounts from the OCR sample
(205577168), whose four summary figures - 5.12, -2.13, 1.83, 4.82 - are all
distinct, so a selector that read a NEIGHBOURING row of the summary ladder
cannot pass here by coincidence. 216713099's own figures are 646.69 / -646.69 /
647.01 / 647.01 and would not discriminate.
"""

from __future__ import annotations

from typing import Any

import pytest

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor, _norm, _runs
from docintel.grammar.ops.infer import resolve_vendor_alias
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs

WIDTH = 612.0
HEIGHT = 792.0

Line = tuple[float, list[tuple[str, float, float]]]


def _shipped_persona() -> dict[str, Any]:
    """The real `digitaldirection|windstream` persona as shipped.

    Read out of the loaded pack rather than re-typed here: a re-typed copy
    would test a copy of the rule, not the rule that ships.
    """
    for pack in load_packs():
        if pack.name != "digitaldirection":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint") == "digitaldirection|windstream":
                return persona
    raise AssertionError("digitaldirection|windstream persona not found in the loaded packs")


def _page(lines: list[Line], source: str = "native") -> PageText:
    words: list[Word] = []
    for y0, cells in lines:
        for text, x0, x1 in cells:
            words.append(Word(text=text, x0=x0, y0=y0, x1=x1, y1=y0 + 8.0))
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT, source=source)


def _digitaldirection_pack() -> Any:
    for pack in load_packs():
        if pack.name == "digitaldirection":
            return pack
    raise AssertionError("digitaldirection pack not found")


def _ctx(page: PageText, text_source: str = "native") -> JobContext:
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
        document_id="d1",
        source_path="x.pdf",
        pages=(page,),
        page_meta=meta,
        text_source=text_source,
        pack=_digitaldirection_pack(),
        doc_type="telecom_bill",
    )


def _extract(page: PageText, text_source: str = "native") -> dict[str, Any]:
    persona = parse_persona(_shipped_persona())
    return dict(Executor(persona).apply(_ctx(page, text_source)).extracted.values)


def _vendor_identity(page: PageText, text_source: str = "native") -> dict[str, Any]:
    """What the record would report about WHO sent this bill.

    The selectors alone cannot answer that: `vendor_name` is settled in Stage 6
    by `resolve_vendor_alias`, which decides between what the page printed and
    what the pack's `DISPLAY_NAMES` table says. So this runs the real op over
    the real extraction with the real pack attached - the only arrangement in
    which "the printed brand wins where it is printed" is actually observable.

    Extracted and derived are merged, because WHICH of the two carries
    `vendor_name` is the mechanism rather than an implementation detail: a
    printed name stays in `extracted` and the op leaves it there, while a
    table-supplied one is written to `derived`. The record surfaces both (as
    `fields.vendor_name` and `derived.vendor_name` respectively), and
    `coverage.assess` counts either as satisfying the selector. Extracted is
    applied second so that if the op ever started overwriting a printed name,
    this would keep reporting the printed one and the assertions on the table
    path would fail loudly instead of both paths quietly agreeing.
    """
    persona = parse_persona(_shipped_persona())
    ctx = resolve_vendor_alias(Executor(persona).apply(_ctx(page, text_source)))
    return {**ctx.derived.values, **ctx.extracted.values}


# Every `adjust` op - `join_lines_comma`, `resolve_vendor_alias`,
# `normalize_credit_sign` - runs in Stage 6 (`s6_capture.py`), not in the
# Executor. So the values asserted below are the RAW captures: a `text_block`
# still newline-separated, a payee still in the case it was printed in. That is
# deliberately the right level for a selector test - it is what the selector
# decided, with nothing downstream able to launder a wrong region into a
# plausible-looking string. (A negative `payments_credits` is not an exception:
# the money parser reads the printed parentheses, before any op runs.)


# ---------------------------------------------------------------------------
# The Enterprise template ("Windstream Enterprise" / Golub Corporation bills).
#
# Coordinates are page 1 of Windstream_216713099_08272025_BILL.pdf verbatim.
# Note the shape of the header: it is a three-column table whose labels are
# stacked over TWO visual lines -
#
#       Account      Invoice        Total
#       Number       Date           Amount Due
#       205577168    Aug 22, 2025   $4.82
#
# so no single line spells "Account Number", "Invoice Date" or "Total Amount
# Due" as a contiguous run. That is not merely a different choice of words from
# the Kinetic template - it is why `_ANCHOR_RE` in `extract/pageroles.py` finds
# no identity anchor on this page either. The contiguous runs the page DOES
# offer are the header's two rows read across: "Account Invoice Total" and
# "Number Date Amount Due".
# ---------------------------------------------------------------------------

ENTERPRISE_LINES: list[Line] = [
    (
        32.2,
        [("For", 185, 196), ("Customer", 197, 228), ("Service", 230, 253),
         ("Correspondence:", 255, 309)],
    ),
    # The only place either Enterprise sample prints its brand as READABLE text.
    # The native sample's letterhead is an image (the tokens WINDSTREAM and
    # ENTERPRISE appear nowhere in its text layer, exactly as with Lumen's logo);
    # the OCR sample's letterhead does come back, but this line is the one that
    # survives on BOTH, which is why the selector reads here rather than there.
    (
        40.2,
        [("ATTN:", 185, 205), ("Windstream", 207, 245), ("Enterprise", 246, 278),
         ("Services", 280, 307)],
    ),
    (36.7, [("Account", 349, 385), ("Invoice", 434, 465), ("Total", 520, 542)]),
    (
        48.2,
        [
            ("P.O.", 185, 199), ("Box", 201, 213), ("25310", 215, 234),
            ("Number", 350, 384), ("Date", 439, 459),
            ("Amount", 507, 541), ("Due", 543, 560),
        ],
    ),
    (
        59.7,
        [
            ("205577168", 353, 398),
            ("Aug", 426, 442), ("22,", 445, 457), ("2025", 460, 480),
            ("$4.82", 525, 558),
        ],
    ),
    # The remittance stub's own invoice-number/due-date pair, 42pt lower. It
    # must stay OUTSIDE the header anchor's `near-anchor` band, or `bill_date`
    # would read the due date instead of the invoice date.
    (
        101.7,
        [("77170792", 351, 391), ("Sep", 426, 442), ("10,", 445, 457), ("2025", 460, 480)],
    ),
    (162.9, [("Remit", 376, 402), ("Payment", 405, 444), ("To:", 447, 462)]),
    (174.9, [("Windstream", 376, 429)]),
    (186.9, [("P.O.", 376, 396), ("Box", 399, 416), ("9001013", 419, 458)]),
    (198.9, [("Louisville,", 376, 420), ("KY", 423, 436), ("40290-1013", 442, 495)]),
    # The Account Summary ladder. Labels left, amounts right-aligned at x=256.
    (332.5, [("Previous", 36, 67), ("Total", 69, 87), ("$5.12", 256, 284)]),
    (
        342.5,
        [
            ("Payments", 36, 72), ("Applied", 74, 100), ("-", 103, 105),
            ("Thank", 108, 130), ("You", 132, 146), ("($2.13)", 253, 287),
        ],
    ),
    # Right-hand column prose shares these visual lines on the real page. Kept
    # in, because it is what a region resolver has to survive: the sentence
    # ends in the bare word "Windstream." and there is a second bare
    # "Windstream" 150pt lower (the last line below).
    (
        365.5,
        [
            ("Monthly", 36, 64), ("Charges", 66, 96), ("$0.00", 256, 284),
            ("payments.", 325, 362), ("No", 364, 374), ("part", 377, 390),
            ("of", 393, 399), ("this", 401, 414), ("fee", 416, 427),
            ("goes", 429, 447), ("to", 449, 456), ("Windstream.", 458, 503),
        ],
    ),
    (
        427.5,
        [
            ("New", 36, 52), ("Charges", 55, 87), ("-", 89, 92),
            ("Due", 94, 109), ("by", 111, 120),
            ("Sep", 123, 137), ("10,", 140, 151), ("2025", 153, 171),
            ("$1.83", 256, 284),
        ],
    ),
    (
        445.5,
        [
            ("TOTAL", 36, 63), ("INVOICE", 65, 98), ("AMOUNT", 100, 135),
            ("$4.82", 256, 284),
            ("capabilities", 325, 365), ("while", 367, 385), ("ensuring", 387, 418),
            ("your", 420, 436), ("current", 438, 463), ("experience", 465, 504),
        ],
    ),
    (
        518.5,
        [
            ("Manage", 36, 65), ("your", 67, 83), ("Windstream", 85, 128),
            ("services", 130, 159), ("directly", 161, 187), ("and", 189, 202),
            ("review", 204, 228),
        ],
    ),
]

# ---------------------------------------------------------------------------
# The Kinetic template, for the no-regression half. Coordinates are page 1 of
# the gold document, Windstream_041069076_07222025_BILL.pdf, verbatim.
# ---------------------------------------------------------------------------

KINETIC_LINES: list[Line] = [
    (
        48.3,
        [
            ("Account", 331, 361), ("number", 363, 391),
            ("Telephone", 410, 448), ("number", 450, 478),
            ("Invoice", 493, 520), ("date", 522, 538),
        ],
    ),
    (
        59.4,
        [
            ("041069076", 331, 371), ("918-653-3103", 410, 461),
            ("July", 493, 506), ("22,", 508, 519), ("2025", 522, 539),
        ],
    ),
    (243.2, [("Previous", 328, 363), ("Bill", 365, 377), ("$1,231.74", 534, 574)]),
    (
        254.1,
        [
            ("Payments/Adjustments", 328, 420), ("thru", 422, 438), ("07/18", 440, 463),
            ("$1,231.74", 534, 574), ("CR", 577, 590),
        ],
    ),
    (
        265.0,
        [("Amount", 328, 359), ("Previously", 361, 403), ("Due", 405, 422), ("$.00", 557, 574)],
    ),
    (
        275.8,
        [
            ("Current", 328, 358), ("Charges", 360, 394), ("Due", 397, 413),
            ("-", 416, 419), ("08/11/25", 421, 456), ("$1,230.14", 534, 574),
        ],
    ),
    (287.0, [("Total", 328, 349), ("Amount", 352, 386), ("Due", 388, 405), ("$1,230.14", 534, 574)]),
    (
        541.6,
        [
            ("Detach", 136, 158), ("and", 160, 172), ("return", 174, 192), ("this", 194, 205),
            ("payment", 207, 234), ("slip", 236, 246), ("with", 248, 260), ("your", 262, 276),
            ("check", 278, 296), ("payable", 298, 323), ("to", 325, 330),
            ("OKLAHOMA", 332, 372), ("WINDSTREAM,", 374, 424), ("LLC.", 426, 441),
        ],
    ),
    (
        590.1,
        [
            ("Account", 333, 362), ("number", 365, 392),
            ("Telephone", 414, 451), ("number", 453, 481),
            ("Due", 497, 511), ("date", 513, 529),
        ],
    ),
    (
        602.5,
        [
            ("ATTN:", 40, 60), ("SUPPORT", 62, 96), ("SERVICES", 98, 133),
            ("041069076", 333, 373), ("918-653-3103", 414, 465),
            ("August", 497, 521), ("11,", 523, 535), ("2025", 537, 555),
        ],
    ),
    (681.5, [("CHOCTAW", 40, 76), ("TRAVEL", 78, 105), ("MART", 107, 127)]),
    (690.0, [("PO", 40, 50), ("BOX", 52, 66), ("1550", 68, 84)]),
    (
        698.5,
        [
            ("DURANT", 40, 69), ("OK", 71, 81), ("74702-1550", 83, 120),
            ("WINDSTREAM", 367, 422),
        ],
    ),
    (711.0, [("PO", 367, 379), ("BOX", 381, 398), ("9001908", 400, 431)]),
    (720.6, [("LOUISVILLE,", 367, 415), ("KY", 417, 428), ("40290-1908", 430, 473)]),
]


@pytest.fixture
def enterprise() -> dict[str, Any]:
    return _extract(_page(ENTERPRISE_LINES))


@pytest.fixture
def kinetic() -> dict[str, Any]:
    return _extract(_page(KINETIC_LINES))


@pytest.fixture
def enterprise_identity() -> dict[str, Any]:
    return _vendor_identity(_page(ENTERPRISE_LINES))


@pytest.fixture
def kinetic_identity() -> dict[str, Any]:
    return _vendor_identity(_page(KINETIC_LINES))


# ---------------------------------------------------------------------------
# The Enterprise template must now extract.
# ---------------------------------------------------------------------------


def test_enterprise_header_yields_the_account_number(enterprise: dict[str, Any]) -> None:
    """`account_number` was `missing_required` on both real Enterprise bills.

    The label it needs, "Account Number", is split across two visual lines, so
    the alt anchors the header's FIRST row read across - "Account Invoice
    Total" - and reads the value row two lines below it.
    """
    assert enterprise["account_number"] == "205577168"


def test_enterprise_header_yields_the_invoice_date_not_the_due_date(
    enterprise: dict[str, Any],
) -> None:
    """One anchor, three fields - the same trick `windstream.json`'s own note
    already describes for the Kinetic header, and it survives the transplant.

    The assertion that earns its keep is the negative one: the remittance
    stub's due date (Sep 10) sits 42pt below the same anchor, so a
    `near-anchor` band one line too tall would return it instead.
    """
    assert enterprise["bill_date"].iso == "2025-08-22"


def test_enterprise_summary_ladder_yields_all_four_amounts(
    enterprise: dict[str, Any],
) -> None:
    """Four adjacent rows of one ladder, four distinct values. Each label is
    reworded from the Kinetic template ("Previous Total" not "Previous Bill",
    "Payments Applied" not "Payments/Adjustments", "New Charges" not "Current
    Charges Due", "TOTAL INVOICE AMOUNT" not "Total Amount Due") and each
    amount belongs to exactly one of them.
    """
    assert str(enterprise["prior_balance"]) == "5.12"
    assert str(enterprise["payments_credits"]) == "-2.13"  # printed "($2.13)"
    assert str(enterprise["current_charges"]) == "1.83"
    assert str(enterprise["total_printed"]) == "4.82"


def test_enterprise_yields_the_due_date_off_the_new_charges_row(
    enterprise: dict[str, Any],
) -> None:
    """The Enterprise template has no "Due date" label at all: the date is
    printed inside the summary row, "New Charges - Due by Sep 10, 2025". So
    the alt anchors "Due by" and takes the date beside it - on a line that
    also carries a currency amount and a bare year.
    """
    assert enterprise["due_date"].iso == "2025-09-10"


def test_enterprise_remit_address_is_the_remittance_block_not_a_prose_sentence(
    enterprise: dict[str, Any],
) -> None:
    """The false positive that WAS the whole of this document's output.

    `remit_address`'s old anchor was the bare brand name with
    `anchor_occurrence: "last"`, and the last bare "Windstream" on an
    Enterprise page 1 is inside a sentence of portal boilerplate. The real
    label is "Remit Payment To:", which the fixture places 356pt higher.
    """
    assert enterprise["remit_address"] == (
        "Windstream\nP.O. Box 9001013\nLouisville, KY 40290-1013"
    )


def test_enterprise_populates_most_of_the_contract_not_one_field(
    enterprise: dict[str, Any],
) -> None:
    """The finding as originally reported: "1 of ~12 fields, and that one
    garbled". A per-field test could be satisfied by twelve separate
    coincidences; this asserts the shape of the outcome directly.
    """
    assert len(enterprise) >= 8


# ---------------------------------------------------------------------------
# Who sent it. Review finding: an otherwise-correct record naming the wrong
# sub-brand.
# ---------------------------------------------------------------------------


def test_enterprise_vendor_name_is_the_brand_the_page_prints(
    enterprise: dict[str, Any],
) -> None:
    """Making these documents extract at all is what made this worth fixing.

    `windstream.json` had no `vendor_name` selector, so `resolve_vendor_alias`
    fell through to the pack's `DISPLAY_NAMES["windstream"]` and every Windstream
    record reported "Kinetic Business by Windstream". On a Kinetic bill that is
    right and is the reason the table entry exists - `aliases.py` documents it:
    the Kinetic text layer breaks the brand mid-word (`Kinetic Business by
    Windstre am`), so no pattern can read it. On an ENTERPRISE bill it is a
    confidently wrong brand on a document letterheaded WINDSTREAM ENTERPRISE and
    remitting to a different PO box - and it is wrong for no good reason, because
    here the brand IS readable.

    Before the fix these documents produced nothing, so nothing was wrong with
    them. Afterwards they produce eight correct fields, which is exactly what
    makes one wrong one worth catching.
    """
    assert enterprise["vendor_name"] == "Windstream Enterprise"


def test_enterprise_vendor_name_survives_to_the_record(
    enterprise_identity: dict[str, Any],
) -> None:
    """The selector capturing it is necessary but not sufficient.

    `resolve_vendor_alias` overwrites `vendor_name` from the display-name table
    only `if ... letterhead is None`. So the assertion that matters is that the
    printed capture reaches the record unclobbered - which is the op's own stated
    principle ("printed evidence wins where it exists ... the table is for where
    the print is unreadable"), now actually exercised on a document where the two
    disagree.
    """
    assert enterprise_identity["vendor_name"] == "Windstream Enterprise"


def test_enterprise_still_collapses_onto_the_one_windstream_persona(
    enterprise_identity: dict[str, Any],
) -> None:
    """F5, which reading a second brand name must not undo.

    Two sub-brands, two remittance addresses, two layouts - one carrier, one
    canonical key, one persona. If "Windstream Enterprise" resolved to its own
    canonical, this fix would have traded a wrong display name for a split
    vendor, which is worse: `carrier_canonical` is asserted by every gold label
    in this pack.
    """
    assert enterprise_identity["vendor_canonical"] == "windstream"
    assert enterprise_identity["carrier_canonical"] == "windstream"
    # Resolved from the name the page printed, not by scanning page text for any
    # token that happens to look like the brand.
    assert enterprise_identity["vendor_basis"] == "letterhead_alias"


def test_kinetic_vendor_name_still_comes_from_the_display_name_table(
    kinetic_identity: dict[str, Any],
) -> None:
    """The other half: the table entry is still load-bearing where it was.

    The Kinetic fixture prints "ATTN: SUPPORT SERVICES" - the same anchor the
    Enterprise selector uses, with no brand beside it - so the anchor RESOLVES
    here and the pattern finds nothing. That is the case most likely to break:
    an anchor that hits on the wrong template and captures whatever is next to
    it. Nothing is captured, `letterhead` stays None, and the table supplies the
    Kinetic name exactly as before.
    """
    assert kinetic_identity["vendor_name"] == "Kinetic Business by Windstream"
    assert kinetic_identity["vendor_canonical"] == "windstream"
    assert kinetic_identity["vendor_basis"] == "page_text_alias"


def test_no_vendor_name_is_captured_off_a_kinetic_page(kinetic: dict[str, Any]) -> None:
    """Stated at the selector level too, so a failure localizes: if this passes
    and the test above fails, the regression is in the op; if this fails, the
    Enterprise pattern has started matching Kinetic text."""
    assert "vendor_name" not in kinetic


# ---------------------------------------------------------------------------
# The Kinetic template must be untouched.
# ---------------------------------------------------------------------------


def test_kinetic_template_still_extracts_every_field_it_did_before(
    kinetic: dict[str, Any],
) -> None:
    """The gold document's own layout, through the same shipped selectors.

    If any Enterprise alt were reachable here it would have to beat a primary
    anchor that resolves, which `_resolve_anchor` never lets it do - but the
    only way to know the alts did not perturb these values is to read them.
    """
    assert kinetic["account_number"] == "041069076"
    assert kinetic["telephone_number"] == "918-653-3103"
    assert kinetic["bill_date"].iso == "2025-07-22"
    assert kinetic["due_date"].iso == "2025-08-11"
    assert str(kinetic["prior_balance"]) == "1231.74"
    assert str(kinetic["payments_credits"]) == "-1231.74"
    assert str(kinetic["amount_previously_due"]) == "0.00"
    assert str(kinetic["current_charges"]) == "1230.14"
    assert str(kinetic["total_printed"]) == "1230.14"


def test_kinetic_remit_address_still_resolves_through_the_brand_name_alt(
    kinetic: dict[str, Any],
) -> None:
    """`remit_address`'s anchor and alt were swapped, so this is the assertion
    that the demotion cost the Kinetic template nothing: no Kinetic bill
    carries "Remit Payment To", the primary therefore misses, and the
    `WINDSTREAM` alt resolves exactly as the un-swapped anchor used to.
    """
    assert kinetic["remit_address"] == "PO BOX 9001908\nLOUISVILLE, KY 40290-1908"


def test_kinetic_remit_payee_still_reads_the_state_operating_entity(
    kinetic: dict[str, Any],
) -> None:
    """F5's assertion, on the fixture: "check payable to" is Kinetic-only
    wording, and nothing added for the Enterprise template may shadow it."""
    assert kinetic["remit_payee"] == "OKLAHOMA WINDSTREAM, LLC"


# ---------------------------------------------------------------------------
# The invariant the whole `anchor_alts` approach rests on.
# ---------------------------------------------------------------------------


def test_the_two_templates_label_vocabularies_are_disjoint() -> None:
    """Why one persona can carry both templates without a discriminator.

    `_resolve_anchor` walks a selector's phrases in declaration order and takes
    the FIRST that resolves, so which template a selector reads is decided
    entirely by which of its phrases the page happens to print. That is only
    unambiguous while no page prints two of them. Stated without reference to
    which side is primary - because `remit_address` is ordered the other way
    round, and a test that hardcoded "primary means Kinetic" would go stale the
    moment a second selector was inverted:

        for every selector, at most ONE of its anchor phrases occurs on any
        one page.

    Hold that, and declaration order stops mattering: there is never a second
    phrase for an earlier position in the list to shadow. Break it - by adding
    a phrase to either side that the other template also prints - and this
    fails loudly instead of silently changing which anchor wins.

    The brand name is the one phrase both templates carry, so it is excluded
    and asserted separately. It is excluded from the invariant, not from
    scrutiny: being on both pages is exactly why it cannot be a primary anchor,
    and `test_enterprise_remit_address_is_the_remittance_block_not_a_prose_sentence`
    is what holds that end.
    """
    persona = parse_persona(_shipped_persona())
    pages = {"Enterprise": _page(ENTERPRISE_LINES), "Kinetic": _page(KINETIC_LINES)}

    def occurs(page: PageText, phrase: str) -> bool:
        needle = _norm(phrase)
        return any(_runs(line, needle) for line in page.lines())

    brand = _norm("WINDSTREAM")
    checked = 0
    for selector in persona.field_selectors:
        anchor = getattr(selector, "anchor", None)
        if anchor is None:
            continue
        phrases = [anchor, *getattr(selector, "anchor_alts", ())]
        discriminating = [p for p in phrases if _norm(p) != brand]
        checked += len(discriminating)
        for template, page in pages.items():
            present = [p for p in discriminating if occurs(page, p)]
            assert len(present) <= 1, (
                f"{selector.field}: the {template} page prints {len(present)} of this "
                f"selector's anchor phrases ({present}). Declaration order now decides "
                "which template it reads, so one of the two is unreachable."
            )

    # The brand name is on both pages - the premise of `remit_address`'s
    # inverted ordering. If this ever stops being true, that inversion is
    # unnecessary and should be reconsidered rather than left as folklore.
    assert all(occurs(page, "WINDSTREAM") for page in pages.values())

    assert checked >= 14, f"only {checked} phrases checked - the persona lost its alts"
