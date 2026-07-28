"""Digital Direction's reference hits (F11) — the opposite shape to Northstar's.

The pack spec's §1 table states why: Northstar's match key is *buried in free
text*, Digital Direction's is *the account / circuit number, printed plainly*. So
this module promotes already-extracted identity fields into `reference_list` with
provenance, rather than scanning text for hidden keys.
"""

from __future__ import annotations

from docintel.core.models import PageMeta, PageText, Word, new_context
from docintel.packs.digitaldirection.references import collect


def _ctx(**fields):
    page = PageText(
        page_number=1,
        words=(Word(text="x", x0=10.0, y0=10.0, x1=20.0, y1=20.0),),
        width=612.0, height=792.0, source="native",
    )
    ctx = new_context("d", "/x.pdf")
    ctx.pages = (page,)
    ctx.page_meta = (PageMeta(1, 10, 0, 0, "primary"),)
    for name, value in fields.items():
        ctx.extracted.set(name, value, 1.0)
    return ctx


def _values(ctx):
    return [h.value for h in ctx.reference_list]


def test_the_account_number_becomes_a_reference_hit() -> None:
    ctx = collect(_ctx(account_number="041069076"))
    assert _values(ctx) == ["041069076"]


def test_the_JOINABLE_form_of_an_account_wins() -> None:
    """F6, and the reason this module promotes a field rather than scanning text.

    Comcast prints `8495 44 462 0365242` and its gold reference hit is
    `8495444620365242`. A reference hit exists to be joined on, so the printed
    spacing would make it useless.
    """
    ctx = collect(_ctx(
        account_number="8495 44 462 0365242",
        account_number_normalized="8495444620365242",
    ))
    assert _values(ctx) == ["8495444620365242"]


def test_an_invoice_number_is_promoted_too() -> None:
    """Lumen is the only carrier in the pack that prints one."""
    ctx = collect(_ctx(invoice_number="752233001", account_number="5-QXH7QKM7"))
    assert set(_values(ctx)) == {"752233001", "5-QXH7QKM7"}


def test_the_circuit_id_and_telephone_number_are_promoted() -> None:
    ctx = collect(_ctx(circuit_id="4351003276", telephone_number="918-653-3103"))
    assert set(_values(ctx)) == {"4351003276", "918-653-3103"}


def test_every_hit_carries_provenance() -> None:
    """A bare list of digit runs is indistinguishable from a list of zip+4
    fragments; a downstream matcher needs to know what it is looking at."""
    ctx = collect(_ctx(account_number="041069076"))
    (hit,) = ctx.reference_list
    assert hit.pattern_id == "account"
    assert hit.source_field == "Account Number"
    assert hit.page == 1


def test_collect_is_idempotent() -> None:
    """It runs at a hook socket, and a hook that duplicated its own output would
    make `reference_list` grow on every retry."""
    ctx = collect(_ctx(account_number="041069076"))
    ctx = collect(ctx)
    assert _values(ctx) == ["041069076"]


def test_an_account_number_object_contributes_its_printed_form() -> None:
    """A persona using the `account_number` PATTERN yields an object, not a string."""
    from docintel.grammar.patterns import NAMED

    ctx = collect(_ctx(account_number=NAMED["account_number"]("5-QXH7QKM7")))
    assert _values(ctx) == ["5-QXH7QKM7"]


def test_nothing_extracted_yields_no_hits() -> None:
    assert _values(collect(_ctx())) == []
