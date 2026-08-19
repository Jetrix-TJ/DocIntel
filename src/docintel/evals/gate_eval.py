"""Isolated Stage 2/3 eval: does the gate correctly decide "worth processing?"
and does the classifier assign the right doc_type/tags/text_source -
independent of whether extraction (stages 4+) succeeds at all.

This is the "Gate & classifier eval" suite named in `docs/architecture/
pipeline-v2.md` (Part 7) - previously only measured as a side effect of
scoring the whole pipeline via `scorecard.replay_gold`. A misclassification
runs the wrong persona's rules on every downstream stage, so isolating this
one is worth its own suite: a regression here shows up here, not buried
inside a dozen other assertions that all happen to also fail because of it.

Deliberately does NOT call `Runner.process()` on a stage-sliced Runner:
`process()` unconditionally routes through `_emit()`, which calls
`build_record`/`validate_record` - machinery meant for a context that ran the
ENTIRE pipeline (`REQUIRED_KEYS`, `core/contract.py`). An isolated suite
doesn't need a valid *record*, it needs the intermediate *context* state
(`ctx.doc_type`, `ctx.tags`, `ctx.disposition`) - so this reuses
`Runner._run_stages` directly against a stage-sliced copy of the runner's own
stage list. That keeps hook-firing and the early-break-on-non-"processed"
behavior identical to a real run (both are part of what Stage 2/3 actually
do), without ever building or validating a full record.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from docintel.core.models import JobContext, new_context
from docintel.pipeline.runner import Runner
from docintel.scorecard import DOCS_DIR, load_gold, matches

# The prefix of stages this suite measures - everything through classification,
# nothing that touches persona lookup or extraction.
_GATE_STAGE_NAMES = frozenset({"intake", "attachment_filter", "classify"})


def _run_gate_stages(runner: Runner, document_id: str, source_path: str) -> JobContext:
    ctx = new_context(document_id=document_id, source_path=source_path)
    original_stages = runner.stages
    try:
        runner.stages = [s for s in original_stages if s.name in _GATE_STAGE_NAMES]
        return runner._run_stages(ctx)
    finally:
        runner.stages = original_stages


def replay_gate(runner_factory: Callable[[], Runner]) -> dict[str, Any]:
    """Score `intake -> attachment_filter -> classify` against every gold
    document's `classification` block. `disposition` is asserted too: every
    gold document is meant to be processed (none currently represents "Stage
    2 correctly skips this"), so this cannot yet measure skip-correctness on
    a should-be-filtered document - `skip_detection` in the summary says so
    explicitly rather than silently omitting that half of the suite's name.
    """
    documents = []
    a_passed = a_total = 0
    check_names = ("disposition", "doc_type", "tags", "text_source")

    for gold in load_gold():
        cls = gold.get("classification") or {}
        source = os.path.join(DOCS_DIR, gold["source_file"])
        runner = runner_factory()

        try:
            ctx = _run_gate_stages(runner, gold["gold_id"], source)
        except Exception as exc:  # noqa: BLE001 - degrade per-document, see below
            # A stage exception (a missing/corrupt source file, a pack hook
            # throwing) must not take down every other document's score -
            # the same discipline `evals.vision_eval` needs for the same
            # reason, one layer up: this is the stage-running call itself,
            # not just the field-comparison step after it.
            results: list[dict[str, Any]] = [
                {"name": name, "kind": "exact", "expected": None,
                 "actual": f"<error: {exc}>", "passed": False}
                for name in check_names
            ]
            a_total += len(results)
            documents.append({
                "gold_id": gold["gold_id"], "source_file": gold["source_file"],
                "priority": gold.get("priority"), "teaches": gold.get("teaches", []),
                "passed": False, "passed_count": 0,
                "total_count": len(results), "assertions": results,
            })
            continue

        checks = [
            ("disposition", "processed", ctx.disposition, "exact"),
            ("doc_type", cls.get("doc_type"), ctx.doc_type, "exact"),
            ("tags", cls.get("tags", []), list(ctx.tags), "superset"),
            ("text_source", cls.get("text_source"), ctx.text_source, "text"),
        ]
        results = [
            {"name": name, "kind": kind, "expected": expected, "actual": actual,
             "passed": matches(expected, actual, kind)}
            for name, expected, actual, kind in checks
        ]

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
            # Honest, not omitted: no gold fixture today represents a document
            # Stage 2 should filter out before it ever reaches classification,
            # so that half of "gate & classifier" reads 0/0 until one exists.
            "skip_detection": {
                "total": 0, "passed": 0,
                "note": "no gold fixture yet represents a should-be-filtered document",
            },
        },
    }
