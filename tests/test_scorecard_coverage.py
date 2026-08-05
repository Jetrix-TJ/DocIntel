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
    CHECKED_FIELDS_BY_GOLD,
    DEFERRED_ARITHMETIC_MODIFIERS,
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

# Gold `derived` keys the printed-fields-only narrowing retired. Empty since
# Task 11 re-enabled both of DERIVED_ONLY's non-identity names. Kept as a
# named, typed constant (rather than deleted) so a future deferral has an
# obvious place to add a key, and so `test_the_deferred_derived_list_holds_only_derived_only_names`
# keeps meaning something.
DEFERRED_DERIVED_KEYS: frozenset[str] = frozenset()

# Thirteen `CHECKED_FIELDS` names stopped being extractable when Tasks 3 and 4
# narrowed the two packs. "No pack extracts it" is one fact with three quite
# different causes underneath, and collapsing them into one list hid the third.
# Split so the states stay distinguishable and only two of them buy an exemption.

# 1. Genuinely derived: computed from other values, never ink on the page. The
#    `*_normalized` pair is stripped from a printed key, `carrier_canonical` is
#    the alias table's output, `currency_basis` names the F14 ladder rung that
#    answered, `prior_balance_basis` is a vendor convention's classification.
#    These would not be extractable however good the personas were.
DEFERRED_DERIVED_FIELDS: frozenset[str] = frozenset({
    "account_number_normalized",
    "vendor_account_number_normalized",
    "carrier_canonical",
    "currency_basis",
    "prior_balance_basis",
})

# 2. Printed, and extracted by a working selector on at least one document right
#    up until the narrowing dropped it. These left for deliverability, not
#    because they are unprintable, so this is the list that shrinks when scope
#    widens again.
#
#    "on at least one document" is the honest wording, and the earlier "extracted
#    by a working selector right up until the narrowing" was not. `vendor_email`
#    is the counter-example: Lumen had a selector, `complete_beverage.json` never
#    did, and that half was FAILING when it was retired - so it is debt and it is
#    back in the denominator via `scorecard.CHECKED_FIELDS_BY_GOLD`.
#
#    `currency` needs the same care. Lumen printed a literal `(USD)` and
#    `federal_recycling.json` had a selector too, but eight of the ten
#    `fields.currency` passes came from `infer_currency` writing to `derived`
#    rather than from ink - the scorecard's `_field_value` looks in `derived`
#    when `fields` is empty, which is why they scored at all. So `currency` is
#    only partly a printed field, and re-widening scope would recover two
#    documents by selector and the rest only by re-enabling the F14 ladder.
DEFERRED_PRINTED_FIELDS: frozenset[str] = frozenset({
    "billing_group",
    "currency",
    "vendor_email",
    "vendor_legal_name",
    "vendor_phone",
    "vendor_website",
})

# What the gold-coverage test will accept as accounted for. Gold is read-only and
# keeps the evidence for all of them, so re-enabling either group is a wiring
# change rather than a re-labelling project.
DEFERRED_FIELDS: frozenset[str] = DEFERRED_DERIVED_FIELDS | DEFERRED_PRINTED_FIELDS

# 3. Printed, gold-labelled, and never given a selector in any persona - not by
#    this narrowing, not before it. `tax_id` is U-PAK's H.S.T. number and
#    `vendor_parent_reference` is the `a CenturyLink company` clause printed
#    beside Lumen's legal name; both were verified as literal page text.
#
#    These are NOT deferred. They were failing every run before this spec touched
#    anything, and moving them into DEFERRED_FIELDS would have deleted a
#    pre-existing coverage gap from the denominator and called it a spec
#    decision - raising the rate by measuring less. They stay in CHECKED_FIELDS,
#    stay failing, and this list exists to make growing it feel expensive: every
#    name here is a field somebody should have written a selector for.
#
#    Both are REGISTERED in their pack's `FIELDS` and neither has a selector.
#    That combination is the point, and getting it wrong once already made the
#    debt unpayable: V1 rejects a selector targeting an unregistered field, so
#    while these names were out of `FIELDS` nobody could pay the debt without
#    first re-widening the field set. See the third assertion in
#    `test_extraction_debt_is_measured_rather_than_deferred`.
EXTRACTION_DEBT: frozenset[str] = frozenset({
    "tax_id",
    "vendor_parent_reference",
})

