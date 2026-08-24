"""GUARDRAIL 9 — DO NOT DELETE THIS FILE.

**Incomplete extraction must never be invisible.**

Before this guardrail existed, the confidence map was keyed by what the executor
*found* rather than by what the persona *declared*. `ExtractedFields.match_quality`
only gains a key inside `set()`, `s6_capture._score` iterates that map, and
`s7_gate._confidence_lane` iterates `ctx.confidence` — so the set of fields that
could lower a lane was a subset of the fields that had already succeeded. A field
that extracted nothing was not scored low; it was absent, and absence was
unrepresentable in the scoring vocabulary.

Measured consequence on the Comcast bill, with 14 of its 16 selectors deleted:

    fields populated  14 -> 2        lane   high -> high
    bill_to_name      set -> None    review False -> False
    modifiers          [] -> []      regen  False -> False

A document missing four-fifths of its data was auto-approved with no signal of any
kind. This matters because ordinary layout drift at a *known* vendor — a redesigned
invoice template — produces exactly that shape, and it is the dominant risk at
volume.

**Two mechanisms are needed, and neither substitutes for the other.** The tests
below pin both because each catches a failure the other cannot see:

* `required` on a selector catches *declared and produced nothing* — the
  hardcoded-literal case, where a rule keyed to `(Clyde Administration Servi)`
  silently returns nothing for a client onboarded last week.
* The pack's `required_fields` / `required_any_of` contract catches *not declared
  at all* — a persona whose rules were deleted or never finished. Selector-level
  `required` is blind here by construction: delete the selector and there is
  nothing left to be required.

**The fully-empty case was already safe** and is not what this file defends.
`s7_gate` has always routed an empty confidence map to `low`. The dangerous shape
is the *partial* one, where a handful of surviving fields all score well and the
document reads as clean.

If this test is failing, DO NOT relax it. Restoring `high` on a document that lost
most of its fields is how a template redesign becomes thousands of confidently
wrong payments.
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any

import pytest

from docintel.adapters.vision.fake import FakeVision
from docintel.grammar.schema import parse_persona
from digitaldirection import aliases as dd_aliases
from docintel.packs.registry import load_packs, register_all
from docintel.packs.store import PackPersonaStore
from docintel.pipeline.hooks import HookRegistry
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_default_stages

GOLD_PATH = os.path.join(
    "docs", "corpus", "gold", "digitaldirection-comcast-8495444620365242.json"
)

# A pattern that compiles under the section 3.2 restrictions and matches nothing
# on any real invoice. Standing in for "the vendor redesigned this template".
NO_MATCH = "(ZZ_NOT_ON_THIS_PAGE_ZZ)"


def _run(mutate: Any = None) -> dict[str, Any]:
    """Process the Comcast bill, optionally mutating its persona first.

    `mutate` receives the raw persona mapping and edits it in place. Mutating the
    raw JSON rather than the parsed object keeps the test honest: the persona still
    goes through `parse_persona`, so anything the schema would reject in
    production is rejected here too.
    """
    with open(GOLD_PATH) as fh:
        gold = json.load(fh)

    from digitaldirection import PACK as DIGITALDIRECTION_PACK

    packs = load_packs() + [DIGITALDIRECTION_PACK]
    hooks = HookRegistry()
    register_all(hooks, packs)
    store = PackPersonaStore(packs)

    if mutate is not None:
        key = next(k for k in store.keys if k[0] == "digitaldirection|comcast")
        raw = copy.deepcopy(store.raw(*key))
        mutate(raw)
        store._by_key[key] = parse_persona(raw)

    runner = Runner(
        stages=build_default_stages(
            vision=FakeVision(), hooks=hooks, packs=packs, store=store
        ),
        hooks=hooks,
    )
    return runner.process(
        document_id=gold["gold_id"],
        source_path=os.path.join("docs", gold["source_file"]),
    )


def _break_all_but(raw: dict[str, Any], keep: set[str]) -> None:
    """Make every selector outside `keep` match nothing, leaving its anchor alone.

    Only the pattern is touched. Removing the anchor as well would leave a
    `near-anchor` region with nothing to anchor to, which `regions.resolve` rejects
    as an authoring error - the document would dead-letter and the test would pass
    for a reason that has nothing to do with coverage. Keeping the anchor is also
    the truer simulation: after a template redesign the printed label is usually
    still there and it is the value beside it that moved.
    """
    for selector in raw["field_selectors"]:
        if "field" in selector and selector["field"] not in keep:
            selector["pattern"] = NO_MATCH


# -- the baseline, so the guard cannot pass by simply failing everything -------


@pytest.fixture(scope="module")
def shipped() -> dict[str, Any]:
    return _run()


def test_the_shipped_persona_still_reaches_the_fast_lane(shipped: dict) -> None:
    """The point of the guard is to fire on incompleteness, not on everything.

    Without this, every assertion below could be satisfied by a gate that routes
    all ten corpus documents to review.
    """
    assert shipped["lane"] == "high"
    assert shipped["review_flag"] is False
    assert shipped["extraction_coverage"]["complete"] is True
    assert shipped["extraction_coverage"]["missing_required"] == []


# -- mechanism 1: declared, required, produced nothing ------------------------


def test_a_required_selector_producing_nothing_does_not_auto_approve() -> None:
    """A required, declared selector that matches nothing on an otherwise
    perfect document is the hardcoded-literal failure the module docstring
    describes: a rule whose pattern stops matching after a template revision,
    silently.

    `account_number`'s selector is `required` (the schema default) and anchored
    on the printed `Account number` label; only its PATTERN is defeated here, so
    the anchor still resolves and `near-anchor` still has something to search -
    the same reasoning `_break_all_but` documents below for the wholesale-
    collapse test, applied to one field instead of "every field but two".

    **Formerly demonstrated via `bill_to_name` with the pack's roster emptied
    out**, because until Task 7 that was the only way to make a required field
    on this document produce nothing: Comcast's template prints no bill-to
    label at all, so `resolve_bill_to_alias`'s roster fallback was the SOLE
    source of `bill_to_name`, and an unrostered client meant the field came back
    empty - a real instance of this mechanism, just reached through the roster
    rather than through a selector. Task 7 gave Comcast a real `bill_to_name`
    selector (region `top-left`, no anchor - the printed name has none) that
    reads the name directly off the page regardless of the roster, so an
    unrostered client no longer leaves the field empty; it leaves it POPULATED
    but disagreeing with the roster instead. That is a real behavior change,
    not a test artifact - see `test_an_unrostered_bill_to_forces_review` below,
    which pins the new shape. `account_number` has no roster involved at all,
    so it stays a clean, roster-independent vehicle for THIS mechanism
    regardless of what happens to any bill-to selector on any persona.
    """
    def defeat_account_number(raw: dict[str, Any]) -> None:
        for selector in raw["field_selectors"]:
            if selector.get("field") == "account_number":
                selector["pattern"] = NO_MATCH

    record = _run(defeat_account_number)

    assert record["fields"].get("account_number") is None, (
        "the test did not achieve the condition it is asserting about"
    )
    assert record["derived"].get("account_number") is None
    assert record["lane"] != "high", (
        "a required field extracted nothing and the document was auto-approved"
    )
    assert record["review_flag"] is True
    assert "account_number" in record["extraction_coverage"]["missing_required"]


# -- the wrong-inbox guard: since Task 7, an unrostered bill-to is CAPTURED, ---
# -- not silently missing - and still forces review ----------------------------


def test_an_unrostered_bill_to_forces_review(monkeypatch) -> None:
    """Since Task 7, Comcast's `bill_to_name` is read directly off the printed
    page (no label; isolated cleanly by the `top-left` region, which nothing
    else in that box competes for) rather than being supplied only by the
    pack's roster fallback. An unrostered / wrong-inbox client therefore no
    longer shows up as a MISSING field (mechanism 1, above) - the printed name
    is captured exactly as it appears - it shows up as a MISMATCHED one:
    `resolve_bill_to_alias` compares the printed value against the pack's
    roster (`MANAGED_CLIENTS`) and tags `bill_to_mismatch`, which
    `s7_gate.DEFAULT_FORCED_REVIEW_TAGS` routes to `review` unconditionally -
    the same outcome the old missing-field path produced, reached a different
    way. This is what makes the wrong-inbox guard reachable for Comcast at
    all: before Task 7, the roster fallback (`_roster_match`) could only ever
    return a name already ON the roster, so it could never disagree with
    itself and `bill_to_mismatch` was structurally unreachable for this
    persona.
    """
    monkeypatch.setattr(dd_aliases, "MANAGED_CLIENTS", ("Somebody Else Entirely",))
    record = _run()

    assert record["fields"].get("bill_to_name") == "Clyde Administration Servi", (
        "the test did not achieve the condition it is asserting about - the "
        "printed name should still be captured even when it is not on the "
        "roster"
    )
    assert "bill_to_mismatch" in record["tags"]
    assert record["lane"] != "high", (
        "an unrostered bill-to disagreed with the pack's roster and the "
        "document was auto-approved anyway"
    )
    assert record["review_flag"] is True


# -- mechanism 2: never declared at all ---------------------------------------


def test_a_persona_stripped_of_its_rules_does_not_auto_approve() -> None:
    """The §4 experiment. Every surviving selector matches perfectly, so nothing
    in the confidence map is low — the only evidence of a problem is what is
    *absent* from it. Selector-level `required` cannot see this: the selectors
    that would have been required are gone."""
    def strip(raw: dict[str, Any]) -> None:
        raw["field_selectors"] = [
            s for s in raw["field_selectors"]
            if s.get("field") in {"account_number", "total_printed"}
        ]

    record = _run(strip)

    # Task 11: derive_amount_payable is now wired on total_printed's adjust
    # list for every persona, and it is a DOCUMENT-level op - it fires
    # whenever total_printed survives, regardless of whether please_pay/
    # current_charges/prior_balance have selectors at all. A persona
    # stripped to {account_number, total_printed} now legitimately produces
    # THREE confidence entries: the two surviving selectors plus the
    # derived amount_payable that total_printed's adjust list always
    # carries. Not a guardrail weakening - account_number/total_printed
    # are still the only SELECTOR-sourced entries, and the actual guard
    # (lane, review_flag, extraction_coverage below) is untouched.
    assert len(record["confidence"]) == 3, (
        "the test did not achieve the condition it is asserting about"
    )
    assert all(score >= 0.90 for score in record["confidence"].values()), (
        "this case only bites when the surviving fields score WELL"
    )
    assert record["lane"] != "high", (
        "81% of the rules were deleted and the document was auto-approved"
    )
    assert record["review_flag"] is True
    assert record["extraction_coverage"]["complete"] is False


# -- collapse: the rules are wrong, not the document --------------------------


def test_a_wholesale_layout_change_asks_for_the_rules_to_be_regenerated() -> None:
    """When most declared selectors stop matching, the actionable conclusion is
    that the persona no longer describes this template — which is what `low` plus
    `regen_flag` says. `review` alone would send a human to re-key the document by
    hand every month instead of fixing the rule set once."""
    record = _run(lambda raw: _break_all_but(raw, {"account_number", "total_printed"}))

    assert record["lane"] == "low"
    assert record["regen_flag"] is True
    assert record["review_flag"] is True


def test_one_missing_field_is_not_a_collapse(monkeypatch) -> None:
    """`low` triggers a rule rewrite, so it must stay rare. A single isolated
    anomaly is a gap in one rule (or, since Task 7, one mismatched bill-to - see
    `test_an_unrostered_bill_to_forces_review` above), not a broken persona."""
    monkeypatch.setattr(dd_aliases, "MANAGED_CLIENTS", ("Somebody Else Entirely",))
    record = _run()
    assert record["lane"] == "review"
    assert record["regen_flag"] is False


# -- the record must carry the evidence ---------------------------------------


def test_the_coverage_block_is_machine_readable(shipped: dict) -> None:
    """A downstream consumer must be able to learn *which* fields were missed
    without parsing prose out of `reason`."""
    coverage = shipped["extraction_coverage"]
    assert set(coverage) == {"declared", "populated", "missing_required", "complete"}
    assert isinstance(coverage["declared"], int)
    assert isinstance(coverage["populated"], int)
    assert isinstance(coverage["missing_required"], list)
    assert isinstance(coverage["complete"], bool)
    assert coverage["declared"] >= coverage["populated"]
