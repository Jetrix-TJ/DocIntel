"""Inference ops (section 4.4).

Both ops record *how* they answered. That is what makes an inferred value usable
at all, so `currency_basis` / `vendor_basis` are asserted alongside every value.
"""

from __future__ import annotations

from docintel.core.models import PageMeta, PageText, Word, new_context
from docintel.grammar.ops.infer import (
    infer_currency,
    resolve_bill_to_alias,
    resolve_vendor_alias,
)


def _page(number: int, *texts: str, y: float = 100.0) -> PageText:
    words = tuple(
        Word(text=t, x0=10.0 + 70.0 * i, y0=y, x1=60.0 + 70.0 * i, y1=y + 10.0)
        for i, t in enumerate(texts)
    )
    return PageText(page_number=number, words=words, width=612.0, height=792.0, source="native")


def _ctx(*pages: PageText, roles: tuple[str, ...] | None = None, **fields):
    ctx = new_context("d", "/x.pdf")
    ctx.pages = pages
    ctx.page_meta = tuple(
        PageMeta(p.page_number, 100, 0, 0, roles[i] if roles else "primary")
        for i, p in enumerate(pages)
    )
    for name, value in fields.items():
        ctx.extracted.set(name, value, 1.0)
    return ctx


class _Pack:
    default_currency = "USD"
    vendor_aliases = {"edco waste & recycling service": "EDCO Disposal Corporation"}


class _Persona:
    pack = _Pack()


# --------------------------------------------------------------------------
# infer_currency - the F14 ladder
# --------------------------------------------------------------------------


def test_an_extracted_iso_code_is_the_strongest_rung() -> None:
    """The basis strings are the GOLD LABELS' own vocabulary, not a fresh
    invention: all ten gold files record a currency_basis using
    `explicit_iso_code`, `tax_regime_marker` and `pack_default`. Naming the rungs
    anything else would make the field unassertable, so the scorecard would
    silently stop measuring the F14 ladder it exists to check."""
    ctx = _ctx(_page(1, "anything"), currency="CAD")
    ctx = infer_currency(ctx)
    assert ctx.derived.get("currency") == "CAD"
    assert ctx.derived.get("currency_basis") == "explicit_iso_code"
    assert "currency_inferred_weak" not in ctx.modifiers


def test_a_lowercase_iso_code_is_normalized() -> None:
    ctx = _ctx(_page(1, "x"), currency="usd")
    ctx = infer_currency(ctx)
    assert ctx.derived.get("currency") == "USD"


def test_an_hst_line_infers_cad_with_no_penalty() -> None:
    """U-PAK, the only non-USD document in the corpus. Its H.S.T. line is a
    statement about jurisdiction, so this rung is a reading, not a guess."""
    ctx = _ctx(_page(1, "H.S.T.", "#", "123142812RT0001", "2,325.69"))
    ctx = infer_currency(ctx)
    assert ctx.derived.get("currency") == "CAD"
    assert ctx.derived.get("currency_basis") == "tax_regime_marker"
    assert "currency_inferred_weak" not in ctx.modifiers


def test_gst_and_qst_also_infer_cad() -> None:
    for marker in ("G.S.T.", "GST", "Q.S.T."):
        ctx = _ctx(_page(1, marker, "148.20"))
        ctx = infer_currency(ctx)
        assert ctx.derived.get("currency") == "CAD", marker


def test_vat_is_deliberately_not_a_currency_signal() -> None:
    """VAT spans the UK and the whole euro area, so it narrows the currency to
    "one of several". Inferring either would be a guess wearing a basis."""
    ctx = _ctx(_page(1, "VAT", "Registration", "GB123456789"))
    ctx = infer_currency(ctx)
    assert ctx.derived.get("currency") is None


def test_a_canadian_postal_code_is_a_weak_signal() -> None:
    ctx = _ctx(_page(1, "Guelph", "ON", "N1G", "4N4"))
    ctx = infer_currency(ctx)
    assert ctx.derived.get("currency") == "CAD"
    assert ctx.derived.get("currency_basis") == "vendor_address"
    assert "currency_inferred_weak" in ctx.modifiers


