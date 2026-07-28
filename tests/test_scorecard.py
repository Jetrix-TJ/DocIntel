import pathlib
from docintel.scorecard import load_gold, replay_gold
from docintel.pipeline.hooks import HookRegistry
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_default_stages
from docintel.adapters.vision.fake import FakeVision

GOLD_DIR = pathlib.Path("docs/corpus/gold")


def _factory():
    return Runner(stages=build_default_stages(vision=FakeVision()), hooks=HookRegistry())


def test_loads_all_ten_gold_documents():
    assert len(load_gold()) == 10


def test_every_gold_source_file_exists():
    for gold in load_gold():
        assert (pathlib.Path("docs") / gold["source_file"]).exists(), gold["gold_id"]


def test_scorecard_shape():
    card = replay_gold(runner_factory=_factory)
    assert card["summary"]["total"] == 10
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
    assert card["summary"]["passed"] + card["summary"]["failed"] == 10
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


def test_centracom_assertions_include_the_trap():
    card = replay_gold(runner_factory=_factory)
    doc = next(d for d in card["documents"] if "centracom" in d["gold_id"])
    names = {a["name"] for a in doc["assertions"]}
    assert "derived.amount_payable" in names
    assert "derived.payable_basis" in names


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
    assert _field_kind("service_location", "Hunter Industries") == "text"


def test_a_non_string_gold_value_is_compared_exactly():
    """A boolean or a number that is not money must not be casefolded into a string."""
    from docintel.scorecard import _field_kind

    assert _field_kind("has_something", True) == "exact"
