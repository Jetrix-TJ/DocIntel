"""`scaffold_pack`/`scaffold_persona` in isolation - does a scaffold actually
load (`packs.datapack.load_pack_file`) and get caught correctly by
`grammar.validator.validate_persona`, the same "survives the real downstream
function" discipline `tests/evals/test_draft_gold.py` applies to gold
fixtures.
"""

from __future__ import annotations

import json

import pytest

from docintel.core.errors import ValidationError
from docintel.generation.pack_scaffold import PLACEHOLDER, scaffold_pack, scaffold_persona
from docintel.grammar.validator import validate_persona
from docintel.packs.datapack import load_pack_file


def test_scaffold_pack_has_one_ladder_rung_per_doc_type():
    """A ladder can never be empty (`declarative.py`'s own load-time check),
    even for a single doc_type - this is the one placeholder that must ALSO
    be structurally loadable, not just present."""
    pack = scaffold_pack("Acme Corp", "acme", ["standard_invoice", "credit_memo"])
    assert len(pack["ladder"]["rungs"]) == 2
    assert pack["ladder"]["default"] == "standard_invoice"


def test_scaffold_pack_declares_a_field_set_per_doc_type():
    pack = scaffold_pack("Acme Corp", "acme", ["standard_invoice", "credit_memo"])
    assert set(pack["fields"]) == {"standard_invoice", "credit_memo"}
    assert pack["fields"]["standard_invoice"] == {
        "all": [], "required": [], "any_of": [], "derived_only": [],
    }


def test_scaffold_pack_survives_a_real_load_pack_file_round_trip(tmp_path):
    """The direct proof this is real, not just JSON-shaped: the exact loader
    `registry.py` calls for every data-only pack must not crash on this."""
    pack = scaffold_pack("Acme Corp", "acme_test_scaffold", ["standard_invoice"])
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(pack))

    loaded = load_pack_file(str(path))

    assert loaded.name == "acme_test_scaffold"
    assert loaded.doc_types == ("standard_invoice",)


def test_scaffold_persona_with_no_hints_has_no_field_selectors():
    persona = scaffold_persona("acme", "acme", "standard_invoice")
    assert persona["field_selectors"] == []
    assert persona["status"] == "draft"


def test_scaffold_persona_sender_fingerprint_is_company_pipe_vendor():
    persona = scaffold_persona("acme", "acme_east_branch", "standard_invoice")
    assert persona["sender_fingerprint"] == "acme|acme_east_branch"


def test_scaffold_persona_carries_over_hint_spec_fields():
    hints = {
        "fields": [
            {"name": "total_printed", "type": "currency", "hint": "bottom right"},
            {"name": "invoice_number", "type": "text", "hint": "top right"},
        ],
        "row_groups": [],
        "notes": "a note",
    }
    persona = scaffold_persona("acme", "acme", "standard_invoice", hints=hints)

    assert len(persona["field_selectors"]) == 2
    sel = persona["field_selectors"][0]
    assert sel["field"] == "total_printed"
    assert sel["pattern"] == "currency"
    assert sel["region"] == PLACEHOLDER
    assert sel["_hint"] == "bottom right"


def test_scaffold_persona_carries_over_hint_spec_row_groups():
    hints = {
        "fields": [],
        "row_groups": [
            {
                "name": "line_items", "hint": "starts below Description",
                "columns": [{"name": "amount", "type": "currency"}],
                "stop_at_subtotal": True,
            },
        ],
        "notes": "",
    }
    persona = scaffold_persona("acme", "acme", "standard_invoice", hints=hints)

    sel = persona["field_selectors"][0]
    assert sel["row_group"] == "line_items"
    assert sel["table_anchor"] == PLACEHOLDER
    assert sel["columns"] == {"amount": "currency"}


def test_scaffold_persona_placeholder_regions_are_caught_by_validate_persona():
    """The direct proof placeholders are real placeholders, not silently
    accepted: the exact function `validate-persona` calls must reject one."""
    hints = {
        "fields": [{"name": "total_printed", "type": "currency", "hint": "bottom right"}],
        "row_groups": [], "notes": "",
    }
    persona = scaffold_persona("acme", "acme", "standard_invoice", hints=hints)

    with pytest.raises(ValidationError, match=PLACEHOLDER):
        validate_persona(persona)


def test_scaffold_persona_with_no_hints_passes_validate_persona_trivially():
    """An empty draft has nothing to violate yet - a real, if unhelpful, pass."""
    persona = scaffold_persona("acme", "acme", "standard_invoice")
    validate_persona(persona)  # must not raise