def test_a_tax_regime_outranks_an_address() -> None:
    ctx = _ctx(_page(1, "H.S.T.", "148.20"), _page(2, "Ohio", "45887"))
    ctx = infer_currency(ctx)
    assert ctx.derived.get("currency_basis") == "tax_regime_marker"


def test_a_supporting_page_does_not_decide_the_currency() -> None:
    """Section 7 applied to inference: a supporting Bill of Lading may mention a
    tax regime that has nothing to do with how this invoice is denominated."""
    ctx = _ctx(
        _page(1, "Invoice", "Total", "1,177.70"),
        _page(2, "H.S.T.", "on", "the", "attached", "BOL"),
        roles=("primary", "supporting"),
    )
    ctx = infer_currency(ctx)
    assert ctx.derived.get("currency") is None


def test_the_pack_default_is_the_last_rung_and_is_weak() -> None:
    ctx = _ctx(_page(1, "Invoice", "699.00"))
    ctx.persona = _Persona()
    ctx = infer_currency(ctx)
    assert ctx.derived.get("currency") == "USD"
    assert ctx.derived.get("currency_basis") == "pack_default"
    assert "currency_inferred_weak" in ctx.modifiers


def test_without_a_pack_nine_of_ten_documents_resolve_to_nothing() -> None:
    """And that is correct, not a gap. "Most invoices are USD" is a PACK POLICY,
    not something the document says - so the rung that supplies it arrives with
    the packs in C5, and until then the honest answer is no answer."""
    ctx = _ctx(_page(1, "Invoice", "Total", "699.00"))
    ctx = infer_currency(ctx)
    assert ctx.derived.get("currency") is None
    assert ctx.derived.get("currency_basis") is None


# --------------------------------------------------------------------------
# resolve_vendor_alias - F5
# --------------------------------------------------------------------------


def test_the_remittance_payee_beats_the_letterhead() -> None:
    """F5: the money goes where the remittance block says, not where the logo says."""
    ctx = _ctx(_page(1, "x"), vendor_name="Lumen", remit_payee="CenturyLink Communications")
    ctx = resolve_vendor_alias(ctx)
    assert ctx.derived.get("vendor_canonical") == "CenturyLink Communications"
    assert ctx.derived.get("vendor_basis") == "remit_payee"


def test_a_letterhead_only_document_uses_the_letterhead() -> None:
    ctx = _ctx(_page(1, "x"), vendor_name="D.T.S.S. Inc.")
    ctx = resolve_vendor_alias(ctx)
    assert ctx.derived.get("vendor_canonical") == "D.T.S.S. Inc."
    assert ctx.derived.get("vendor_basis") == "letterhead"


def test_a_mismatch_between_payee_and_letterhead_is_logged() -> None:
    """Auditable rather than invisible: two of the corpus senders bill under a
    different brand than they print."""
    ctx = _ctx(_page(1, "x"), vendor_name="Lumen", remit_payee="CenturyLink")
    ctx = resolve_vendor_alias(ctx)
    assert any("differs from letterhead" in e for e in ctx.events)


def test_agreement_is_not_logged_as_a_mismatch() -> None:
    ctx = _ctx(_page(1, "x"), vendor_name="Veritiv", remit_payee="Veritiv")
    ctx = resolve_vendor_alias(ctx)
    assert not any("differs from letterhead" in e for e in ctx.events)


def test_a_pack_alias_table_outranks_both() -> None:
    ctx = _ctx(_page(1, "x"), vendor_name="EDCO Waste & Recycling Service")
    ctx.persona = _Persona()
    ctx = resolve_vendor_alias(ctx)
    assert ctx.derived.get("vendor_canonical") == "EDCO Disposal Corporation"
    assert ctx.derived.get("vendor_basis") == "letterhead_alias"


def test_alias_lookup_is_case_and_whitespace_insensitive() -> None:
    ctx = _ctx(_page(1, "x"), vendor_name="  edco   WASTE & recycling   service  ")
    ctx.persona = _Persona()
    ctx = resolve_vendor_alias(ctx)
    assert ctx.derived.get("vendor_canonical") == "EDCO Disposal Corporation"


