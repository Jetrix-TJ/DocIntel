"""Inference ops (section 4.4).

Both ops record *how* they answered. That is what makes an inferred value usable
at all, so `currency_basis` / `vendor_basis` are asserted alongside every value.
"""

from __future__ import annotations

from docintel.core.models import PageMeta, PageText, Word, new_context
from docintel.grammar.ops.infer import infer_currency, resolve_vendor_alias


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
