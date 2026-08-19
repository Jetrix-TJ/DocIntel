"""Isolated Stage 5b eval: field accuracy of the vision one-shot extractor
against the gold set, forced on every document regardless of whether it
would actually collapse to vision under normal routing.

This is the "Vision one-shot eval" suite named in `docs/architecture/
pipeline-v2.md` (Part 7) - guards the fallback path every first-time and
collapsed document rides on. Previously unmeasured in isolation: only
exercised implicitly, and only for whichever gold documents happened to
escalate, during a full `scorecard.replay_gold` run.

Dependency named, not silently worked around: `tests/fixtures/cassettes/
corpus.json` has zero entries today (Bug 5, `docs/BUGS-FEATURES-PRODUCTION.
md`) - the vision path has never been exercised against a real model. This
suite is fully buildable and testable now against `--vision fake` (an
honest, near-zero report that proves the harness) and gets real signal for
free the moment a real cassette entry exists - not fixed here.

Deliberately does NOT call `Runner.process()` - same reasoning as
`gate_eval.py`: this needs `ctx.extracted` state after a forced Stage 5b
call, not a built/validated record. The "forced" part needs no special
handling: `VisionOneShot.run()` only short-circuits when
`ctx.extraction_route == "5a_cached"`, and that never gets set because
`apply_cached_rules` (Stage 5a) is deliberately excluded from the stage
slice run here - stopping one stage short of it is what "forced" means.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from docintel.core.models import JobContext, new_context
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages.s5b_vision import DEFAULT_FIELDS, VisionOneShot
from docintel.scorecard import DOCS_DIR, _field_kind, load_gold, matches

# Through persona lookup, and no further - Stage 5a (apply_cached_rules) is
# excluded on purpose, see module docstring.
_UPSTREAM_STAGE_NAMES = frozenset({"intake", "attachment_filter", "classify", "persona_lookup"})


def _run_through_persona_lookup(runner: Runner, document_id: str, source_path: str) -> JobContext:
    ctx = new_context(document_id=document_id, source_path=source_path)
    original_stages = runner.stages
    try:
        runner.stages = [s for s in original_stages if s.name in _UPSTREAM_STAGE_NAMES]
        return runner._run_stages(ctx)
    finally:
        runner.stages = original_stages


def replay_vision(runner_factory: Callable[[], Runner], vision: object) -> dict[str, Any]:
    """Score Stage 5b alone against every gold document's `fields`, restricted
    to `DEFAULT_FIELDS` - that's genuinely all Stage 5b requests unless
    constructed with a wider field list, so this suite cannot claim to
    measure fields vision was never even asked for.
    """
    documents = []
    a_passed = a_total = 0

    for gold in load_gold():
        fields = gold.get("fields") or {}
        source = os.path.join(DOCS_DIR, gold["source_file"])
        runner = runner_factory()

        try:
            ctx = _run_through_persona_lookup(runner, gold["gold_id"], source)
        except Exception as exc:  # noqa: BLE001 - degrade per-document, see below
            # A stage exception (a missing/corrupt source file, a pack hook
            # throwing) reaching here, upstream of the vision call itself,
            # must not take down every other document's score either.
            results = [
                {"name": name, "kind": _field_kind(name, fields.get(name)),
                 "expected": fields.get(name), "actual": f"<error: {exc}>", "passed": False}
                for name in DEFAULT_FIELDS
            ]
            a_total += len(results)
            documents.append({
                "gold_id": gold["gold_id"], "source_file": gold["source_file"],
                "priority": gold.get("priority"), "teaches": gold.get("teaches", []),
                "passed": False, "passed_count": 0,
                "total_count": len(results), "assertions": results,
            })
            continue

        if ctx.disposition != "processed":
            # Filtered out before it ever reached persona lookup - nothing for
            # vision to be scored on. Recorded as a real, zero-assertion entry
            # rather than silently dropped from the corpus count.
            documents.append({
                "gold_id": gold["gold_id"], "source_file": gold["source_file"],
                "priority": gold.get("priority"), "teaches": gold.get("teaches", []),
                "passed": True, "passed_count": 0, "total_count": 0, "assertions": [],
            })
            continue

        try:
            # `field_names=DEFAULT_FIELDS` pins this suite to the fixed,
            # vendor-independent field set its own module docstring promises -
            # `VisionOneShot` now derives a KNOWN persona's own field list by
            # default (see `s5b_vision._field_names_and_hints`), which is the
            # right behaviour for the real pipeline but would silently widen
            # what this isolated suite scores per vendor if left implicit.
            ctx = VisionOneShot(vision=vision, field_names=DEFAULT_FIELDS).run(ctx)
        except Exception as exc:  # noqa: BLE001 - degrade per-document, see below
            # `CassetteVision` in replay mode raises loudly on a cache miss
            # (Bug 5: the shipped cassette has zero entries) rather than
            # degrading silently - correct for the pipeline, since a silent
            # empty result there would look like a real, confident answer.
            # An eval suite scoring MANY documents must not let one such miss
            # (or any other real error) crash every other document's score;
            # `scorecard.replay_gold` already has this exact discipline
            # (`assertions_for`'s per-assertion try/except) - this mirrors it
            # per-document instead, since the failure here is document-wide,
            # not per-field.
            results = [
                {"name": name, "kind": _field_kind(name, fields.get(name)),
                 "expected": fields.get(name), "actual": f"<error: {exc}>", "passed": False}
                for name in DEFAULT_FIELDS
            ]
            passed_count = 0
            a_total += len(results)
            documents.append({
                "gold_id": gold["gold_id"], "source_file": gold["source_file"],
                "priority": gold.get("priority"), "teaches": gold.get("teaches", []),
                "passed": False, "passed_count": passed_count,
                "total_count": len(results), "assertions": results,
            })
            continue

        results = []
        for name in DEFAULT_FIELDS:
            expected = fields.get(name)
            actual = ctx.extracted.get(name)
            kind = _field_kind(name, expected)
            results.append({
                "name": name, "kind": kind, "expected": expected, "actual": actual,
                "passed": matches(expected, actual, kind),
            })

        passed_count = sum(1 for r in results if r["passed"])
        a_passed += passed_count
        a_total += len(results)
        documents.append({
            "gold_id": gold["gold_id"],
            "source_file": gold["source_file"],
            "priority": gold.get("priority"),
            "teaches": gold.get("teaches", []),
            "passed": passed_count == len(results),
            "passed_count": passed_count,
            "total_count": len(results),
            "assertions": results,
        })

    passed_docs = sum(1 for d in documents if d["passed"])
    return {
        "documents": documents,
        "summary": {
            "total": len(documents),
            "passed": passed_docs,
            "failed": len(documents) - passed_docs,
            "assertions_passed": a_passed,
            "assertions_total": a_total,
        },
    }