def test_no_vendor_at_all_records_nothing() -> None:
    ctx = _ctx(_page(1, "x"))
    ctx = resolve_vendor_alias(ctx)
    assert ctx.derived.get("vendor_canonical") is None


# --------------------------------------------------------------------------
# The page-text rung and the display-name table (unit 2)
# --------------------------------------------------------------------------


class _CarrierPack:
    default_currency = "USD"
    vendor_aliases = {
        "lumen": "lumen",
        "level 3 communications, llc": "lumen",
        "kinetic business": "windstream",
        "windstream": "windstream",
    }
    display_names = {
        "lumen": "Lumen",
        "windstream": "Kinetic Business by Windstream",
    }


def _pack_ctx(*pages, **fields):
    ctx = _ctx(*pages, **fields)
    ctx.pack = _CarrierPack()
    return ctx


def test_a_canonical_key_is_found_in_page_text_when_no_field_was_extracted() -> None:
    """Lumen's letterhead is an IMAGE - the token appears zero times in the text
    layer, so no selector can capture it. The alias table still matches the one
    place the brand IS written."""
    ctx = _pack_ctx(_page(1, "How", "to", "reach", "Lumen:", "1-877-453-8353"))
    ctx = resolve_vendor_alias(ctx)
    assert ctx.derived.get("vendor_canonical") == "lumen"
    assert ctx.derived.get("vendor_basis") == "page_text_alias"


def test_carrier_canonical_is_emitted_under_the_pack_specs_name() -> None:
    """One fact, two names. Every Digital Direction gold label asserts it as
    `carrier_canonical`."""
    ctx = _pack_ctx(_page(1, "How", "to", "reach", "Lumen:"))
    ctx = resolve_vendor_alias(ctx)
    assert ctx.derived.get("carrier_canonical") == ctx.derived.get("vendor_canonical")


def test_the_display_table_supplies_a_vendor_name_the_page_cannot() -> None:
    """Windstream's text layer breaks the brand mid-word: `Kinetic Business by
    Windstre am`. No pattern yields the real name, but `kinetic business` still
    resolves the canonical key."""
    ctx = _pack_ctx(_page(1, "Please", "call", "Kinetic", "Business", "by", "Windstre", "am"))
    ctx = resolve_vendor_alias(ctx)
    assert ctx.derived.get("vendor_canonical") == "windstream"
    assert ctx.derived.get("vendor_name") == "Kinetic Business by Windstream"


def test_a_printed_vendor_name_is_never_overwritten_by_the_table() -> None:
    """F5's principle: printed evidence wins where it exists. The table is for
    where the print is unreadable, not for normalizing what was read."""
    ctx = _pack_ctx(_page(1, "How", "to", "reach", "Lumen:"), vendor_name="LUMEN TECHNOLOGIES")
    ctx = resolve_vendor_alias(ctx)
    assert ctx.derived.get("vendor_name") is None
    assert ctx.extracted.get("vendor_name") == "LUMEN TECHNOLOGIES"


def test_the_longest_alias_match_wins() -> None:
    """`level 3 communications, llc` is more specific than a bare brand token."""
    ctx = _pack_ctx(_page(1, "Invoice", "of", "Level", "3", "Communications,", "LLC"))
    ctx = resolve_vendor_alias(ctx)
    assert ctx.derived.get("vendor_canonical") == "lumen"


def test_an_extracted_payee_still_outranks_page_text() -> None:
    ctx = _pack_ctx(
        _page(1, "How", "to", "reach", "Lumen:"),
        remit_payee="Level 3 Communications, LLC",
    )
    ctx = resolve_vendor_alias(ctx)
    assert ctx.derived.get("vendor_basis") == "remit_payee_alias"


def test_an_unrecognized_vendor_printing_two_names_is_logged() -> None:
    """The case that most needs to be visible: it is a new alias-table entry
    waiting to be written."""
    ctx = _ctx(_page(1, "x"), vendor_name="Acme Widgets", remit_payee="Acme Holdings LLC")
    ctx = resolve_vendor_alias(ctx)
    assert any("differs from letterhead" in e for e in ctx.events)


def test_no_pack_and_no_names_records_nothing() -> None:
    ctx = _ctx(_page(1, "x"))
    ctx = resolve_vendor_alias(ctx)
    assert ctx.derived.get("vendor_canonical") is None


