"""GUARDRAIL 3 — the scorecard's own blind spots.

Standing rule 3 says: when a cluster adds a capability, check the scorecard
measures it. That rule has been violated four times now — `reference_list` and
all fifteen tags (found in A10), `page_roles` (found in C1b), the four contract
keys (found in A10, fixed in C2b), and then in C3 both `lane` and the entire
`assertions` array plus 29 unasserted gold field names.

Every one of those was invisible: no test failed, no count looked wrong, and the
loop could have reported "10/10 green" while measuring none of them.

This file makes the gap mechanical instead of a thing somebody has to remember.
It asserts that every fact a gold file states is either asserted by the scorecard
or explicitly classified as not-asserted-and-why. Adding a gold file, or an
assertion to an existing one, fails here until someone makes that decision.

DO NOT satisfy a failure here by deleting the check. Classify the new name in
`scorecard.GOLD_ASSERTION_COVERAGE`, or wire it.
"""

from __future__ import annotations

import pytest

from docintel.core.confidence import MODIFIERS
from docintel.scorecard import (
    CHECKED_DERIVED,
    CHECKED_FIELDS,
    GOLD_ASSERTION_COVERAGE,
    assertions_for,
    load_gold,
)

GOLD = load_gold()

# Gold field names that are the labeller's prose about a judgement, not a value
# any pipeline could produce. These are the only fields allowed to go unchecked.
PROSE_FIELDS = frozenset({"prior_balance_basis_note", "currency_basis_note"})

VERDICT_PREFIXES = ("covered:", "wired:", "documentation", "deferred:")

DEFERRED_REASON = "deferred:printed-fields-only"

# Gold `derived` keys the printed-fields-only narrowing retired. Both are
# DERIVED_ONLY names; the gold files still record their answers, so the evidence
# for re-enabling stays on disk and this list is what points at it.
DEFERRED_DERIVED_KEYS = frozenset({"amount_payable", "payable_basis"})

# Assertions that an empty record satisfies for a legitimate reason, keyed
# `<gold_id>:<assertion>` (or `*:<assertion>` for all documents). Every entry
# needs a written reason, and this list must not grow without one: each one is a
# free pass in the numerator, and the numerator is the only number anyone reads.
VACUOUS_BY_CONSTRUCTION: dict[str, str] = {
    # False is both the gold expectation on most documents and a JobContext
    # default. Making these non-vacuous would mean asserting the gate RAN, which
    # is `lane` - and `lane` is asserted and does fail on an empty record.
    "*:review_flag": "False is the gold expectation and the default",
    "*:regen_flag": "False is the gold expectation and the default",
    # U-PAK's two entries left with the printed-fields-only narrowing. Its gold
    # expects a null payable because refusing IS the right answer (F8) and an
    # empty record matched that by coincidence — but `derived.amount_payable` and
    # `derived.payable_basis` are no longer asserted at all, so there is nothing
    # left to forgive. See test_upak_has_no_document_specific_vacuous_allowance.
}


def _all_check_names() -> set[str]:
    return {
        str(entry.get("check"))
        for gold in GOLD
        for entry in (gold.get("assertions") or [])
    }


# --------------------------------------------------------------------------
# The assertions array
# --------------------------------------------------------------------------


def test_every_gold_assertion_check_is_classified() -> None:
    """The C3 finding, made mechanical.

    68 entries across 55 check names were read by nothing at all. Underneath
    them, the whole of spec section 5 — 16 confidence modifiers — was unmeasured.
    """
    present = _all_check_names()
    unclassified = sorted(present - set(GOLD_ASSERTION_COVERAGE))
    assert not unclassified, (
        f"gold assertion checks with no coverage verdict: {unclassified}. "
        "Classify them in scorecard.GOLD_ASSERTION_COVERAGE or wire them."
    )


def test_the_coverage_table_has_no_stale_entries() -> None:
    """A verdict for a check name no gold file states is dead weight that will
    outlive whatever it was written for."""
    stale = sorted(set(GOLD_ASSERTION_COVERAGE) - _all_check_names())
    assert not stale, f"coverage verdicts for checks no gold file makes: {stale}"


@pytest.mark.parametrize("check", sorted(GOLD_ASSERTION_COVERAGE))
def test_every_verdict_is_one_of_the_four_kinds(check: str) -> None:
    verdict = GOLD_ASSERTION_COVERAGE[check]
    assert verdict.startswith(VERDICT_PREFIXES), (
        f"{check!r} has verdict {verdict!r}, which is none of {VERDICT_PREFIXES}"
    )


