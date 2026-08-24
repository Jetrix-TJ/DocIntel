"""GUARDRAIL 5 — every shipped persona passes the closed grammar.

A persona that cannot pass V1-V13 must never reach the repo. The validator is the
security boundary for agent-written personas (grammar section 8); a hand-authored
one that bypassed it would be a precedent saying the boundary is optional.

This also catches the failure mode that cost a round during C5a: a persona with an
invalid selector does not error loudly, it is *rejected at lookup* and the document
falls silently back to the vision path. DTSS dropped from 23 passing assertions to
14 that way, and nothing but the scorecard noticed.
"""

from __future__ import annotations

import pytest

from digitaldirection import PACK as DIGITALDIRECTION_PACK
from northstar import PACK as NORTHSTAR_PACK

from docintel.core.models import DERIVED_ONLY
from docintel.grammar.schema import parse_persona
from docintel.grammar.validator import validate_persona
from docintel.packs.registry import load_packs

# northstar/digitaldirection are real, measured configuration for two real
# companies - kept as test fixtures rather than shipped (see registry.py's
# PACK_MODULES comment) - but their personas still deserve this guardrail's
# coverage, so they're included here explicitly rather than silently dropped.
PACKS = load_packs() + [NORTHSTAR_PACK, DIGITALDIRECTION_PACK]
PERSONAS = [(pack, p) for pack in PACKS for p in pack.personas()]


def test_packs_are_loaded() -> None:
    assert PACKS


def test_personas_are_shipped() -> None:
    assert PERSONAS, "a pack with no personas cannot take the fast lane at all"


@pytest.mark.parametrize(
    "pack,persona", PERSONAS, ids=[p["sender_fingerprint"] for _, p in PERSONAS]
)
def test_every_shipped_persona_passes_the_closed_grammar(pack, persona) -> None:
    validate_persona(persona, pack=pack)


@pytest.mark.parametrize(
    "pack,persona", PERSONAS, ids=[p["sender_fingerprint"] for _, p in PERSONAS]
)
def test_no_shipped_persona_targets_a_derived_field(pack, persona) -> None:
    """V10 from the other direction. `amount_payable` is the F1 footgun: on 7 of
    the 10 corpus documents a selector pointed at it would look correct."""
    for selector in persona["field_selectors"]:
        assert selector.get("field") not in DERIVED_ONLY
        for column in (selector.get("columns") or {}):
            assert column not in DERIVED_ONLY


@pytest.mark.parametrize(
    "pack,persona", PERSONAS, ids=[p["sender_fingerprint"] for _, p in PERSONAS]
)
def test_every_shipped_persona_is_active_not_draft(pack, persona) -> None:
    """A `draft` persona applies `draft_rules` (x0.85) to every field against a
    0.90 default threshold, so it can never reach the `high` lane - and seven
    corpus documents expect one. Draft is for authoring, not for shipping."""
    assert persona["status"] == "active"


@pytest.mark.parametrize(
    "pack,persona", PERSONAS, ids=[p["sender_fingerprint"] for _, p in PERSONAS]
)
def test_every_persona_parses_into_typed_selectors(pack, persona) -> None:
    parsed = parse_persona(persona)
    assert parsed.field_selectors


def test_persona_fingerprints_are_unique_per_doc_type() -> None:
    """Two personas on one key would mean whichever loaded last silently won."""
    keys = [(p["sender_fingerprint"], p["doc_type"]) for _, p in PERSONAS]
    assert len(keys) == len(set(keys))


def test_every_persona_fingerprint_names_a_known_vendor() -> None:
    """The fingerprint a persona declares and the one the `beforePersonaLookup`
    hook computes from page text must be the same string, or the persona is
    unreachable and nothing says so."""
    from northstar import aliases

    for pack, persona in PERSONAS:
        if pack.name != "northstar":
            continue
        prefix, _, vendor = persona["sender_fingerprint"].partition("|")
        assert prefix == "northstar"
        assert vendor in aliases.KNOWN_VENDORS, f"{vendor!r} is not in the alias table"