# --------------------------------------------------------------------------
# resolve_bill_to_alias - the bill-to party, when the page prints no label
# --------------------------------------------------------------------------
#
# The same shape as resolve_vendor_alias and for the same reason. Two of the four
# telecom templates print their bill-to with no label at all, so no anchor exists
# to hang a selector on - which is exactly why those personas had the client's name
# hardcoded as the pattern. A pack-level roster moves that string out of the
# per-document rule and into the pack's business registry, where one entry serves
# every carrier and every billing period.
#
# The op returns the name AS PRINTED rather than a canonical display form, because
# each vendor renders the same party differently - `Northstar Recycling`,
# `Northstar Recycling Company LLC` and `NorthStar Recycling Company, LLC` are all
# the same AP department, and each gold label asserts its own document's rendering.


class _RosterPack:
    default_currency = "USD"
    bill_to_roster = (
        "Northstar Recycling Company, LLC",
        "Northstar Recycling",
        "Choctaw Travel Mart",
    )


def test_the_roster_reads_the_bill_to_off_the_page() -> None:
    ctx = _ctx(_page(1, "Choctaw", "Travel", "Mart", "PO", "BOX", "1550"))
    ctx.pack = _RosterPack()

    resolve_bill_to_alias(ctx)

    assert ctx.derived.get("bill_to_name") == "Choctaw Travel Mart"
    assert ctx.derived.get("bill_to_basis") == "roster_page_text"


def test_the_printed_rendering_is_preserved_not_the_roster_spelling() -> None:
    """Each vendor prints the same party its own way and every gold label asserts
    the rendering on its own document, so canonicalising here would break them."""
    ctx = _ctx(_page(1, "NORTHSTAR", "RECYCLING", "invoice"))
    ctx.pack = _RosterPack()

    resolve_bill_to_alias(ctx)

    assert ctx.derived.get("bill_to_name") == "NORTHSTAR RECYCLING"


def test_the_longest_roster_match_wins() -> None:
    """`Northstar Recycling` is a prefix of `Northstar Recycling Company, LLC`.
    Taking the shorter match would silently truncate the party on every vendor
    that prints the full legal name."""
    ctx = _ctx(_page(1, "Northstar", "Recycling", "Company,", "LLC"))
    ctx.pack = _RosterPack()

    resolve_bill_to_alias(ctx)

    assert ctx.derived.get("bill_to_name") == "Northstar Recycling Company, LLC"


def test_a_printed_selector_value_outranks_the_roster() -> None:
    """F5's principle: printed evidence wins where it exists. A persona that can
    anchor on a real label must not have its answer replaced by a table."""
    ctx = _ctx(_page(1, "Northstar", "Recycling"), bill_to_name="City of Dublin")
    ctx.pack = _RosterPack()

    resolve_bill_to_alias(ctx)

    assert ctx.extracted.get("bill_to_name") == "City of Dublin"
    assert ctx.derived.get("bill_to_name") is None
    assert ctx.derived.get("bill_to_basis") == "printed"


def test_an_unknown_party_is_left_empty_rather_than_guessed() -> None:
    """The onboarding case. An empty required field is escalated by
    `core.coverage`, which is the correct outcome - somebody has to add the new
    client. Inventing a value here would put a wrong party on a payment."""
    ctx = _ctx(_page(1, "Ridgeline", "Freight", "Holdings"))
    ctx.pack = _RosterPack()

    resolve_bill_to_alias(ctx)

    assert ctx.derived.get("bill_to_name") is None
    assert ctx.derived.get("bill_to_basis") is None


def test_a_supporting_page_cannot_supply_the_bill_to() -> None:
    """Section 7. A Bill of Lading naming the AP department says nothing about who
    this invoice is addressed to."""
    ctx = _ctx(
        _page(1, "no", "party", "here"),
        _page(2, "Northstar", "Recycling"),
        roles=("primary", "supporting"),
    )
    ctx.pack = _RosterPack()

    resolve_bill_to_alias(ctx)

    assert ctx.derived.get("bill_to_name") is None