def test_no_derived_only_field_is_asserted_by_the_scorecard() -> None:
    """The printed-fields-only rule, in machine-checkable form.

    `document_identity` and `identity_basis` are the exception and stay: they are
    Stage 8 contract keys carrying pipeline provenance, required to be PRESENT by
    core/contract.py, and they live under `derived` rather than `fields` — which
    is where the record already draws this line.
    """
    from docintel.core.models import DERIVED_ONLY

    retained = {"document_identity", "identity_basis"}
    asserted = {a.name for gold in GOLD for a in assertions_for(gold)}
    for name in DERIVED_ONLY - retained:
        offenders = [a for a in asserted if a.endswith(f".{name}") or a == name]
        assert not offenders, f"{name} is derived-only but still asserted: {offenders}"


def test_every_deferred_verdict_names_this_spec() -> None:
    """A bare `deferred:` tells a later reader nothing about what to re-enable."""
    for check, verdict in GOLD_ASSERTION_COVERAGE.items():
        if verdict.startswith("deferred:"):
            assert verdict == DEFERRED_REASON or "printed-fields-only" not in verdict, (
                f"{check} has an ad-hoc deferral reason {verdict!r}; use "
                f"{DEFERRED_REASON!r} so all of them are greppable together"
            )


def test_every_named_assertion_in_the_table_is_one_the_scorecard_emits() -> None:
    """A `covered:` or `wired:` verdict pointing at an assertion that does not
    exist is worse than no verdict: it reads as coverage that is not there."""
    emitted = {a.name for gold in GOLD for a in assertions_for(gold)}
    # Field and derived assertions are only emitted when that gold file carries
    # the value, so the union across all ten is the right thing to check against.
    emitted |= {f"fields.{name}" for name in CHECKED_FIELDS}
    emitted |= {f"derived.{name}" for name in CHECKED_DERIVED}

    dangling = sorted(
        f"{check} -> {verdict}"
        for check, verdict in GOLD_ASSERTION_COVERAGE.items()
        if verdict.startswith(("covered:", "wired:"))
        and verdict.split(":", 1)[1] not in emitted
    )
    assert not dangling, f"verdicts naming an assertion the scorecard never emits: {dangling}"


# --------------------------------------------------------------------------
# Gold fields
# --------------------------------------------------------------------------


def test_every_gold_field_is_either_asserted_or_declared_prose() -> None:
    """The larger half of the C3 finding: 29 gold field names across 73
    occurrences were never asserted, `bill_to_address` and `currency_basis` in
    all ten files. `currency_basis` is C3's own output."""
    unchecked: dict[str, int] = {}
    for gold in GOLD:
        for name, value in (gold.get("fields") or {}).items():
            if value is None or name in CHECKED_FIELDS or name in PROSE_FIELDS:
                continue
            unchecked[name] = unchecked.get(name, 0) + 1
    assert not unchecked, (
        f"gold fields present but never asserted: {sorted(unchecked)}. "
        "Add them to scorecard.CHECKED_FIELDS or to PROSE_FIELDS here."
    )


def test_the_prose_exemption_list_stays_small() -> None:
    """An exemption list is how this gap comes back. Two entries, both `*_note`."""
    assert all(name.endswith("_note") for name in PROSE_FIELDS)
    assert len(PROSE_FIELDS) <= 2


def test_every_gold_derived_key_is_asserted_or_explicitly_deferred() -> None:
    """CHECKED_DERIVED narrowed to the two Stage 8 contract keys, and this
    follows it — without losing the property that made it a guardrail.

    A gold `derived` key must still be accounted for. It may now be accounted for
    in two ways instead of one: asserted, or named in DEFERRED_DERIVED_KEYS *and*
    carrying the printed-fields-only verdict in the coverage table. A new gold
    derived key satisfies neither and still fails here.
    """
    for gold in GOLD:
        for name in (gold.get("derived") or {}):
            if name in DEFERRED_DERIVED_KEYS:
                assert GOLD_ASSERTION_COVERAGE.get(name) == DEFERRED_REASON, (
                    f"gold derived.{name} is not asserted and has no "
                    f"{DEFERRED_REASON!r} verdict — it is simply unaccounted for"
                )
                continue
            assert name in CHECKED_DERIVED, f"gold derived.{name} is never asserted"


def test_the_deferred_derived_list_holds_only_derived_only_names() -> None:
    """The deferral exists because these are computed, not because they are
    inconvenient. Anything not in DERIVED_ONLY has no business on this list."""
    from docintel.core.models import DERIVED_ONLY

    assert DEFERRED_DERIVED_KEYS <= DERIVED_ONLY
    assert not DEFERRED_DERIVED_KEYS & set(CHECKED_DERIVED)


