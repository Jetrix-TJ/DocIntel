from decimal import Decimal
import pytest
from docintel.core.models import (
    DerivedFields, ExtractedFields, PageText, ReferenceHit, Word, new_context,
)

DERIVED_ONLY = {"amount_payable", "payable_basis", "document_identity", "identity_basis"}


def test_extracted_fields_refuse_derived_only_names():
    """Grammar V10: no selector may target amount_payable. Enforced by type, not convention."""
    ef = ExtractedFields()
    for name in DERIVED_ONLY:
        with pytest.raises(ValueError, match="derived_only"):
            ef.set(name, Decimal("13752.60"), match_quality=1.0)


def test_extracted_fields_accept_printed_values():
    ef = ExtractedFields()
    ef.set("total_printed", Decimal("33876.40"), match_quality=0.98)
    ef.set("current_charges", Decimal("13752.60"), match_quality=0.97)
    assert ef.get("total_printed") == Decimal("33876.40")
    assert ef.match_quality["current_charges"] == 0.97


def test_derived_fields_accept_amount_payable():
    df = DerivedFields()
    df.set("amount_payable", Decimal("13752.60"))
    df.set("payable_basis", "current_charges")
    assert df.get("amount_payable") == Decimal("13752.60")


def test_pagetext_lines_groups_words_by_row():
    words = (
        Word("CURRENT", 10.0, 100.0, 60.0, 110.0),
        Word("CHARGES:", 62.0, 100.0, 120.0, 110.0),
        Word("69.62", 300.0, 100.0, 340.0, 110.0),
        Word("BALANCE", 10.0, 130.0, 70.0, 140.0),
    )
    page = PageText(page_number=1, words=words, width=612.0, height=792.0, source="native")
    lines = page.lines()
    assert len(lines) == 2
    assert [w.text for w in lines[0]] == ["CURRENT", "CHARGES:", "69.62"]
    assert "CURRENT CHARGES: 69.62" in page.text


def test_pagetext_source_is_constrained():
    with pytest.raises(ValueError):
        PageText(page_number=1, words=(), width=1.0, height=1.0, source="magic")


def test_new_context_starts_with_the_invariant_unsatisfied():
    ctx = new_context(document_id="doc1", source_path="/tmp/x.pdf")
    assert ctx.emitted is False
    assert ctx.disposition == "processed"
    assert ctx.reference_list == []
    assert ctx.modifiers == []


def test_reference_hit_carries_provenance():
    """F11: reference_list is objects, not strings, so annotation-sourced keys stay identifiable."""
    hit = ReferenceHit(value="2436687", source_field="Reference", page=1, pattern_id="ref_column")
    assert hit.source_field == "Reference"
