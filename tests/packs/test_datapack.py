"""Onboarding a company must cost a config file, not a Python module.

**This is the test that decides whether the declarative work met its goal**, and
it is written so that it FAILS if a future change makes a pack need code again.
Everything else in that work — the signal registry, the ladder compiler, the
claim compiler — is machinery. This is the outcome.

The bar, stated concretely: the two module-backed packs are ~1,290 and ~1,150
lines of Python across eight modules each. `acme_freight` is one `pack.json`.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from docintel.core.models import PageMeta, PageText, Word, new_context
from docintel.packs import registry
from docintel.packs.datapack import DataPack, PackSpecError, load_pack_file
from docintel.packs.registry import Pack, load_packs, resolve_pack

PACK_DIR = pathlib.Path(registry.__file__).parent / "acme_freight"


def _ctx(text: str, role: str = "primary", source: str = "native"):
    words: list[Word] = []
    for row, line in enumerate(text.split("|")):
        y = 100.0 + row * 14.0
        for i, tok in enumerate(line.split()):
            words.append(
                Word(text=tok, x0=10.0 + 40.0 * i, y0=y, x1=45.0 + 40.0 * i, y1=y + 10.0)
            )
    ctx = new_context("d", "/x.pdf")
    ctx.pages = (
        PageText(page_number=1, words=tuple(words), width=612.0, height=792.0, source=source),
    )
    ctx.page_meta = (PageMeta(1, 100, 0, 0, role),)
    ctx.text_source = source
    return ctx


def _acme() -> DataPack:
    return load_pack_file(str(PACK_DIR / "pack.json"))


# --------------------------------------------------------------------------
# The goal
# --------------------------------------------------------------------------


def test_the_third_pack_contains_no_python_at_all() -> None:
    """THE POINT. If this fails, onboarding a company costs code again."""
    python_files = sorted(p.name for p in PACK_DIR.rglob("*.py"))
    assert python_files == [], f"acme_freight should be data only, found {python_files}"


def test_the_third_pack_is_not_a_python_module() -> None:
    """It is listed in PACK_FILES, not PACK_MODULES. Discovery stays deliberate
    either way - a pack is a business decision and must not activate because
    somebody dropped a folder on disk - but the DECISION now costs a config file
    rather than eight modules."""
    assert not any("acme" in module for module in registry.PACK_MODULES)
    assert "acme_freight/pack.json" in registry.PACK_FILES


def test_it_satisfies_the_same_protocol_as_the_module_packs() -> None:
    """A data pack is not a lesser kind of pack: the pipeline, the grammar
    validator and the scorecard must not be able to tell the difference."""
    assert isinstance(_acme(), Pack)


def test_it_is_loaded_by_the_real_registry() -> None:
    # spt_metals joined PACK_MODULES between digitaldirection and the
    # data-only acme_freight (PACK_FILES) - a module pack with a custom hook,
    # not a drift in this list.
    assert [p.name for p in load_packs()] == [
        "northstar", "digitaldirection", "spt_metals", "acme_freight",
    ]


# --------------------------------------------------------------------------
# It actually works
# --------------------------------------------------------------------------


def test_it_claims_its_own_documents() -> None:
    ctx = _ctx("SUMMIT CARRIERS LLC|INVOICE 8891|BILL TO: ACME FREIGHT SERVICES|TOTAL 1,200.00")
    assert resolve_pack(ctx, load_packs()).name == "acme_freight"


def test_one_pack_file_is_one_object_however_often_it_is_loaded() -> None:
    """Required for correctness, not speed, and the bug it prevents is silent.

    `registry._ClaimGatedRegistry` gates a pack's hooks on `ctx.pack is owner` -
    an IDENTITY test. A module pack is a singleton (`module.PACK`), so identity
    holds across any number of `load_packs()` calls. If a data pack were rebuilt
    per call, a caller that loaded packs twice - once to register hooks, once to
    resolve - would get a gate that never matches: the pack claims its documents
    and then its ladder never runs, leaving every one at the pipeline default.

    `build_pipeline` happens to load once and share the list, so the shipped
    path was safe. "Happens to" is not a contract, so this pins it.
    """
    first = {p.name: p for p in load_packs()}
    second = {p.name: p for p in load_packs()}
    assert first["acme_freight"] is second["acme_freight"]
    assert first["northstar"] is second["northstar"]


def test_it_does_not_claim_another_packs_document() -> None:
    ctx = _ctx("VERITIV|INVOICE 715|BILL TO: NORTHSTAR RECYCLING COMPANY LLC|TOTAL 100.00")
    assert resolve_pack(ctx, load_packs()).name == "northstar"


def test_its_ship_to_veto_works_like_the_pack_it_was_copied_from() -> None:
    ctx = _ctx(
        "GLOBEX SUPPLY|INVOICE 1|BILL TO: GLOBEX CORP AUSTIN TX|"
        "SHIP TO: ACME FREIGHT SERVICES DOCK 4|TOTAL 50.00"
    )
    assert resolve_pack(ctx, load_packs()) is None


def test_its_ladder_classifies() -> None:
    acme = _acme()
    body = "|".join(["ACME"] * 3 + ["CREDIT MEMO"] + ["filler"] * 10)
    assert acme.ladder.doc_type_for(_ctx(body)) == ("credit_memo", "credit_memo_title")
    assert acme.ladder.doc_type_for(_ctx("INVOICE 8891|TOTAL 1,200.00")) == (
        "standard_invoice",
        "default",
    )


def test_a_statement_with_a_charges_table_is_still_an_invoice() -> None:
    """The rule Digital Direction learned at a cost of $20,123.80, inherited by a
    pack that never had to relearn it - which is what a shared registry buys."""
    acme = _acme()
    assert acme.ladder.doc_type_for(
        _ctx("STATEMENT OF ACCOUNT|1.00 2.00 3.00")
    ) == ("standard_invoice", "default")
    assert acme.ladder.doc_type_for(
        _ctx("STATEMENT OF ACCOUNT|no table here")
    ) == ("statement_of_account", "statement_title_no_table")


def test_its_tags_fire() -> None:
    acme = _acme()
    assert "past_due" in acme.tag_rules.tags_for(_ctx("INVOICE 1|PAST DUE"))
    assert "ocr_only" in acme.tag_rules.tags_for(_ctx("INVOICE 1", source="ocr"))


def test_classify_sets_everything_the_record_needs() -> None:
    ctx = _acme().classify(_ctx("INVOICE 1|PAST DUE"))
    assert ctx.doc_type == "standard_invoice"
    assert ctx.signal_that_fired == "default"
    assert ctx.classification_confidence == 0.80
    assert "past_due" in ctx.tags


# --------------------------------------------------------------------------
# Vendor-fingerprint resolution - declarative, no Python hook required
# --------------------------------------------------------------------------


def _pack_with_alias(tmp_path, literal: dict, doc_type: str = "standard_invoice") -> DataPack:
    spec = _spec()
    spec["name"] = "bluepine_testing"
    spec["aliases"] = {"literal": literal, "display": {}}
    return DataPack(spec, directory=str(tmp_path))


def _write_persona(tmp_path, filename: str, sender_fingerprint: str, doc_type: str = "standard_invoice") -> None:
    personas_dir = tmp_path / "personas"
    personas_dir.mkdir(exist_ok=True)
    (personas_dir / filename).write_text(json.dumps({
        "sender_fingerprint": sender_fingerprint, "doc_type": doc_type,
        "rule_version": "v1", "status": "draft", "field_selectors": [],
    }))


def test_canonical_vendor_matches_its_own_alias_table(tmp_path) -> None:
    pack = _pack_with_alias(tmp_path, {"bluepine testing supplies": "bluepine_testing"})
    ctx = _ctx("BLUEPINE TESTING SUPPLIES|INVOICE BP-1|TOTAL 100.00")
    assert pack._canonical_vendor(ctx) == "bluepine_testing"


def test_canonical_vendor_alias_match_is_word_boundary_safe(tmp_path) -> None:
    """A short alias must not fire on a partial-word substring - the same
    concern `northstar.aliases`' regex patterns are careful about (`\\bu\\s?pak\\b`,
    not a bare substring search)."""
    pack = _pack_with_alias(tmp_path, {"pak": "some_other_vendor"})
    ctx = _ctx("BLUEPINE TESTING SUPPLIES|INVOICE BP-1|TOTAL 100.00")
    assert pack._canonical_vendor(ctx) is None


def test_canonical_vendor_falls_back_to_its_one_persona_with_no_alias_match(tmp_path) -> None:
    """The common case for a newly-scaffolded, single-vendor pack: zero alias
    entries required at all."""
    pack = _pack_with_alias(tmp_path, {})
    _write_persona(tmp_path, "bluepine_testing.json", "bluepine_testing|bluepine_testing")
    ctx = _ctx("ANYTHING AT ALL ON THE PAGE|TOTAL 100.00")
    assert pack._canonical_vendor(ctx) == "bluepine_testing"


def test_canonical_vendor_does_not_guess_with_several_personas_and_no_alias_match(tmp_path) -> None:
    """Multiple vendors under one pack genuinely need an alias table - falling
    back to "the first persona" would silently misroute the others."""
    pack = _pack_with_alias(tmp_path, {})
    _write_persona(tmp_path, "vendor_a.json", "bluepine_testing|vendor_a")
    _write_persona(tmp_path, "vendor_b.json", "bluepine_testing|vendor_b")
    ctx = _ctx("ANYTHING AT ALL ON THE PAGE|TOTAL 100.00")
    assert pack._canonical_vendor(ctx) is None


def test_canonical_vendor_is_none_with_no_alias_match_and_no_personas_at_all(tmp_path) -> None:
    pack = _pack_with_alias(tmp_path, {})
    ctx = _ctx("ANYTHING AT ALL ON THE PAGE|TOTAL 100.00")
    assert pack._canonical_vendor(ctx) is None


def test_resolve_vendor_fingerprint_sets_the_full_pack_qualified_key(tmp_path) -> None:
    pack = _pack_with_alias(tmp_path, {"bluepine testing supplies": "bluepine_testing"})
    ctx = _ctx("BLUEPINE TESTING SUPPLIES|INVOICE BP-1|TOTAL 100.00")
    result = pack._resolve_vendor_fingerprint(ctx, lambda c: c)
    assert result.sender_fingerprint == "bluepine_testing|bluepine_testing"


def test_resolve_vendor_fingerprint_leaves_it_unset_when_nothing_resolves(tmp_path) -> None:
    pack = _pack_with_alias(tmp_path, {})
    _write_persona(tmp_path, "vendor_a.json", "bluepine_testing|vendor_a")
    _write_persona(tmp_path, "vendor_b.json", "bluepine_testing|vendor_b")
    ctx = _ctx("ANYTHING AT ALL ON THE PAGE|TOTAL 100.00")
    result = pack._resolve_vendor_fingerprint(ctx, lambda c: c)
    assert result.sender_fingerprint is None


def test_register_hooks_wires_fingerprint_resolution_gated_on_this_packs_own_claim(tmp_path) -> None:
    """The exact failure class this file's own module docstring warns about:
    a second pack's hook must never resolve a fingerprint for a document the
    FIRST pack claimed."""
    from docintel.packs.registry import register_all
    from docintel.pipeline.hooks import HookRegistry

    acme = _acme()
    bluepine = _pack_with_alias(tmp_path, {"bluepine testing supplies": "bluepine_testing"})

    hooks = HookRegistry()
    register_all(hooks, [acme, bluepine])

    ctx = _ctx("BLUEPINE TESTING SUPPLIES|INVOICE BP-1|TOTAL 100.00")
    ctx.pack = acme  # acme claimed it, not bluepine

    result = hooks.run("beforePersonaLookup", ctx)

    assert result.sender_fingerprint is None


def test_register_hooks_resolves_fingerprint_for_the_pack_that_actually_claimed(tmp_path) -> None:
    from docintel.packs.registry import register_all
    from docintel.pipeline.hooks import HookRegistry

    bluepine = _pack_with_alias(tmp_path, {"bluepine testing supplies": "bluepine_testing"})
    hooks = HookRegistry()
    register_all(hooks, [bluepine])

    ctx = _ctx("BLUEPINE TESTING SUPPLIES|INVOICE BP-1|TOTAL 100.00")
    ctx.pack = bluepine

    result = hooks.run("beforePersonaLookup", ctx)

    assert result.sender_fingerprint == "bluepine_testing|bluepine_testing"


# --------------------------------------------------------------------------
# A malformed pack file fails at LOAD
# --------------------------------------------------------------------------


def _spec(**overrides) -> dict:
    spec = json.loads((PACK_DIR / "pack.json").read_text())
    spec.update(overrides)
    return spec


def test_a_ladder_producing_an_undeclared_doc_type_is_rejected() -> None:
    """The subtle one. A rung can name any string; if the pack does not declare
    that doc_type there is no field set for it, so the document classifies
    successfully and then extraction has nothing to read."""
    spec = _spec()
    spec["ladder"]["rungs"][0]["doc_type"] = "invoice_with_attachment"
    with pytest.raises(PackSpecError, match="does not declare"):
        DataPack(spec, directory=str(PACK_DIR))


def test_a_pack_without_a_claim_is_rejected() -> None:
    spec = _spec()
    del spec["claim"]
    with pytest.raises(PackSpecError, match="how it claims"):
        DataPack(spec, directory=str(PACK_DIR))


def test_fields_for_an_undeclared_doc_type_are_rejected() -> None:
    spec = _spec()
    spec["fields"]["telecom_bill"] = {"all": []}
    with pytest.raises(PackSpecError, match="undeclared doc_types"):
        DataPack(spec, directory=str(PACK_DIR))


def test_a_pack_without_a_name_is_rejected() -> None:
    spec = _spec()
    del spec["name"]
    with pytest.raises(PackSpecError, match="name is required"):
        DataPack(spec, directory=str(PACK_DIR))


def test_a_missing_pack_file_is_a_load_error_not_a_silent_skip() -> None:
    with pytest.raises(PackSpecError, match="cannot be read"):
        load_pack_file(str(PACK_DIR / "nope.json"))