def test_a_pack_with_no_roster_is_unaffected() -> None:
    ctx = _ctx(_page(1, "Northstar", "Recycling"))
    ctx.pack = _Pack()

    resolve_bill_to_alias(ctx)

    assert ctx.derived.get("bill_to_name") is None


def _block_page(number: int, rows: list[list[tuple[str, float]]], top: float = 100.0):
    """A page whose rows are (text, x0) pairs, one visual line per row."""
    words = []
    for r, row in enumerate(rows):
        y = top + 12.0 * r
        for text, x0 in row:
            words.append(Word(text=text, x0=x0, y0=y, x1=x0 + 6.0 * len(text), y1=y + 9.0))
    return PageText(
        number, tuple(words), width=612.0, height=792.0, source="native"
    )


def test_the_roster_also_reads_the_address_block_under_the_party() -> None:
    """`bill_to_address` is always the block beneath `bill_to_name`, and with the
    party located by the roster no selector can anchor on it - so the op that
    already knows where the name is takes the lines under it."""
    page = _block_page(1, [
        [("Northstar", 40.0), ("Recycling", 100.0), ("EDCO", 400.0), ("WASTE", 440.0)],
        [("PO", 40.0), ("BOX", 60.0), ("188", 85.0), ("P.O.", 400.0), ("BOX", 430.0)],
        # `MA` sits close to `LONGMEADOW`: a real address line has no gutter inside
        # it, and a 24pt hole would legitimately read as the next column.
        [("EAST", 40.0), ("LONGMEADOW", 75.0), ("MA", 140.0), ("BUENA", 400.0)],
    ])
    ctx = _ctx(page)
    ctx.pack = _RosterPack()

    resolve_bill_to_alias(ctx)

    assert ctx.derived.get("bill_to_name") == "Northstar Recycling"
    assert ctx.derived.get("bill_to_address") == "PO BOX 188, EAST LONGMEADOW MA"


def test_the_address_block_stops_at_the_column_gutter() -> None:
    """The neighbouring column is contamination, not continuation. Both packs'
    bill-to blocks sit beside the vendor's own remittance address."""
    ctx = _ctx(_block_page(1, [
        [("Choctaw", 40.0), ("Travel", 90.0), ("Mart", 130.0), ("VENDOR", 400.0)],
        [("PO", 40.0), ("BOX", 60.0), ("1550", 85.0), ("OTHER", 400.0)],
    ]))
    ctx.pack = _RosterPack()

    resolve_bill_to_alias(ctx)

    assert ctx.derived.get("bill_to_address") == "PO BOX 1550"


def test_an_extracted_address_is_not_overwritten_by_the_block() -> None:
    """Printed evidence wins, exactly as it does for the party name itself."""
    ctx = _ctx(
        _block_page(1, [[("Northstar", 40.0), ("Recycling", 100.0)],
                        [("PO", 40.0), ("BOX", 60.0), ("188", 85.0)]]),
        bill_to_address="94 Maple St, East Longmeadow, MA",
    )
    ctx.pack = _RosterPack()

    resolve_bill_to_alias(ctx)

    assert ctx.derived.get("bill_to_address") is None


def test_no_address_block_is_invented_when_the_party_is_the_last_line() -> None:
    ctx = _ctx(_block_page(1, [[("Northstar", 40.0), ("Recycling", 100.0)]]))
    ctx.pack = _RosterPack()

    resolve_bill_to_alias(ctx)

    assert ctx.derived.get("bill_to_name") == "Northstar Recycling"
    assert ctx.derived.get("bill_to_address") is None


def test_the_block_prefers_a_party_that_begins_its_own_line() -> None:
    """A party name printed mid-line is a mention, not the head of an address block.

    Centracom prints `Account Name: CLYDE COMPANIES` in its summary table and the
    same party again at the head of the remittance block. The first is a labelled
    field whose neighbours are `Bill Date:` and `Due Date:`; only the second has an
    address under it. Reading order alone picks the wrong one.
    """
    ctx = _ctx(_block_page(1, [
        [("Account", 40.0), ("Name:", 90.0), ("Choctaw", 140.0), ("Travel", 190.0),
         ("Mart", 230.0)],
        [("Bill", 40.0), ("Date:", 70.0), ("January", 110.0)],
        [("Choctaw", 40.0), ("Travel", 90.0), ("Mart", 130.0)],
        [("PO", 40.0), ("BOX", 60.0), ("1550", 85.0)],
    ]))
    ctx.pack = _RosterPack()

    resolve_bill_to_alias(ctx)

    assert ctx.derived.get("bill_to_address") == "PO BOX 1550"


