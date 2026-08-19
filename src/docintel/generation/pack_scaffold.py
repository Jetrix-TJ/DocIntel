"""Scaffold a brand-new company's `pack.json` and a starter persona - the rest
of Hari's "blank space" once a filled-in `COMPANY-CONFIG-TEMPLATE.md` names
the company and its document types. Nothing here is registered anywhere on
its own (see `generation.persona_agent`'s own docstring for the identical
discipline) - a human reviews and wires this in, exactly like every other
draft this project produces.

If a `generate-persona` hint-spec draft is given, its field names/types seed
the starter persona's `field_selectors` - carrying the SAME closed-vocabulary
discipline through rather than inventing a second copy of it (see
`persona_agent.py`'s own module docstring for why that vocabulary is a closed
set in the first place). What this never writes is selector geometry -
`region`/`table_anchor`/`anchor` are always left an explicit placeholder,
because that is the one thing this session's own evidence says does not
generalize from a blind pass (194/283 vs. 238/283 in an earlier exercise,
losses almost entirely geometry) and stays a human's job either way.

The very next step after this command is `docintel validate-persona
--pack-file <the scaffolded pack.json>` (see `cli.py`'s own printed
reminder) - every placeholder this module writes is deliberately something
that command will catch and name, one at a time, rather than something that
would silently pass.

Once a human fills in the real selectors, the scaffold is not just valid but
actually runnable end to end, with no Python: `DataPack.register_hooks`
(`datapack.py`) resolves `sender_fingerprint` declaratively from the pack's
own `aliases.literal` table, falling back to its one shipped persona when the
pack has only that one vendor - the common case for a company onboarded this
way, needing zero alias entries at all.
"""

from __future__ import annotations

from typing import Any

PLACEHOLDER = "TODO-human-must-set"


def _placeholder_rung(doc_type: str, index: int) -> dict[str, Any]:
    """A ladder must have at least one rung (`declarative.py`'s own load-time
    check: `ladder.rungs: expected a non-empty list`, even for a single
    doc_type) - a data pack with no real rungs at all isn't expressible, so
    this is the one placeholder that must ALSO be structurally loadable
    (a valid regex, a real signal name) rather than left blank, unlike every
    other placeholder in this module. `pattern_in_scope` never matches a real
    document until a human replaces the pattern - it's a closed-vocabulary
    signal, not a made-up one, exactly what a real rung would use.
    """
    return {
        "name": f"{doc_type}_placeholder_{index}",
        "doc_type": doc_type,
        "when": {
            "signal": "pattern_in_scope",
            "params": {"pattern": PLACEHOLDER, "scope": "primary"},
        },
    }


def scaffold_pack(company_name: str, slug: str, doc_types: list[str]) -> dict[str, Any]:
    rungs = [_placeholder_rung(doc_type, i) for i, doc_type in enumerate(doc_types)]
    return {
        "_note": (
            f"{company_name} - scaffolded by `docintel new-pack`, NOT reviewed. "
            "Every threshold/claim/ladder value below is a placeholder, including "
            "every ladder rung (a ladder can't be empty, so each doc_type gets one "
            "placeholder rung that will never actually match - replace or delete "
            "them once real documents are in hand). See "
            "docs/DOCINTEL-ARCHITECTURE-GUIDE.html#new-company for a real, "
            "worked example (acme_freight) before filling these in."
        ),
        "name": slug,
        "default_currency": "USD",
        "doc_types": doc_types,
        "bill_to_roster": [PLACEHOLDER],
        "aliases": {"literal": {}, "display": {}},
        "thresholds": {},
        "fields": {
            doc_type: {"all": [], "required": [], "any_of": [], "derived_only": []}
            for doc_type in doc_types
        },
        "claim": {
            "rules": [{"kind": "markers", "scope": "primary", "values": [PLACEHOLDER]}],
            "vetoes": [],
        },
        "ladder": {"default": doc_types[0], "rungs": rungs},
        "tags": [],
    }


def scaffold_persona(
    company_slug: str,
    vendor_slug: str,
    doc_type: str,
    hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    field_selectors: list[dict[str, Any]] = []
    for field in (hints or {}).get("fields", []):
        field_selectors.append({
            "field": field["name"],
            "region": PLACEHOLDER,
            "pattern": field["type"],
            "_hint": field.get("hint", ""),
        })
    for group in (hints or {}).get("row_groups", []):
        field_selectors.append({
            "row_group": group["name"],
            "table_anchor": PLACEHOLDER,
            "columns": {c["name"]: c["type"] for c in group.get("columns", [])},
            "_hint": group.get("hint", ""),
        })

    return {
        "sender_fingerprint": f"{company_slug}|{vendor_slug}",
        "doc_type": doc_type,
        "rule_version": "v1",
        "status": "draft",
        "notes": (
            "Scaffolded by `docintel new-pack`, NOT reviewed. Every region/anchor/"
            "table_anchor above is a placeholder - run `docintel validate-persona "
            "--pack-file <this pack's pack.json>` to see them named one at a time."
        ),
        "field_selectors": field_selectors,
    }
