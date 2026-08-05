import pathlib
from docintel.scorecard import load_gold, replay_gold
from docintel.pipeline.hooks import HookRegistry
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_default_stages
from docintel.adapters.vision.fake import FakeVision

GOLD_DIR = pathlib.Path("docs/corpus/gold")


def _factory():
    return Runner(stages=build_default_stages(vision=FakeVision()), hooks=HookRegistry())


def test_loads_every_gold_document():
    # The gold corpus is a growing set, not a fixed size - assert load_gold()
    # reads everything on disk, independently globbed, rather than pin a count
    # that goes stale the next time a document is added.
    on_disk = len(list(GOLD_DIR.glob("*.json")))
    assert on_disk > 0
    assert len(load_gold()) == on_disk


def test_every_gold_source_file_exists():
    for gold in load_gold():
        assert (pathlib.Path("docs") / gold["source_file"]).exists(), gold["gold_id"]


def test_scorecard_shape():
    card = replay_gold(runner_factory=_factory)
    assert card["summary"]["total"] == len(load_gold())
    assert set(card["summary"]) == {"total", "passed", "failed", "assertions_passed",
                                    "assertions_total"}
    for doc in card["documents"]:
        assert {"gold_id", "passed", "assertions", "passed_count", "total_count"} <= set(doc)


def test_scorecard_actually_evaluates_assertions():
    """Guards the instrument, not the score.

    Deliberately does NOT assert a specific failing count: the whole point of
    Part B is to drive that count down, so pinning it would make this test fail
    on every successful iteration.
    """
    card = replay_gold(runner_factory=_factory)
    assert card["summary"]["assertions_total"] > 50
    assert card["summary"]["passed"] + card["summary"]["failed"] == len(load_gold())
    assert all("passed" in a for d in card["documents"] for a in d["assertions"])


def test_money_assertions_compare_by_value_not_by_string():
    """Gold holds 33876.4; the record serializes "33876.40". Same amount."""
    from docintel.scorecard import matches
    assert matches(33876.4, "33876.40", kind="money") is True
    assert matches(83.79, "83.7900", kind="money") is True
    assert matches(33876.4, "13752.60", kind="money") is False
    assert matches(None, None, kind="money") is True
    assert matches(69.62, None, kind="money") is False
    # exact kind stays strict
    assert matches("current_charges", "current_charges", kind="exact") is True
    assert matches(33876.4, "33876.40", kind="exact") is False


def test_the_centracom_trap_is_caught_not_silently_dropped():
    """The trap this used to assert as deferred, now caught for real.

    Centracom prints 33,876.40 and owes 13,752.60. Before Task 11, the printed-
    fields-only narrowing retired the derived-payable assertions entirely, so
    collapsing the derivation into "read the total" would have shown up nowhere
    - the guard was two-sided: the assertions gone, AND the gold facts behind
    them classified as deferred rather than forgotten. Task 11 re-wires
    derive_amount_payable and re-asserts both fields, so the trap is caught the
    direct way again: a wrong derivation now fails `derived.amount_payable`
    against gold's 13,752.60, not a deferral-table entry.
    """
    from docintel.scorecard import GOLD_ASSERTION_COVERAGE

    card = replay_gold(runner_factory=_factory)
    doc = next(d for d in card["documents"] if "centracom" in d["gold_id"])
    names = {a["name"] for a in doc["assertions"]}
    assert "derived.amount_payable" in names
    assert "derived.payable_basis" in names

    # Not asserting `passed is True` here: this file's `_factory()` builds a
    # bare Runner with no packs/persona store (`PersonaLookup(store=None)` is a
    # hard miss for every document), so no persona - and therefore no
    # derivation - ever actually runs in this harness. The real derivation is
    # exercised and asserted correct by `docintel.cli replay-gold`'s full
    # pipeline (see the Task 11 commit's before/after numbers) and by
    # `grammar/ops/derive.py`'s own unit tests. What this harness CAN prove is
    # the scorecard wiring: the assertion exists and carries the right verdict.

    for check, verdict in (
        ("amount_payable", "wired:derived.amount_payable"),
        ("payable_basis", "wired:derived.payable_basis"),
        ("payable_mismatch", "wired:derived.amount_payable"),
        ("balance_composition", "documentation"),
    ):
        assert GOLD_ASSERTION_COVERAGE[check] == verdict, (
            f"{check} does not carry its Task 11 verdict — expected {verdict!r}"
        )


def test_replay_never_mutates_gold():
    before = {p.name: p.read_bytes() for p in GOLD_DIR.glob("*.json")}
    replay_gold(runner_factory=_factory)
    after = {p.name: p.read_bytes() for p in GOLD_DIR.glob("*.json")}
    assert before == after, "gold files are READ-ONLY to the loop"


# ==========================================================================
# The `text` comparison kind (decided in C5b)
# ==========================================================================