# --------------------------------------------------------------------------
# Routing and modifiers
# --------------------------------------------------------------------------


def test_every_expected_routing_key_is_asserted() -> None:
    """`lane` sat here unasserted through Part A and two Part B clusters."""
    asserted = {"lane", "review_flag", "regen_flag"}
    for gold in GOLD:
        for name in gold["expected_routing"]:
            if name == "reason":
                continue  # free-text explanation of the routing, not a value
            assert name in asserted, f"expected_routing.{name} is never asserted"


def test_the_modifier_mechanism_is_measured_somewhere() -> None:
    """Not every modifier can be predicted from a gold label, but if NO document
    asserts modifiers at all then spec section 5 is entirely unmeasured — which is
    exactly the state C3b found."""
    names = {a.name for gold in GOLD for a in assertions_for(gold)}
    assert "confidence_modifiers" in names


def test_modifier_expectations_only_name_real_modifiers() -> None:
    """A typo would silently weaken a superset check rather than fail it."""
    for gold in GOLD:
        for assertion in assertions_for(gold):
            if assertion.name != "confidence_modifiers":
                continue
            unknown = sorted(set(assertion.expected) - set(MODIFIERS))
            assert not unknown, f"{gold['gold_id']} expects unknown modifiers {unknown}"


def test_no_assertion_passes_vacuously_on_an_empty_record() -> None:
    """The trap this cluster had to avoid.

    A "modifier is absent" or "field is absent" assertion is satisfied by a
    pipeline that computed nothing, so adding those would have raised the score
    while measuring nothing. Every assertion must FAIL against an empty record —
    otherwise it is a free pass, and the numerator stops meaning anything.

    The exceptions are the handful of genuine "this document really is like that"
    facts, which an empty record does happen to satisfy.
    """
    empty: dict[str, object] = {
        "doc_type": None, "text_source": None, "fields": {}, "derived": {},
        "confidence_modifiers": [], "reference_list": [], "tags": [],
        "line_items": [], "charges": [], "sub_account": [], "scanline": None,
        "review_flag": False, "regen_flag": False, "lane": None,
        "page_roles": [],
    }
    from docintel.scorecard import matches

    vacuous: list[str] = []
    for gold in GOLD:
        for a in assertions_for(gold):
            if matches(a.expected, a.getter(empty), a.kind):
                vacuous.append(f"{gold['gold_id']}:{a.name}")

    allowed = set(VACUOUS_BY_CONSTRUCTION)
    unexpected = sorted(
        v for v in vacuous
        if v not in allowed and f"*:{v.split(':', 1)[1]}" not in allowed
    )
    assert not unexpected, f"assertions that pass against an empty record: {unexpected}"


def test_the_vacuous_allowance_list_stays_honest() -> None:
    """Every allowance must still be a real assertion, or the list is fiction."""
    live = {
        f"{gold['gold_id']}:{a.name}"
        for gold in GOLD for a in assertions_for(gold)
    }
    live |= {f"*:{a.name}" for gold in GOLD for a in assertions_for(gold)}
    stale = sorted(set(VACUOUS_BY_CONSTRUCTION) - live)
    assert not stale, f"allowances for assertions that no longer exist: {stale}"


def test_upak_has_no_document_specific_vacuous_allowance() -> None:
    """What replaced the mitigation for U-PAK's two allowances.

    Its gold expects `amount_payable: null` because refusing IS the right answer
    (F8: 14,789.77 printed against 14,740.85 payable, aging all zero, nothing
    explaining the 48.92), and an empty record coincidentally matched that. Two
    free passes, justified at the time by U-PAK's `confidence_modifiers`
    assertion requiring `arith_balance_mismatch` — a modifier only the refusal
    can emit.

    The printed-fields-only narrowing deferred all three: the two payable
    assertions, and the arithmetic modifier that was their non-vacuous gate. With
    nothing left to forgive, the allowances went too, and U-PAK is now covered by
    the general `test_no_assertion_passes_vacuously_on_an_empty_record` with no
    exceptions at all — strictly stronger than what it had.

    The invariant worth keeping is that the free passes do not creep back under
    another name.
    """
    upak = "northstar-upak-4378107"
    specific = sorted(k for k in VACUOUS_BY_CONSTRUCTION if k.startswith(f"{upak}:"))
    assert not specific, f"U-PAK regained a document-specific free pass: {specific}"

    assertions = assertions_for(next(g for g in GOLD if g["gold_id"] == upak))
    assert assertions, "U-PAK must still be measured by something"
