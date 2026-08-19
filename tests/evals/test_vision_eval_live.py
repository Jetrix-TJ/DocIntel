"""The real end-to-end check: Stage 5b (vision one-shot), forced, against
every real gold document, through a real Gemini call.

Every other test in this repo deliberately never touches the network -
`--vision fake`/`--vision cassette` exist precisely so the suite stays
offline, deterministic, and free to run. This file is the one place that
breaks that rule on purpose, because "does the pipeline's actual live vision
path work" is not answerable any other way - a fake or a cassette only
proves the plumbing around a call, never that Google's API still accepts the
request this adapter builds.

Skipped unless BOTH are true:
  - GEMINI_API_KEY is set (there is a real key to call with)
  - DOCINTEL_RUN_LIVE_TESTS=1 is set (an explicit, separate opt-in)

Two gates, not one: a developer with a key sitting in `.env` for other work
should not have a normal `pytest` run silently start spending money and
needing network. Run explicitly:

    DOCINTEL_RUN_LIVE_TESTS=1 pytest tests/evals/test_vision_eval_live.py -v -s

or the equivalent CLI entry point this test itself exercises:

    docintel eval-vision --vision live --json
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not (os.environ.get("GEMINI_API_KEY") and os.environ.get("DOCINTEL_RUN_LIVE_TESTS") == "1"),
    reason="live Gemini test: needs GEMINI_API_KEY and DOCINTEL_RUN_LIVE_TESTS=1 (opt-in, costs money and needs network)",
)


def _runner_factory():
    from docintel.pipeline.hooks import HookRegistry
    from docintel.pipeline.runner import Runner
    from docintel.pipeline.stages import build_default_stages

    return Runner(stages=build_default_stages(vision=None), hooks=HookRegistry())


def test_gemini_actually_extracts_from_the_real_gold_corpus():
    """Runs the real pipeline (intake through persona lookup) on all 15 real
    gold PDFs, then forces Stage 5b with a real, live GeminiVision - no fake,
    no cassette, no canned response. Prints a per-document report so a human
    reading test output can see exactly what came back from the model, not
    just a pass/fail count.
    """
    from docintel.adapters.vision.gemini_adapter import GeminiVision
    from docintel.evals.vision_eval import replay_vision

    vision = GeminiVision()
    card = replay_vision(runner_factory=_runner_factory, vision=vision)

    print(f"\n=== live Gemini vision-one-shot vs. {card['summary']['total']} gold documents ===")
    for doc in card["documents"]:
        if doc["total_count"] == 0:
            continue
        mark = "PASS" if doc["passed"] else "FAIL"
        print(f"  {mark}  {doc['gold_id']:<45} {doc['passed_count']}/{doc['total_count']}")
        for a in doc["assertions"]:
            if not a["passed"]:
                print(f"        FAIL {a['name']:<16} expected={a['expected']!r} actual={a['actual']!r}")

    summary = card["summary"]
    print(
        f"\nTOTAL: {summary['assertions_passed']}/{summary['assertions_total']} assertions, "
        f"{summary['passed']}/{summary['total']} documents fully correct"
    )

    # The bar here is "the live call genuinely worked end to end," not "every
    # field matched" - gold labels intentionally cover hard cases (F3 forced
    # review, foreign currency, OCR-only scans) a bare transcription pass may
    # legitimately miss. A real assertion count > 0 with SOME passes is the
    # honest floor: it proves a real network call happened, was parsed, and
    # produced at least partially correct data - not that Stage 5b crashed or
    # every document silently scored zero the way `--vision fake` always does.
    assert summary["assertions_total"] > 0, "no gold document reached Stage 5b at all"
    assert summary["assertions_passed"] > 0, "the live Gemini call ran but extracted nothing correct"
