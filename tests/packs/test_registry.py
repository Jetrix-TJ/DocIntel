"""The pack protocol, the loader, and the claiming rule."""

from __future__ import annotations

from docintel.core.models import PageMeta, PageText, Word, new_context
from docintel.grammar.schema import Pack as GrammarPack
from docintel.packs.registry import Pack, load_packs, register_all, resolve_pack
from docintel.pipeline.hooks import SOCKETS, HookRegistry


def _page(*texts: str, number: int = 1) -> PageText:
    """`number` is a real parameter, not a default to be ignored: an earlier draft
    hardcoded page 1, so a two-page fixture was two copies of page 1 and the
    supporting-page test passed for the wrong reason."""
    words = tuple(
        Word(text=t, x0=10.0 + 70.0 * i, y0=100.0, x1=60.0 + 70.0 * i, y1=110.0)
        for i, t in enumerate(texts)
    )
    return PageText(
        page_number=number, words=words, width=612.0, height=792.0, source="native"
    )


def _ctx(*texts: str):
    ctx = new_context("d", "/x.pdf")
    ctx.pages = (_page(*texts),)
    ctx.page_meta = (PageMeta(1, 100, 0, 0, "primary"),)
    return ctx


def test_load_packs_returns_packs() -> None:
    assert load_packs()


def test_every_pack_satisfies_the_registry_protocol() -> None:
    for pack in load_packs():
        assert isinstance(pack, Pack)


def test_every_pack_also_satisfies_the_grammar_protocol() -> None:
    """This is what makes "every shipped persona passes V1-V13" testable rather
    than aspirational: the pack object can be handed straight to the validator."""
    for pack in load_packs():
        assert isinstance(pack, GrammarPack)


def test_a_pack_claims_a_document_billed_to_its_organization() -> None:
    ctx = _ctx("Bill", "To", "Northstar", "Recycling", "Company,", "LLC")
    pack = resolve_pack(ctx)
    assert pack is not None and pack.name == "northstar"


def test_a_pack_claims_on_the_po_box_alone() -> None:
    """EDCO's remittance stub prints the PO Box without the company name."""
    ctx = _ctx("PO", "BOX", "188", "EAST", "LONGMEADOW", "MA", "01028")
    assert resolve_pack(ctx) is not None


def test_no_pack_claims_someone_elses_invoice() -> None:
    """None is a real answer. Forcing it into whichever pack is first would
    process an invoice that is not ours as though it were."""
    ctx = _ctx("Bill", "To", "Acme", "Widgets", "Incorporated")
    assert resolve_pack(ctx) is None


def test_claiming_reads_only_primary_pages() -> None:
    """A supporting page may name a different company entirely (F10)."""
    ctx = new_context("d", "/x.pdf")
    ctx.pages = (_page("Acme", "Widgets"), _page("Northstar", "Recycling", number=2))
    ctx.page_meta = (PageMeta(1, 100, 0, 0, "primary"), PageMeta(2, 100, 0, 0, "supporting"))
    assert resolve_pack(ctx) is None


def test_register_all_registers_into_real_sockets() -> None:
    registry = HookRegistry()
    register_all(registry)
    registered = {s: registry.registered(s) for s in SOCKETS}
    assert registered["classifySignals"], "a pack with no ladder cannot classify"
    assert registered["beforePersonaLookup"], "no fingerprint means no persona lookup"
    assert registered["afterExtraction"]


def _selector_adjust_ops(selector: object) -> tuple[str, ...]:
    """Every op named in one selector's `adjust`, whichever shape it took.

    Section 1.1 allows `adjust` as a bare string or a list, and a `row_group`
    selector may carry its own `adjust` alongside a plain field selector's
    (`grammar.validator._check_adjust` is called for both) - so this reads
    `adjust` off whatever mapping it is handed rather than assuming the
    selector is a scalar field.
    """
    if not isinstance(selector, dict):
        return ()
    raw = selector.get("adjust")
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,)
    return tuple(raw)


def _pack_derives_amount_payable(pack: Pack) -> bool:
    """Does any persona this pack ships still call `derive_amount_payable`?

    Walks every selector in every persona - not just plain field selectors,
    since a `row_group` selector is a sibling entry in the same
    `field_selectors` list and may carry its own `adjust`.
    """
    return any(
        "derive_amount_payable" in _selector_adjust_ops(selector)
        for persona in pack.personas()
        for selector in persona["field_selectors"]
    )


def test_pack_thresholds_cover_the_fields_that_decide_payment() -> None:
    """Asserts the INVARIANT, not either pack's numbers.

    The two packs deliberately differ - Northstar holds `total_printed` at 0.95
    while Digital Direction holds it at 0.93 because a scan line corroborates it
    on all four of its bills. Where a pack still derives `amount_payable`, that
    DERIVED payable must be held to at least the bar of the printed total it
    came from, and both bars must be high, because a wrong total is a wrong
    payment.

    The guard is keyed on **whether the pack's personas still call
    `derive_amount_payable`**, not on whether `thresholds` happens to have the
    key. Keying it on the dict under test would make the dict self-certifying -
    deleting `"amount_payable"` from a pack that still derives it would silence
    this check instead of failing it.

    As of Task 11, every persona in both packs calls `derive_amount_payable`
    again, so the invariant is live for both - not dormant. It was written to
    reactivate automatically the moment any persona reinstated the op, without
    anyone having to remember to re-enable it, and that is exactly what
    happened: both packs are now held to the full rule, including the "the key
    must exist at all" half.
    """
    for pack in load_packs():
        t = pack.thresholds
        assert t["total_printed"] >= 0.90, pack.name
        if _pack_derives_amount_payable(pack):
            assert "amount_payable" in t, pack.name
            assert t["amount_payable"] >= 0.95, pack.name
            assert t["amount_payable"] >= t["total_printed"], pack.name


def test_no_pack_registers_an_adjust_op_of_its_own() -> None:
    """Not a rule, an observation worth pinning: every transformation the corpus
    needs is already in the grammar's closed enum, so no pack has had to grow it."""
    for pack in load_packs():
        assert pack.adjust_ops() == frozenset()