def test_transcribed_text_compares_case_insensitively():
    """EDCO prints `EDCO WASTE & RECYCLING SERVICE`; its gold label reads
    `EDCO Waste & Recycling Service`. The document is all-caps and the labeller
    title-cased it, so the extraction is CORRECT and a scorecard that failed here
    would be measuring the labeller's typing."""
    from docintel.scorecard import matches

    assert matches(
        "EDCO Waste & Recycling Service", "EDCO WASTE & RECYCLING SERVICE", "text"
    )


def test_transcribed_text_collapses_whitespace():
    from docintel.scorecard import matches

    assert matches("Hunter Industries", "Hunter   Industries", "text")


def test_transcribed_text_does_NOT_normalize_punctuation():
    """A missing comma is a different transcription, not a different case.
    Collapsing that would stop the assertion measuring how well an address was
    captured at all."""
    from docintel.scorecard import matches

    assert not matches(
        "260 S Pacific St, San Marcos, CA 92078",
        "260 S PACIFIC ST SAN MARCOS CA 92078",
        "text",
    )


def test_transcribed_text_still_fails_on_a_genuinely_wrong_value():
    from docintel.scorecard import matches

    assert not matches("EDCO Waste", "Acme Widgets", "text")


def test_a_missing_value_is_not_matched_by_text_comparison():
    from docintel.scorecard import matches

    assert not matches("EDCO Waste", None, "text")
    assert matches(None, None, "text")


def test_our_own_vocabulary_stays_case_sensitive():
    """`payable_basis` and friends are enums the pipeline emits, not text read off
    a page. Accepting `Current_Charges` for `current_charges` would stop catching a
    typo in code we wrote."""
    from docintel.scorecard import EXACT_TEXT_FIELDS, _field_kind

    assert _field_kind("currency", "USD") == "exact"
    assert _field_kind("currency_basis", "pack_default") == "exact"
    assert _field_kind("prior_balance_basis", "gross") == "exact"
    assert "currency_basis" in EXACT_TEXT_FIELDS


def test_money_fields_are_never_compared_as_text():
    from docintel.scorecard import _field_kind

    assert _field_kind("total_printed", 699.0) == "money"


def test_a_transcribed_field_gets_the_text_kind():
    from docintel.scorecard import _field_kind

    assert _field_kind("vendor_name", "D.T.S.S., Inc.") == "text"
    assert _field_kind("payment_terms", "Due on receipt") == "text"
    # `service_location` moved to the `address` kind - it is a site description
    # whose punctuation gold normalizes the same way it does a postal address.
    assert _field_kind("service_location", "Hunter Industries") == "address"


def test_a_non_string_gold_value_is_compared_exactly():
    """A boolean or a number that is not money must not be casefolded into a string."""
    from docintel.scorecard import _field_kind

    assert _field_kind("has_something", True) == "exact"


# ==========================================================================
# The `address` comparison kind
# ==========================================================================


def test_an_address_forgives_the_comma_gold_inserts():
    """Gold systematically adds a comma between city and state that the documents
    do not print. `join_lines_comma` joins LINES, so no op can insert one inside a
    line - and an address is the same address whichever way the punctuation falls."""
    from docintel.scorecard import matches

    assert matches(
        "PO Box 1550, Durant, OK 74702-1550", "PO BOX 1550, DURANT OK 74702-1550",
        "address",
    )
    assert matches(
        "387 S 520 W STE 210, Lindon, UT 84042-1960",
        "387 S 520 W STE 210, LINDON UT 84042-1960",
        "address",
    )


def test_an_address_does_NOT_forgive_extra_content():
    """The property that keeps the assertion meaningful. An over-reaching capture
    pulls the next block into the value, and that must still fail."""
    from docintel.scorecard import matches

    assert not matches(
        "5555 Perimeter Dr, Dublin, OH 43017-3219",
        "5555 PERIMETER DR, DUBLIN OH 43017-3219, How to reach Lumen:",
        "address",
    )


def test_an_address_does_NOT_forgive_missing_content():
    from docintel.scorecard import matches

    assert not matches(
        "500 North Defiance Trail, Spencerville, OH 45887",
        "500 North Defiance Trail",
        "address",
    )


def test_an_address_does_not_forgive_a_wrong_address():
    from docintel.scorecard import matches

    assert not matches("PO Box 188, East Longmeadow, MA 01028",
                       "PO Box 7, Fairview, UT 84629", "address")


def test_address_fields_get_the_address_kind():
    from docintel.scorecard import _field_kind

    for name in ("bill_to_address", "vendor_address", "remit_address",
                 "return_address", "service_location"):
        assert _field_kind(name, "somewhere") == "address"


def test_a_company_name_is_not_treated_as_an_address():
    """`remit_payee` is a legal entity, and `Level 3 Communications, LLC` versus
    `Level 3 Communications LLC` is a different name, not different punctuation."""
    from docintel.scorecard import _field_kind

    assert _field_kind("remit_payee", "Level 3 Communications, LLC") == "text"
