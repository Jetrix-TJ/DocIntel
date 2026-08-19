"""`compare()` in isolation - hand-built `EvalRun`s, no history store, no
pipeline. Just: does a same-named assertion flipping pass->fail get named,
and does everything else (gains, unrelated docs, missing assertions) not.
"""

from __future__ import annotations

from docintel.evals.compare import Regression, compare
from docintel.evals.history import EvalRun


def _run(*docs) -> EvalRun:
    return EvalRun(
        id=1, suite="full_pipeline", label="x", vision_mode="cassette",
        run_at="2026-08-17T00:00:00", summary={}, documents=list(docs),
    )


def _doc(gold_id, **assertions):
    return {
        "gold_id": gold_id,
        "assertions": [{"name": name, "passed": passed} for name, passed in assertions.items()],
    }


def test_a_same_assertion_flipping_pass_to_fail_is_a_regression():
    baseline = _run(_doc("doc-a", **{"fields.vendor_name": True}))
    candidate = _run(_doc("doc-a", **{"fields.vendor_name": False}))

    regressions = compare(baseline, candidate)

    assert regressions == [Regression(
        gold_id="doc-a", assertion="fields.vendor_name",
        baseline_passed=True, candidate_passed=False,
    )]


def test_no_regressions_when_nothing_changed():
    baseline = _run(_doc("doc-a", **{"fields.vendor_name": True}))
    candidate = _run(_doc("doc-a", **{"fields.vendor_name": True}))

    assert compare(baseline, candidate) == []


def test_a_previously_failing_assertion_that_still_fails_is_not_a_regression():
    baseline = _run(_doc("doc-a", **{"fields.vendor_name": False}))
    candidate = _run(_doc("doc-a", **{"fields.vendor_name": False}))

    assert compare(baseline, candidate) == []


def test_a_candidate_gaining_a_pass_is_not_a_regression():
    baseline = _run(_doc("doc-a", **{"fields.vendor_name": False}))
    candidate = _run(_doc("doc-a", **{"fields.vendor_name": True}))

    assert compare(baseline, candidate) == []


def test_an_assertion_missing_entirely_from_the_candidate_is_not_a_regression():
    """A removed gold document or a renamed assertion is a different problem
    than "the same check got worse" - this function only names the latter."""
    baseline = _run(_doc("doc-a", **{"fields.vendor_name": True}))
    candidate = _run(_doc("doc-a"))  # no assertions at all

    assert compare(baseline, candidate) == []


def test_multiple_regressions_across_multiple_documents_are_all_named():
    baseline = _run(
        _doc("doc-a", **{"fields.vendor_name": True, "fields.total_printed": True}),
        _doc("doc-b", **{"doc_type": True}),
    )
    candidate = _run(
        _doc("doc-a", **{"fields.vendor_name": False, "fields.total_printed": True}),
        _doc("doc-b", **{"doc_type": False}),
    )

    regressions = compare(baseline, candidate)

    assert len(regressions) == 2
    assert Regression("doc-a", "fields.vendor_name", True, False) in regressions
    assert Regression("doc-b", "doc_type", True, False) in regressions


def test_an_unrelated_document_with_no_changes_contributes_no_regressions():
    baseline = _run(
        _doc("doc-a", **{"fields.vendor_name": True}),
        _doc("doc-b", **{"doc_type": True}),
    )
    candidate = _run(
        _doc("doc-a", **{"fields.vendor_name": False}),
        _doc("doc-b", **{"doc_type": True}),
    )

    regressions = compare(baseline, candidate)

    assert regressions == [Regression("doc-a", "fields.vendor_name", True, False)]
