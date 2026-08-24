"""The pack protocol, the loader, and the claiming rule."""

from __future__ import annotations

from digitaldirection import PACK as DIGITALDIRECTION_PACK
from northstar import PACK as NORTHSTAR_PACK

from docintel.core.models import PageMeta, PageText, Word, new_context
from docintel.grammar.schema import Pack as GrammarPack
from docintel.packs.registry import (
    Pack,
    load_basis_overlay,
    load_extra_aliases,
    load_extra_personas,
    load_packs,
    register_all,
    resolve_pack,
)
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


def test_load_packs_returns_an_empty_list_by_default() -> None:
    """docintel ships as a pure framework - `PACK_MODULES`/`PACK_FILES` are
    both empty, so a fresh adopter's `load_packs()` finds nothing until they
    supply their own `extra_packs`. Not `None`, not an error - an empty list,
    the same shape `build_pipeline` always expects to extend."""
    assert load_packs() == []


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
    pack = resolve_pack(ctx, load_packs() + [NORTHSTAR_PACK])
    assert pack is not None and pack.name == "northstar"


def test_a_pack_claims_on_the_po_box_alone() -> None:
    """EDCO's remittance stub prints the PO Box without the company name."""
    ctx = _ctx("PO", "BOX", "188", "EAST", "LONGMEADOW", "MA", "01028")
    assert resolve_pack(ctx, load_packs() + [NORTHSTAR_PACK]) is not None


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
    """No pack ships by default, so this exercises `register_all` against a
    real fixture pack - the mechanism under test is the socket wiring
    itself, not which packs happen to be shipped."""
    hooks = HookRegistry()
    register_all(hooks, packs=[NORTHSTAR_PACK])
    registered = {s: hooks.registered(s) for s in SOCKETS}
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


# ==========================================================================
# `load_basis_overlay` - the reviewer-confirmed prior_balance_basis overlay
# ==========================================================================


def test_a_missing_overlay_file_is_an_empty_dict(tmp_path) -> None:
    """No file yet is the common case (no reviewer has confirmed anything for
    this pack) - it must read as 'nothing known', never raise."""
    assert load_basis_overlay(str(tmp_path)) == {}


def test_an_existing_overlay_file_is_read_fresh(tmp_path) -> None:
    """No caching: a reviewer's just-written decision must be visible on the
    very next call, mirroring `DataPack.personas()`'s own 'read from disk on
    every call' idiom."""
    path = tmp_path / "prior_balance_basis.local.json"
    path.write_text('{"acme-widgets": "gross"}')
    assert load_basis_overlay(str(tmp_path)) == {"acme-widgets": "gross"}

    path.write_text('{"acme-widgets": "gross", "second-vendor": "net_of_payments"}')
    assert load_basis_overlay(str(tmp_path)) == {
        "acme-widgets": "gross",
        "second-vendor": "net_of_payments",
    }


def test_malformed_json_is_treated_as_no_overlay_not_a_crash(tmp_path) -> None:
    """A hand-edited or half-written overlay file must never take down the
    pipeline - it's reviewer-facing runtime state, not validated input."""
    path = tmp_path / "prior_balance_basis.local.json"
    path.write_text("{not valid json")
    assert load_basis_overlay(str(tmp_path)) == {}


def test_a_json_value_that_is_not_an_object_is_treated_as_no_overlay(tmp_path) -> None:
    path = tmp_path / "prior_balance_basis.local.json"
    path.write_text("[1, 2, 3]")
    assert load_basis_overlay(str(tmp_path)) == {}


def test_overlay_values_are_coerced_to_strings(tmp_path) -> None:
    """Defensive: the file is meant to hold only the two F1b basis strings, but
    the reader itself makes no assumption about what's in it beyond 'a dict'."""
    path = tmp_path / "prior_balance_basis.local.json"
    path.write_text('{"acme-widgets": "gross", "123": "net_of_payments"}')
    overlay = load_basis_overlay(str(tmp_path))
    assert overlay == {"acme-widgets": "gross", "123": "net_of_payments"}
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in overlay.items())