# --------------------------------------------------------------------------
# resolve_bill_to_alias - the wrong-inbox guard (bill_to_mismatch)
# --------------------------------------------------------------------------
#
# Northstar's `claims` is a substring search over the whole primary page, so an
# invoice billed to a different company that merely MENTIONS Northstar anywhere
# is claimed, extracted in full, and would otherwise route `high`. Only the
# PRINTED rung can disagree with the roster - rung 2 read the name off the
# roster itself, so it can never contradict it. See
# `test_a_roster_supplied_name_is_never_tagged` below for what that means in
# practice: it is a live gap in rung 2, not a guarantee that rung is safe.


def _ctx_with_pack_roster(roster: tuple[str, ...]):
    """A bare context whose pack exposes only `bill_to_roster`.

    No page text is needed: these tests exercise the PRINTED rung, which never
    consults the page, so the roster's page-text rung is deliberately unreachable
    here.
    """

    class _StubPack:
        bill_to_roster = roster

    ctx = new_context("d", "/x.pdf")
    ctx.pack = _StubPack()
    return ctx


def test_a_printed_bill_to_off_the_roster_is_tagged() -> None:
    """The wrong-inbox case. The pack claim is a whole-page substring match, so a
    document that merely MENTIONS the client is claimed; this is what catches it.
    """
    ctx = _ctx_with_pack_roster(("Northstar Recycling Company, LLC",))
    ctx.extracted.set("bill_to_name", "Contoso Manufacturing Inc", 1.0)
    ctx = resolve_bill_to_alias(ctx)
    assert "bill_to_mismatch" in ctx.tags
    assert ctx.derived.get("bill_to_basis") == "printed"


def test_a_roster_party_is_not_tagged() -> None:
    ctx = _ctx_with_pack_roster(("Northstar Recycling Company, LLC",))
    ctx.extracted.set("bill_to_name", "NORTHSTAR RECYCLING COMPANY LLC", 1.0)
    ctx = resolve_bill_to_alias(ctx)
    assert "bill_to_mismatch" not in ctx.tags


def test_a_roster_supplied_name_is_never_tagged() -> None:
    """This pins a LIMITATION, not a guarantee: rung 2 cannot detect a wrong
    inbox at all, because it derives `bill_to_name` from the very roster it
    would need to check the name against - there is no printed value left to
    disagree with the roster once rung 2 has answered.

    `_roster_match` (infer.py:365-386) is a plain `re.search` over the WHOLE
    primary page, with no head-of-line requirement - unlike `_candidate_lines`
    (infer.py:285-307), which states the doctrine it violates: "a party name
    printed mid-line is a mention; at the head of a line it is the top of a
    block." A document billed to one company that merely MENTIONS a roster
    name elsewhere (e.g. "Ship via Northstar Recycling") has that mention
    read as the bill-to party, with no signal raised, because rung 2 never
    runs the mention-vs-block check the printed rung gets for free.

    This is not a corner case: five of the ten corpus personas (`comcast`,
    `windstream`, `edco`, `upak`, `veritiv`) declare no `bill_to_name`
    selector at all, so `printed` is always `None` on their documents and
    every one of them always takes this rung. On any of those five, a
    document billed to the wrong party is claimed, fully extracted, and
    routes `high` with no `bill_to_mismatch` tag.

    The fix - requiring `_roster_match` to land at the head of a line, or to
    have an address block under it like `_block_under` - can change which
    rendering is returned on corpus documents that rely on this rung, so it
    needs a full re-baseline and is Wave 2 work, not this test. The assertion
    below stays exactly as it was; only what it is understood to mean changes.
    """
    ctx = _ctx_with_pack_roster(("Northstar Recycling Company, LLC",))
    ctx = resolve_bill_to_alias(ctx)          # nothing extracted
    assert "bill_to_mismatch" not in ctx.tags
