"""Champion/challenger: a pure diff over two stored eval runs.

No new scoring logic - `docintel.evals.history.EvalHistoryStore` already
stores each run's full per-assertion detail (`EvalRun.documents`), so
comparing "did anything that used to pass now fail" is just an index lookup
over two already-computed cards. This is the reusable half of the
champion/challenger mechanism `docs/architecture/pipeline-v2.md` names -
live automated *regeneration* (an agent proposing new rules, this gate
deciding whether they ship) isn't built; a human editing a persona today can
already use this directly (`replay-gold --record-history` before and after,
then `eval-compare`).
"""

from __future__ import annotations

from dataclasses import dataclass

from docintel.evals.history import EvalRun


@dataclass(frozen=True)
class Regression:
    gold_id: str
    assertion: str
    baseline_passed: bool
    candidate_passed: bool


def _index(run: EvalRun) -> dict[tuple[str, str], bool]:
    return {
        (doc["gold_id"], assertion["name"]): assertion["passed"]
        for doc in run.documents
        for assertion in doc["assertions"]
    }


def compare(baseline: EvalRun, candidate: EvalRun) -> list[Regression]:
    """Every `(gold_id, assertion)` that passed in `baseline` and explicitly
    failed in `candidate`. The candidate may freely gain passes, and an
    assertion absent from the candidate entirely (a removed gold document, a
    renamed assertion) is not itself a regression here - only a same-named
    assertion that is provably worse counts.
    """
    baseline_index = _index(baseline)
    candidate_index = _index(candidate)

    regressions = []
    for (gold_id, name), was_passing in baseline_index.items():
        if not was_passing:
            continue
        now_passing = candidate_index.get((gold_id, name))
        if now_passing is False:
            regressions.append(Regression(
                gold_id=gold_id, assertion=name,
                baseline_passed=True, candidate_passed=False,
            ))
    return regressions