def test_the_hardcoded_table_wins_over_the_overlay_for_a_known_vendor(tmp_path, monkeypatch) -> None:
    """The overlay is a strictly lower trust tier - see conventions.py's own
    docstring ('a wrong entry here is a reviewed code change'). Exercised
    directly against the real northstar convention, not a stand-in, so a
    future refactor that reorders the two lookups fails this test."""
    import northstar.conventions as ns_conventions

    overlay_path = tmp_path / "prior_balance_basis.local.json"
    overlay_path.write_text('{"edco": "net_of_payments"}')
    monkeypatch.setattr(ns_conventions, "_PACK_DIR", str(tmp_path))

    ctx = _ctx("EDCO Waste Recycling Service")
    ctx.extracted.set("prior_balance", 298.34, 0.99)
    out = ns_conventions.apply_prior_balance_basis(ctx)
    assert out.extracted.get("prior_balance_basis") == "gross", (
        "edco is in PRIOR_BALANCE_BASIS as 'gross' - the overlay's "
        "'net_of_payments' must lose"
    )


def test_the_overlay_supplies_the_basis_for_a_vendor_the_hardcoded_table_does_not_know(
    tmp_path, monkeypatch
) -> None:
    """The other half of the same precedence: when the hardcoded table has
    nothing for this vendor, the overlay is consulted rather than the F1b
    refusal firing immediately."""
    import northstar.conventions as ns_conventions

    overlay_path = tmp_path / "prior_balance_basis.local.json"
    overlay_path.write_text('{"dtss": "net_of_payments"}')
    monkeypatch.setattr(ns_conventions, "_PACK_DIR", str(tmp_path))

    ctx = _ctx("D T S S Inc")
    ctx.extracted.set("prior_balance", 100.00, 0.99)
    out = ns_conventions.apply_prior_balance_basis(ctx)
    assert out.extracted.get("prior_balance_basis") == "net_of_payments"
    assert "unknown_prior_balance_basis" not in out.tags


def test_a_vendor_in_neither_table_still_tags_unknown_and_sets_no_basis(
    tmp_path, monkeypatch
) -> None:
    import northstar.conventions as ns_conventions

    monkeypatch.setattr(ns_conventions, "_PACK_DIR", str(tmp_path))  # no overlay file at all

    ctx = _ctx("D T S S Inc")
    ctx.extracted.set("prior_balance", 100.00, 0.99)
    out = ns_conventions.apply_prior_balance_basis(ctx)
    assert out.extracted.get("prior_balance_basis") is None
    assert "unknown_prior_balance_basis" in out.tags


def test_the_overlay_mechanism_is_symmetric_on_the_digitaldirection_pack(
    tmp_path, monkeypatch
) -> None:
    """conventions.py is duplicated code, one copy per pack (see both files'
    own docstrings) - a fix or a bug in one does not automatically apply to
    the other, so the overlay fallback needs its own proof here too, not just
    on northstar."""
    import digitaldirection.conventions as dd_conventions

    monkeypatch.delitem(dd_conventions.PRIOR_BALANCE_BASIS, "comcast")
    monkeypatch.setattr(dd_conventions, "_PACK_DIR", str(tmp_path))
    overlay_path = tmp_path / "prior_balance_basis.local.json"
    overlay_path.write_text('{"comcast": "gross"}')

    ctx = _ctx("Comcast Business")
    ctx.extracted.set("prior_balance", 221.11, 0.99)
    out = dd_conventions.apply_prior_balance_basis(ctx)
    assert out.extracted.get("prior_balance_basis") == "gross"
    assert "unknown_prior_balance_basis" not in out.tags


# ==========================================================================
# `load_extra_personas` / `load_extra_aliases` - the external, third-party
# vendor extension point for an ALREADY-REGISTERED shipped pack, generalizing
# `load_basis_overlay`'s own "external, gitignored, read-fresh" discipline to
# personas and alias tables.
# ==========================================================================


def test_extra_personas_is_empty_when_the_env_var_is_unset(monkeypatch) -> None:
    """The common case for every existing caller - zero behavior change."""
    monkeypatch.delenv("DOCINTEL_EXTRA_PERSONAS_DIR", raising=False)
    assert load_extra_personas("digitaldirection") == []


