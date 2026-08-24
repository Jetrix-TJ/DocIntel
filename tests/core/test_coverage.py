"""`Coverage.collapsed` - the single source of truth `s5b_vision._collapsed`
and `s7_gate.ConfidenceGate._collapsed` both consult.
"""

from __future__ import annotations

from digitaldirection import PACK as DIGITALDIRECTION_PACK

from docintel.core import coverage as coverage_mod
from docintel.core.coverage import Coverage
from docintel.core.models import new_context
from docintel.packs.registry import load_packs


def _coverage(declared: int, populated: int) -> Coverage:
    return Coverage(declared=declared, populated=populated, assessed=True)


def test_an_unassessed_document_never_reads_as_collapsed() -> None:
    """No persona reached, nothing to measure - `complete=True` on a vacuous
    count would be the original bug wearing a new key, and `collapsed=True`
    would be the same mistake in the opposite direction."""
    assert Coverage(assessed=False).collapsed is False


def test_a_document_with_no_declared_selectors_never_reads_as_collapsed() -> None:
    assert _coverage(declared=0, populated=0).collapsed is False


def test_a_large_persona_collapses_when_the_share_crosses_the_floor() -> None:
    """9 declared, 3 populated: 6 missing, 6/9 = 0.667 >= 0.60, and 6 missing
    clears the absolute floor too."""
    assert _coverage(declared=9, populated=3).collapsed is True


def test_a_large_persona_does_not_collapse_below_the_share_floor() -> None:
    """9 declared, 4 populated: 5 missing, 5/9 = 0.556 < 0.60."""
    assert _coverage(declared=9, populated=4).collapsed is False


def test_a_two_field_persona_never_collapses_from_coverage_alone() -> None:
    """The real, live case this fix closes:
    `digitaldirection|golub-windstream-contract` declares exactly 2 selectors,
    both `required: false`, because real amendment layouts vary which one
    prints at all. Losing BOTH is 2/2 = 1.0 - a 100% share, comfortably over
    the 0.60 floor - but only 2 fields were ever at stake, which the absolute
    floor (3) says is not enough evidence that "the rules no longer fit this
    document" rather than "this amendment just doesn't print these two
    values". Before this fix, this exact case set `regen_flag` and routed to
    the `low` lane."""
    assert _coverage(declared=2, populated=0).collapsed is False
    assert _coverage(declared=2, populated=1).collapsed is False


def test_a_three_field_persona_needs_all_three_missing_not_just_two() -> None:
    """3 declared, 1 populated: 2 missing, 2/3 = 0.667 >= 0.60 (share alone
    would collapse here) but 2 < 3 (the absolute floor) - so this no longer
    collapses purely from percentage. All 3 missing (3/3, and 3 >= 3) still
    does."""
    assert _coverage(declared=3, populated=1).collapsed is False
    assert _coverage(declared=3, populated=0).collapsed is True


def test_the_absolute_floor_alone_is_not_sufficient_without_the_share() -> None:
    """20 declared, 15 populated: 5 missing clears the absolute floor (>= 3)
    but 5/20 = 0.25 is nowhere near the 0.60 share floor - a large persona
    missing a handful of fields is not a collapse either."""
    assert _coverage(declared=20, populated=15).collapsed is False


def _golub_windstream_contract_persona():
    from docintel.grammar.schema import parse_persona

    for pack in load_packs() + [DIGITALDIRECTION_PACK]:
        if pack.name != "digitaldirection":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint") == "digitaldirection|windstream" and (
                persona.get("doc_type") == "contract"
            ):
                return parse_persona(persona)
    raise AssertionError("digitaldirection|windstream contract persona not found")


def test_the_real_two_field_windstream_contract_persona_does_not_collapse_when_both_miss() -> None:
    """The scenario the synthetic tests above model, proven against the real
    shipped persona rather than a stand-in: a contract amendment where
    neither `contract_number` nor `effective_date` was found must not read
    as 'the rules no longer fit this document' - both fields are declared
    `required: false` precisely because the persona's own notes say layouts
    vary which one a given amendment prints."""
    persona = _golub_windstream_contract_persona()
    assert len(persona.field_selectors) == 2, (
        "this test's whole premise is that this persona has very few "
        "declared selectors - re-check it still does"
    )

    ctx = new_context("d1", "/x.pdf")
    ctx.persona = persona
    ctx.pack = None
    ctx.doc_type = None

    cov = coverage_mod.assess(ctx)
    assert cov.declared == 2
    assert cov.populated == 0
    assert cov.collapsed is False