# 3b. The same debt, where it belongs to one DOCUMENT rather than to a name.
#     `vendor_email` is a deferral on Lumen (a working selector, an assertion
#     that was passing) and debt on Complete Beverage (no selector ever, an
#     assertion that was failing when it was retired). Mirrors
#     `scorecard.CHECKED_FIELDS_BY_GOLD`, which puts the failing half back.
DOCUMENT_SCOPED_EXTRACTION_DEBT: dict[str, frozenset[str]] = {
    "northstar-complete-beverage-32930": frozenset({"vendor_email"}),
}

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
    # U-PAK's gold expects a null payable because refusing IS the right answer
    # (F8). An empty record matches by coincidence. The non-vacuous gate on the
    # same behaviour is its `confidence_modifiers` assertion, which requires
    # `arith_balance_mismatch` and cannot be satisfied without the derivation
    # actually running and refusing - see test_upak_cannot_go_green_on_its_vacuous_assertions_alone.
    "northstar-upak-4378107:derived.amount_payable": "null IS the correct answer (F8)",
    "northstar-upak-4378107:derived.payable_basis": "null IS the correct answer (F8)",
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
    """`document_identity`/`identity_basis` are Stage 8 contract keys carrying
    pipeline provenance, required to be PRESENT by core/contract.py.
    `amount_payable`/`payable_basis` are the other two names DERIVED_ONLY has
    ever held, and Task 11 wired them back into the scorecard on purpose -
    both are exceptions for a reason, not by oversight.
    """
    from docintel.core.models import DERIVED_ONLY

    retained = {"document_identity", "identity_basis", "amount_payable", "payable_basis"}
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
    emitted |= {
        f"fields.{name}"
        for names in CHECKED_FIELDS_BY_GOLD.values()
        for name in names
    }
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
    all ten files. `currency_basis` is C3's own output.

    Three accounts now, not two: asserted, declared prose, or named in
    DEFERRED_FIELDS because no pack registers the name any more. The third is
    held honest by test_the_deferred_field_list_holds_only_unextractable_names.
    """
    unchecked: dict[str, int] = {}
    for gold in GOLD:
        for name, value in (gold.get("fields") or {}).items():
            if value is None or name in CHECKED_FIELDS or name in PROSE_FIELDS:
                continue
            if name in DEFERRED_FIELDS:
                continue
            unchecked[name] = unchecked.get(name, 0) + 1
    assert not unchecked, (
        f"gold fields present but never asserted: {sorted(unchecked)}. "
        "Add them to scorecard.CHECKED_FIELDS, or to DEFERRED_FIELDS here if no "
        "pack registers the name, or to PROSE_FIELDS if it is labeller prose."
    )


def test_the_deferred_field_list_holds_only_unextractable_names() -> None:
    """An entry here for a field a pack still extracts is a free pass, not a
    deferral — it would hide a real extraction failure behind a spec decision."""
    from docintel.packs.digitaldirection import fields as dd
    from docintel.packs.northstar import fields as ns

    assert not (DEFERRED_FIELDS & (ns.FIELDS | dd.FIELDS))
    assert not (DEFERRED_FIELDS & set(CHECKED_FIELDS))


def test_the_two_deferral_reasons_stay_separate() -> None:
    """The split is the point: one list is "cannot be printed", the other is
    "was printed and we stopped reading it", and they are undone by different
    work. A name in both would mean nobody had decided which."""
    assert not (DEFERRED_DERIVED_FIELDS & DEFERRED_PRINTED_FIELDS)
    assert DEFERRED_FIELDS == DEFERRED_DERIVED_FIELDS | DEFERRED_PRINTED_FIELDS


def test_extraction_debt_is_measured_rather_than_deferred() -> None:
    """The guard the disjointness pin cannot give us.

    `DEFERRED_FIELDS` is pinned disjoint from both packs' `FIELDS` — but that is
    exactly the property a printed field nobody ever wrote a selector for has, so
    the pin would wave one straight through. What separates the two is that a
    deferral was a decision and this is a gap, so the gap stays in the
    denominator where it goes on costing something.
    """
    from docintel.packs.digitaldirection import fields as dd
    from docintel.packs.northstar import fields as ns

    assert not (EXTRACTION_DEBT & DEFERRED_FIELDS), (
        "extraction debt moved into a deferral list — that hides a real gap "
        "behind a spec decision and silently raises the score"
    )
    assert EXTRACTION_DEBT <= set(CHECKED_FIELDS), (
        "extraction debt must stay asserted, and therefore stay failing, until "
        "somebody writes the selector"
    )
    # Registered, selectable, and nobody has done it yet.
    #
    # INVERTED from `not (EXTRACTION_DEBT & (ns.FIELDS | dd.FIELDS))`, which was
    # backwards and made the debt UNPAYABLE. These names are held out of the
    # deferral lists precisely because they are printed, and V1 rejects a
    # selector targeting an unregistered field — so pinning them OUT of `FIELDS`
    # meant the only way to pay the debt was to first undo the pin. It also
    # contradicted the design's own mechanical test, "a field is in scope if a
    # selector can read it off the page".
    assert EXTRACTION_DEBT <= (ns.FIELDS | dd.FIELDS), (
        "extraction debt must be REGISTERED so a selector can target it; "
        "un-registering it makes the debt unpayable rather than smaller"
    )


def test_no_persona_has_quietly_paid_the_extraction_debt() -> None:
    """The other half of `EXTRACTION_DEBT <= FIELDS`: registered is not selected.

    Registering the names re-opens the door a selector walks through, and a
    selector appearing without this list shrinking would leave the scorecard
    describing a gap that has been closed. Either is a diff worth arguing about;
    neither should happen silently.
    """
    import glob
    import json
    import os

    selected: dict[str, list[str]] = {}
    pattern = os.path.join("src", "docintel", "packs", "*", "personas", "*.json")
    paths = sorted(glob.glob(pattern))
    assert len(paths) == 10, f"expected ten personas, found {len(paths)}"
    for path in paths:
        with open(path) as fh:
            persona = json.load(fh)
        for selector in persona.get("field_selectors") or []:
            name = selector.get("field")
            if name in EXTRACTION_DEBT:
                selected.setdefault(name, []).append(os.path.basename(path))

    assert not selected, (
        f"a persona now selects extraction debt: {selected}. If the selector "
        "works, take the name out of EXTRACTION_DEBT in the same change; the "
        "list is only honest while every name in it is still failing."
    )


def test_document_scoped_extraction_debt_is_wired_and_still_failing() -> None:
    """`vendor_email` on Complete Beverage: the assertion I2 found swept away.

    Of the 77 assertions the narrowing removed from the denominator, 75 were
    passing and 2 were failing. One of the two — edco's
    `vendor_account_number_normalized` — is genuinely derived and leaves whatever
    happens. This one is not: `complete_beverage.json` never had a selector for
    `vendor_email`, so it was extraction debt being retired as a spec decision,
    which raises the rate by measuring less.
    """
    assert DOCUMENT_SCOPED_EXTRACTION_DEBT == {
        gold_id: frozenset(names)
        for gold_id, names in CHECKED_FIELDS_BY_GOLD.items()
    }, "the test's view of the document-scoped debt and the scorecard's disagree"

    for gold_id, names in DOCUMENT_SCOPED_EXTRACTION_DEBT.items():
        gold = next((g for g in GOLD if g["gold_id"] == gold_id), None)
        assert gold is not None, f"{gold_id} is not a gold document"
        emitted = {a.name for a in assertions_for(gold)}
        for name in names:
            assert gold["fields"].get(name) is not None, (
                f"{gold_id} does not label {name}, so asserting it measures nothing"
            )
            assert name not in CHECKED_FIELDS, (
                f"{name} is checked on every document already; scoping it to "
                f"{gold_id} would assert it twice"
            )
            assert f"fields.{name}" in emitted, (
                f"{gold_id}:fields.{name} is declared as debt but never asserted"
            )


# The three deferral buckets, pinned literally.
#
# `test_extraction_debt_is_measured_rather_than_deferred` asserts disjointness
# and subset properties, and a reviewer demonstrated that all of them are
# satisfied BY CONSTRUCTION by anybody who moves a name from one bucket to
# another: the bucket shrinks at the same moment the other grows, so every
# relation still holds. Moving `tax_id` out of the debt list left 95 relevant
# tests green while the denominator fell from 262 to 261.
#
# So the contents are pinned literally, following `VACUOUS_BY_CONSTRUCTION`.
# Growing a bucket, shrinking one, or moving a name between them is then a
# visible diff line here that has to be argued for in a commit message.
PINNED_DEFERRED_DERIVED_FIELDS = frozenset({
    "account_number_normalized",
    "carrier_canonical",
    "currency_basis",
    "prior_balance_basis",
    "vendor_account_number_normalized",
})
PINNED_DEFERRED_PRINTED_FIELDS = frozenset({
    "billing_group",
    "currency",
    "vendor_email",
    "vendor_legal_name",
    "vendor_phone",
    "vendor_website",
})
PINNED_EXTRACTION_DEBT = frozenset({"tax_id", "vendor_parent_reference"})


def test_the_three_buckets_have_exactly_these_contents() -> None:
    """Re-bucketing a failure must cost a diff line, not nothing at all."""
    assert DEFERRED_DERIVED_FIELDS == PINNED_DEFERRED_DERIVED_FIELDS
    assert DEFERRED_PRINTED_FIELDS == PINNED_DEFERRED_PRINTED_FIELDS
    assert EXTRACTION_DEBT == PINNED_EXTRACTION_DEBT
    assert DOCUMENT_SCOPED_EXTRACTION_DEBT == {
        "northstar-complete-beverage-32930": frozenset({"vendor_email"}),
    }


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


def test_amount_payable_and_payable_basis_are_asserted() -> None:
    """Task 11: the scorecard must actually measure the newly-wired capability.

    Re-enabling derive_amount_payable without widening CHECKED_DERIVED would
    make the pipeline compute the right answer while the scorecard kept
    silently ignoring it - the exact class of blind spot this file exists to
    catch (see the module docstring).
    """
    from docintel.scorecard import CHECKED_DERIVED

    assert "amount_payable" in CHECKED_DERIVED
    assert "payable_basis" in CHECKED_DERIVED


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


def test_the_deferred_arithmetic_modifiers_are_real_modifiers() -> None:
    """The only deferral bucket that had no pin at all.

    `DEFERRED_ARITHMETIC_MODIFIERS` subtracts from `_expected_modifiers`, so a
    name added here removes an expectation from the numerator AND the
    denominator — the same mechanism as a deferred field, with none of the
    guards. A typo would remove nothing and pass silently; a real modifier added
    by mistake would remove a live expectation and also pass silently.
    """
    unknown = sorted(DEFERRED_ARITHMETIC_MODIFIERS - set(MODIFIERS))
    assert not unknown, (
        f"{unknown} are not modifiers, so deferring them defers nothing — "
        "check the spelling against core.confidence.MODIFIERS"
    )


def test_every_deferred_modifier_comes_from_an_op_this_spec_unwired() -> None:
    """The membership rule, not just the spelling.

    A modifier may be deferred here only because the printed-fields-only
    narrowing unwired the op that emits it. Both of those ops live in
    `grammar/ops/`, and their code stays in the tree — so "which ops emit this
    name" is a question the source can answer, and the answer must be the two
    deferred files rather than, say, a stage that still runs.
    """
    import pathlib

    root = pathlib.Path("src") / "docintel"
    deferred_sources = {
        root / "grammar" / "ops" / "crosscheck.py",
        root / "grammar" / "ops" / "derive.py",
    }
    for path in deferred_sources:
        assert path.exists(), f"{path} was deleted; deferral means kept, not removed"

    for name in sorted(DEFERRED_ARITHMETIC_MODIFIERS):
        emitters = {
            path
            for path in root.rglob("*.py")
            for call in (f'add_modifier("{name}")', f'add_field_modifier(field, "{name}")')
            if call in path.read_text()
        }
        assert emitters, f"nothing emits {name}; it cannot be deferred from anywhere"
        stray = sorted(str(p) for p in emitters - deferred_sources)
        assert not stray, (
            f"{name} is also emitted from {stray}, which this spec did not "
            "unwire — deferring it there hides a live capability"
        )


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


def test_upak_cannot_go_green_on_its_vacuous_assertions_alone() -> None:
    """The mitigation that makes U-PAK's two allowances acceptable.

    Its gold expects `amount_payable: null` because refusing IS the right answer
    (F8: 14,789.77 printed against 14,740.85 payable, aging all zero, nothing
    explaining the 48.92). An empty record coincidentally matches that. What an
    empty record CANNOT match is the modifier the refusal must emit, so U-PAK
    still has a non-vacuous gate on the same behaviour.
    """
    upak = next(g for g in GOLD if g["gold_id"] == "northstar-upak-4378107")
    modifier_assertions = [
        a for a in assertions_for(upak) if a.name == "confidence_modifiers"
    ]
    assert modifier_assertions, "U-PAK must assert the refusal's modifier"
    assert "arith_balance_mismatch" in modifier_assertions[0].expected