def test_extra_personas_is_empty_when_the_pack_subdirectory_does_not_exist(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DOCINTEL_EXTRA_PERSONAS_DIR", str(tmp_path))
    assert load_extra_personas("digitaldirection") == []


def test_extra_personas_reads_every_json_file_in_the_packs_own_subdirectory(tmp_path, monkeypatch) -> None:
    directory = tmp_path / "digitaldirection"
    directory.mkdir()
    (directory / "spectrum.json").write_text(
        '{"sender_fingerprint": "digitaldirection|spectrum", "status": "draft"}'
    )
    monkeypatch.setenv("DOCINTEL_EXTRA_PERSONAS_DIR", str(tmp_path))

    out = load_extra_personas("digitaldirection")

    assert out == [{"sender_fingerprint": "digitaldirection|spectrum", "status": "draft"}]


def test_extra_personas_skips_the_aliases_overlay_file(tmp_path, monkeypatch) -> None:
    """`aliases.local.json` lives in the SAME per-pack directory as personas -
    it must never be misread as a persona itself."""
    directory = tmp_path / "digitaldirection"
    directory.mkdir()
    (directory / "spectrum.json").write_text('{"sender_fingerprint": "digitaldirection|spectrum"}')
    (directory / "aliases.local.json").write_text('{"spectrum": "spectrum"}')
    monkeypatch.setenv("DOCINTEL_EXTRA_PERSONAS_DIR", str(tmp_path))

    out = load_extra_personas("digitaldirection")

    assert out == [{"sender_fingerprint": "digitaldirection|spectrum"}]


def test_extra_personas_only_returns_the_named_packs_own_subdirectory(tmp_path, monkeypatch) -> None:
    """A vendor placed under `northstar/` must never leak into
    `digitaldirection`'s own persona list, or vice versa."""
    (tmp_path / "northstar").mkdir()
    (tmp_path / "northstar" / "acme.json").write_text('{"sender_fingerprint": "northstar|acme"}')
    monkeypatch.setenv("DOCINTEL_EXTRA_PERSONAS_DIR", str(tmp_path))

    assert load_extra_personas("digitaldirection") == []
    assert load_extra_personas("northstar") == [{"sender_fingerprint": "northstar|acme"}]


def test_a_malformed_persona_overlay_file_is_skipped_not_a_crash(tmp_path, monkeypatch) -> None:
    """Same discipline as `load_extra_aliases`/`load_basis_overlay`: a typo in
    a caller's own persona.json - a file this project's source never touches -
    must skip only that one file, not crash `process()` for every document of
    every vendor across every pack."""
    directory = tmp_path / "digitaldirection"
    directory.mkdir()
    (directory / "broken.json").write_text("{not valid json")
    monkeypatch.setenv("DOCINTEL_EXTRA_PERSONAS_DIR", str(tmp_path))

    assert load_extra_personas("digitaldirection") == []


def test_a_malformed_persona_overlay_file_does_not_block_its_well_formed_siblings(
    tmp_path, monkeypatch
) -> None:
    """One bad file in the directory must not take down the good ones sitting
    right next to it."""
    directory = tmp_path / "digitaldirection"
    directory.mkdir()
    (directory / "broken.json").write_text("{not valid json")
    (directory / "spectrum.json").write_text('{"sender_fingerprint": "digitaldirection|spectrum"}')
    monkeypatch.setenv("DOCINTEL_EXTRA_PERSONAS_DIR", str(tmp_path))

    out = load_extra_personas("digitaldirection")

    assert out == [{"sender_fingerprint": "digitaldirection|spectrum"}]


def test_a_persona_overlay_file_that_is_not_a_json_object_is_skipped(tmp_path, monkeypatch) -> None:
    """Valid JSON that isn't an object (e.g. a bare list or string) is just as
    unusable as a persona as malformed JSON is - same skip-only-this-file
    behavior, not a crash."""
    directory = tmp_path / "digitaldirection"
    directory.mkdir()
    (directory / "not_an_object.json").write_text("[1, 2, 3]")
    monkeypatch.setenv("DOCINTEL_EXTRA_PERSONAS_DIR", str(tmp_path))

    assert load_extra_personas("digitaldirection") == []


def test_extra_aliases_is_empty_when_the_env_var_is_unset(monkeypatch) -> None:
    monkeypatch.delenv("DOCINTEL_EXTRA_PERSONAS_DIR", raising=False)
    assert load_extra_aliases("digitaldirection") == {}


def test_extra_aliases_reads_the_packs_own_overlay_file(tmp_path, monkeypatch) -> None:
    directory = tmp_path / "digitaldirection"
    directory.mkdir()
    (directory / "aliases.local.json").write_text(
        '{"spectrum": "spectrum", "charter communications": "spectrum"}'
    )
    monkeypatch.setenv("DOCINTEL_EXTRA_PERSONAS_DIR", str(tmp_path))

    assert load_extra_aliases("digitaldirection") == {
        "spectrum": "spectrum",
        "charter communications": "spectrum",
    }


def test_extra_aliases_malformed_json_is_treated_as_no_overlay(tmp_path, monkeypatch) -> None:
    directory = tmp_path / "digitaldirection"
    directory.mkdir()
    (directory / "aliases.local.json").write_text("{not valid json")
    monkeypatch.setenv("DOCINTEL_EXTRA_PERSONAS_DIR", str(tmp_path))

    assert load_extra_aliases("digitaldirection") == {}


def test_digitaldirection_resolves_a_carrier_only_known_through_the_overlay(tmp_path, monkeypatch) -> None:
    """Proves the real consumer, not just the loader: `aliases.canonical`
    must actually find a name that ONLY exists in the external overlay -
    word-boundary matched against real, whole-page text, the same way
    PATTERN_ALIASES already works, not an exact `.get()` that would never
    fire against a multi-line blob."""
    import digitaldirection.aliases as dd_aliases

    directory = tmp_path / "digitaldirection"
    directory.mkdir()
    (directory / "aliases.local.json").write_text('{"spectrum business": "spectrum"}')
    monkeypatch.setenv("DOCINTEL_EXTRA_PERSONAS_DIR", str(tmp_path))

    page_text = "Some Company\nThank you for choosing Spectrum Business for enterprise.\nTotal: $1.00"
    assert dd_aliases.canonical(page_text) == "spectrum"


def test_digitaldirection_personas_include_the_overlay_ones(tmp_path, monkeypatch) -> None:
    from digitaldirection import PACK as dd_pack

    directory = tmp_path / "digitaldirection"
    directory.mkdir()
    (directory / "spectrum.json").write_text(
        '{"sender_fingerprint": "digitaldirection|spectrum", "status": "draft"}'
    )
    monkeypatch.setenv("DOCINTEL_EXTRA_PERSONAS_DIR", str(tmp_path))

    fingerprints = {p["sender_fingerprint"] for p in dd_pack.personas()}
    assert "digitaldirection|spectrum" in fingerprints


def test_digitaldirection_claims_a_carrier_only_known_through_the_overlay(
    tmp_path, monkeypatch
) -> None:
    """The bug this closes: the overlay reached persona lookup
    (`test_digitaldirection_personas_include_the_overlay_ones` above) and
    fingerprint resolution (`test_digitaldirection_resolves_a_carrier_only_
    known_through_the_overlay` above) but never the CLAIM decision itself -
    `alias_table`'s compiled rule baked its needle list in once at import
    time, from `aliases.LITERAL_ALIASES` alone. A carrier this rule never
    claims never reaches persona lookup at all, so proving the other two
    were not enough."""
    from digitaldirection import PACK as dd_pack

    directory = tmp_path / "digitaldirection"
    directory.mkdir()
    (directory / "aliases.local.json").write_text('{"brandnew carrier communications": "brandnew"}')
    monkeypatch.setenv("DOCINTEL_EXTRA_PERSONAS_DIR", str(tmp_path))

    ctx = _ctx("Brandnew", "Carrier", "Communications", "Account", "Summary")
    assert dd_pack.claims(ctx) is True


def test_digitaldirection_overlay_does_not_widen_the_claim_to_everything(
    tmp_path, monkeypatch
) -> None:
    """The overlay must widen what the pack recognizes, not make it claim
    everything - an unrelated document with the overlay set must still go
    unclaimed."""
    from digitaldirection import PACK as dd_pack

    directory = tmp_path / "digitaldirection"
    directory.mkdir()
    (directory / "aliases.local.json").write_text('{"brandnew carrier communications": "brandnew"}')
    monkeypatch.setenv("DOCINTEL_EXTRA_PERSONAS_DIR", str(tmp_path))

    ctx = _ctx("Some", "Unrelated", "Vendor", "Incorporated")
    assert dd_pack.claims(ctx) is False


def test_digitaldirection_still_claims_a_shipped_carrier_with_the_overlay_env_var_unset(
    monkeypatch,
) -> None:
    """The common case - no overlay directory at all - must keep claiming
    every already-shipped carrier exactly as before this fix."""
    from digitaldirection import PACK as dd_pack

    monkeypatch.delenv("DOCINTEL_EXTRA_PERSONAS_DIR", raising=False)

    ctx = _ctx("Comcast", "Business", "Account", "Summary")
    assert dd_pack.claims(ctx) is True


def test_northstar_resolves_a_vendor_only_known_through_the_overlay(tmp_path, monkeypatch) -> None:
    import northstar.aliases as ns_aliases

    directory = tmp_path / "northstar"
    directory.mkdir()
    (directory / "aliases.local.json").write_text('{"acme widgets": "acme_widgets"}')
    monkeypatch.setenv("DOCINTEL_EXTRA_PERSONAS_DIR", str(tmp_path))

    page_text = "Acme Widgets Inc\n123 Main St\nInvoice #1\nTotal: $1.00"
    assert ns_aliases.canonical(page_text) == "acme_widgets"
