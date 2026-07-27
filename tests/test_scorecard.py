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
