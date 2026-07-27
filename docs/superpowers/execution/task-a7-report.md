# Task A7 Report: Runner with the emit-always guarantee

## Status: BLOCKED

## Files created (as transcribed verbatim from the brief)
- `src/docintel/pipeline/runner.py` — transcribed byte-for-byte from the brief's Step 3.
- `tests/pipeline/test_runner.py` — transcribed byte-for-byte from the brief's Step 1.

Both files were typed exactly as given; no code in `runner.py` or `test_runner.py`
was altered from the brief.

## The blocking conflict

Two of the ten brief tests fail, and the failure is not a bug in the transcription —
it's a genuine contradiction between the brief's test file and the already-landed,
already-tested `validate_record` in `src/docintel/core/contract.py` (commit `33832e8`,
"fix(contract): tighten validate_record to reject malformed records", which is part of
the base commit `3f5bafc` this task builds on).

`validate_record`'s FINDING 1 (see `src/docintel/core/contract.py` lines 86–91) requires:

```python
if rec["disposition"] == "processed":
    if not isinstance(rec["doc_type"], str) or not rec["doc_type"]:
        raise ContractError(...)
```

This is not incidental — it is itself covered by frozen, already-green tests in
`tests/core/test_contract.py`:
- `test_finding_1_rejects_null_doc_type_on_processed`
- `test_finding_1_allows_null_doc_type_on_skipped`
- `test_finding_1_allows_null_doc_type_on_dead_letter`
- `test_finding_1_rejects_empty_doc_type_on_processed`

So: a `processed` record MUST carry a non-empty `doc_type`, and that requirement is
permanent, PR-reviewed, and out of scope for me to touch (contract.py is outside the
files I'm permitted to modify, and it's core/frozen per the task context).

The brief's `Runner` test file uses two stage doubles that never set `ctx.doc_type`:

```python
class Ok:
    name = "ok"
    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("ok")
        return ctx
```

and the `Flaky` stage in `test_transient_error_that_recovers_emits_processed`, which
also never touches `doc_type`. `JobContext.doc_type` defaults to `None`
(`src/docintel/core/models.py` line 166).

Two brief tests then assert these runs land as `disposition == "processed"`:
- `test_happy_path_emits_a_valid_record` — stages are `[Ok(), Ok()]`.
- `test_transient_error_that_recovers_emits_processed` — stage is `Flaky()`, which
  recovers on the second attempt and returns `ctx` unchanged otherwise.

Because neither stage ever sets `doc_type`, `ctx.doc_type` stays `None`. When
`Runner._emit()` calls `build_record` + `validate_record`, FINDING 1 raises
`ContractError: doc_type must be a non-empty string for processed records, got None`.
Per the brief's own deliberate design (subtlety 1: `_emit()` degrades instead of
raising), this is caught and the runner correctly degrades the record to
`disposition == "dead_letter"` — which is exactly the invariant-preserving behavior
the brief asked for. But that means the record is no longer `"processed"`, so the
test's own assertion (`rec["disposition"] == "processed"`) fails.

In other words: the brief's `_emit()` degradation logic and the brief's own
`test_happy_path_emits_a_valid_record` test cannot both be satisfied simultaneously
once `validate_record` enforces FINDING 1 — and FINDING 1 is already landed and
independently tested. This looks like the test file was written against an earlier,
looser version of `validate_record` (before `33832e8` tightened it), and the brief
was not updated after that tightening landed.

## Exact failure output

`python3 -m pytest tests/pipeline/test_runner.py -v`:

```
tests/pipeline/test_runner.py::test_happy_path_emits_a_valid_record FAILED [ 10%]
tests/pipeline/test_runner.py::test_any_stage_failure_still_emits_a_dead_letter[exc0] PASSED [ 20%]
tests/pipeline/test_runner.py::test_any_stage_failure_still_emits_a_dead_letter[exc1] PASSED [ 30%]
tests/pipeline/test_runner.py::test_any_stage_failure_still_emits_a_dead_letter[exc2] PASSED [ 40%]
tests/pipeline/test_runner.py::test_any_stage_failure_still_emits_a_dead_letter[exc3] PASSED [ 50%]
tests/pipeline/test_runner.py::test_transient_error_is_retried_then_dead_lettered PASSED [ 60%]
tests/pipeline/test_runner.py::test_transient_error_that_recovers_emits_processed FAILED [ 70%]
tests/pipeline/test_runner.py::test_the_invariant_holds_over_a_burst_with_mixed_failures PASSED [ 80%]
tests/pipeline/test_runner.py::test_a_record_that_fails_validation_degrades_instead_of_raising PASSED [ 90%]
tests/pipeline/test_runner.py::test_a_stage_that_returns_none_is_a_programming_error_not_silent_data_loss PASSED [100%]

=================================== FAILURES ===================================
_____________________ test_happy_path_emits_a_valid_record _____________________
    r = _runner([Ok(), Ok()])
    rec = r.process("d1", "/tmp/a.pdf")
    validate_record(rec)
>   assert rec["disposition"] == "processed"
E   AssertionError: assert 'dead_letter' == 'processed'
E     - processed
E     + dead_letter

______________ test_transient_error_that_recovers_emits_processed ______________
    r = Runner(stages=[Flaky()], hooks=HookRegistry(), max_retries=2)
>   assert r.process("d1", "/tmp/a.pdf")["disposition"] == "processed"
E   AssertionError: assert 'dead_letter' == 'processed'
E     - processed
E     + dead_letter

========================= 2 failed, 8 passed in 0.09s ==========================
```

`python3 -m pytest -q` (whole suite, includes the two failures above):

```
2 failed, 126 passed in 0.15s
```

(126 = 118 pre-existing + 10 new `test_runner.py` tests − 2 failing = 126 passed,
2 failed. Pre-existing 118 tests are unaffected/still green.)

## What I did not do
- Did not modify `test_runner.py`'s assertions to make them pass (explicitly
  forbidden — "STOP and report BLOCKED ... rather than adjusting the test").
- Did not modify `src/docintel/core/contract.py` (outside the allowed file set for
  this task, and it is frozen/independently tested).
- Did not run mypy / ruff / validate_gold / the chaos-invariant script as
  "verification of a complete task," since the task is not complete — 2 of the
  brief's own tests fail against already-landed code. (Whole-suite pytest above was
  run to confirm the pre-existing 118 are unaffected.)
- Did not commit. Per global constraint: "Never commit without the full test suite
  green."

## Possible resolutions (for the requester to decide — not my call)
1. Update the brief/test so `Ok`/`Flaky` stage doubles set `ctx.doc_type` to a
   non-empty value (e.g. `ctx.doc_type = "test_doc"`), reflecting how a real
   classification stage would behave upstream of extraction. This would make both
   failing tests pass without touching `runner.py` or `contract.py`.
2. Confirm FINDING 1 is intentionally as strict as landed, in which case option 1
   is the fix.
3. If FINDING 1 was over-tightened and should allow `None` doc_type on `processed`
   records under some condition, that's a contract.py change outside this task's
   scope and outside my file permissions.

I believe option 1 is almost certainly correct (the stage doubles are meant to be
minimal, and FINDING 1 is clearly deliberate, independently tested, PR-reviewed
behavior) — but the instructions were explicit not to adjust the test myself and to
report back instead.

## Resolution

**Coordinator's ruling:** option 1 was correct.

- `validate_record`'s doc_type rule (FINDING 1) is correct and stays unchanged.
  Coordinator independently verified a processed record with `doc_type=None` is
  rejected with a clear message.
- `runner.py`'s `_emit()` degradation is correct and stays unchanged. It did
  precisely what it should: refused to emit an invalid "processed" record and
  degraded it to a valid `dead_letter` record instead.
- The defect was confirmed to be in the brief's test doubles: `Ok` and `Flaky`
  were unrealistically minimal — they never classified. The coordinator confirmed
  the real `Classify` stage (arriving in Task A8) does set
  `doc_type = "standard_invoice"`, so live pipeline runs were never affected by
  this — only these two test doubles were.

**Brief was regenerated.** The only change was to `tests/pipeline/test_runner.py`:
1. Added a module-level helper `_classified(ctx)` that sets
   `doc_type = "standard_invoice"` when it is `None`, with a docstring explaining
   it stands in for stage 3 (real classification, landing in Task A8).
2. `Ok.run` now returns `_classified(ctx)` instead of bare `ctx`.
3. The `Flaky` stage inside `test_transient_error_that_recovers_emits_processed`
   returns `_classified(ctx)` on its successful attempt instead of bare `ctx`.

`src/docintel/pipeline/runner.py` is byte-for-byte unchanged from the original
transcription — no changes were needed or made to it. `src/docintel/core/contract.py`
was not touched. No assertion in any test was weakened; the fix was entirely in
making the stage doubles classify the document, mirroring realistic pipeline
behavior.

### Final verification (all commands actually run, real output)

**1. `python3 -m pytest tests/pipeline/test_runner.py -v`**

```
tests/pipeline/test_runner.py::test_happy_path_emits_a_valid_record PASSED [ 10%]
tests/pipeline/test_runner.py::test_any_stage_failure_still_emits_a_dead_letter[exc0] PASSED [ 20%]
tests/pipeline/test_runner.py::test_any_stage_failure_still_emits_a_dead_letter[exc1] PASSED [ 30%]
tests/pipeline/test_runner.py::test_any_stage_failure_still_emits_a_dead_letter[exc2] PASSED [ 40%]
tests/pipeline/test_runner.py::test_any_stage_failure_still_emits_a_dead_letter[exc3] PASSED [ 50%]
tests/pipeline/test_runner.py::test_transient_error_is_retried_then_dead_lettered PASSED [ 60%]
tests/pipeline/test_runner.py::test_transient_error_that_recovers_emits_processed PASSED [ 70%]
tests/pipeline/test_runner.py::test_the_invariant_holds_over_a_burst_with_mixed_failures PASSED [ 80%]
tests/pipeline/test_runner.py::test_a_record_that_fails_validation_degrades_instead_of_raising PASSED [ 90%]
tests/pipeline/test_runner.py::test_a_stage_that_returns_none_is_a_programming_error_not_silent_data_loss PASSED [100%]

============================== 10 passed in 0.03s ==============================
```

**2. `python3 -m pytest -q`** (whole suite: 118 pre-existing + 10 new)

```
........................................................................ [ 56%]
........................................................                 [100%]
128 passed in 0.09s
```

**3. `python3 -m mypy src/docintel/core --strict`**

```
Success: no issues found in 7 source files
```

**4. `python3 docs/corpus/validate_gold.py`**

```
gold documents : 10
checks run     : 95
failures       : 0

all gold labels are internally consistent ✓
```

**5. `ruff check src tests`**

```
All checks passed!
```

**6. Chaos-invariant stress script (200 documents, random exceptions/None returns)**

```
records: 200 stats: {'intaken': 200, 'emitted': 200}
INVARIANT HOLDS under 200 docs with random failures
```

**7. Degradation-path check (corrupt context still yields a valid record)**

```
dead_letter | contract validation failed: doc_type must be a non-empty str | {'intaken': 1, 'emitted': 1}
```

This confirms: a stage that sets `doc_type = None` and an out-of-range confidence
value still produces exactly one valid emitted record, correctly disposed as
`dead_letter`, with `stats == {'intaken': 1, 'emitted': 1}` — the invariant held
even though the enforcement machinery itself (`validate_record`) rejected the
record the pipeline tried to build.

### Final test count

128 tests total (118 pre-existing + 10 in `tests/pipeline/test_runner.py`), all
green.

### Commit

Committed on `feat/pipeline` per the brief's Step 5 instruction, with files scoped
to exactly `src/docintel/pipeline/runner.py` and `tests/pipeline/test_runner.py`.

## Fix round 1

Spec compliance and logic review passed. Three gaps were identified in the brief's
own code and fixed by re-transcribing the updated brief (not by independent
judgment):

**FINDING 1 (Important) — hooks were stored but never dispatched.** The module
docstring claimed "a pack hook throwing" was one of the guarded escape routes, but
no hook socket was ever invoked anywhere in `runner.py`. Fixed by transcribing the
brief's boundary-dispatch design:
- `HOOKS_BEFORE: dict[str, str]` maps 4 stage names (`intake`, `persona_lookup`,
  `capture_fields`, `confidence_gate`) to the sockets that fire before them
  (`beforeIntake`, `beforePersonaLookup`, `afterExtraction`, `beforeConfidenceGate`).
- `HOOKS_AFTER: dict[str, str]` maps `attachment_filter` to `afterFilter`.
- `_run_stages` dispatches the before-socket (if mapped) ahead of `_run_one`, then
  dispatches the after-socket (if mapped) BEFORE the `disposition != "processed"`
  break check — so a pack can react to a skip the base pipeline just decided.
- `beforeEmit` is dispatched inside `_emit()`, not through either boundary map.
  This is deliberate: skipped/dead-lettered documents break out of `_run_stages`
  early and never reach an "emit" stage boundary, but they still produce a Stage 8
  record, so a boundary-mapped `beforeEmit` would silently miss them. Dispatching
  it inside `_emit()` guarantees it reaches every emitted record.
- `classifySignals` and `onRegenTrigger` are deliberately NOT wired here:
  `classifySignals` fires inside stage 3 where a pack injects its signal ladder;
  `onRegenTrigger` belongs to the rule lifecycle that runs beside the pipeline.

**FINDING 2 (Minor) — `assert last is not None` was load-bearing control flow.**
`python -O` strips assertions, which would turn this into `raise None` →
`TypeError`, silently breaking the exhausted-retries path. Replaced with an
explicit `if last is None: raise RuntimeError(...)`.

**FINDING 3 (Minor) — `test_transient_error_that_recovers_emits_processed` was
the only test not calling `validate_record()` or asserting `r.stats`.** Brought in
line with its siblings: now calls `validate_record(rec)` and asserts
`r.stats == {"intaken": 1, "emitted": 1}` in addition to the disposition check.

**Three new tests transcribed verbatim:**
- `test_a_throwing_pack_hook_still_emits_a_dead_letter` — registers an `afterFilter`
  hook that raises `RuntimeError("pack bug")`, confirms the record still emits as
  `dead_letter` with `"northstar"` (the registering pack's name) in the reason.
- `test_hooks_fire_at_their_declared_boundaries` — registers probes on all 6
  runner-owned sockets and asserts they fire in the declared order.
- `test_beforeEmit_fires_even_for_a_skipped_document` — a stage that sets
  `disposition = "skipped"` and returns early still triggers `beforeEmit`.

**Coordinator's rulings, applied as instructed, not second-guessed:**
- `ctx.emitted = True` was NOT removed, despite being flagged as dead code by
  review — `JobContext.emitted` is asserted by Task A3's tests and removal has
  ripple effects outside this task's file scope.
- The runner does NOT catch `BaseException` — `KeyboardInterrupt`/`SystemExit`
  still propagate past `process()`, which is correct: if one escapes,
  `intaken > emitted` and that mismatch is itself the correct alert signal.

No existing test needed editing — all previously-passing assertions still hold
after the hook-dispatch and control-flow changes.

### Verification (all commands actually run, real output)

**1. `python3 -m pytest tests/pipeline/test_runner.py -v`**

```
collected 13 items

tests/pipeline/test_runner.py::test_happy_path_emits_a_valid_record PASSED [  7%]
tests/pipeline/test_runner.py::test_any_stage_failure_still_emits_a_dead_letter[exc0] PASSED [ 15%]
tests/pipeline/test_runner.py::test_any_stage_failure_still_emits_a_dead_letter[exc1] PASSED [ 23%]
tests/pipeline/test_runner.py::test_any_stage_failure_still_emits_a_dead_letter[exc2] PASSED [ 30%]
tests/pipeline/test_runner.py::test_any_stage_failure_still_emits_a_dead_letter[exc3] PASSED [ 38%]
tests/pipeline/test_runner.py::test_transient_error_is_retried_then_dead_lettered PASSED [ 46%]
tests/pipeline/test_runner.py::test_transient_error_that_recovers_emits_processed PASSED [ 53%]
tests/pipeline/test_runner.py::test_the_invariant_holds_over_a_burst_with_mixed_failures PASSED [ 61%]
tests/pipeline/test_runner.py::test_a_throwing_pack_hook_still_emits_a_dead_letter PASSED [ 69%]
tests/pipeline/test_runner.py::test_hooks_fire_at_their_declared_boundaries PASSED [ 76%]
tests/pipeline/test_runner.py::test_beforeEmit_fires_even_for_a_skipped_document PASSED [ 84%]
tests/pipeline/test_runner.py::test_a_record_that_fails_validation_degrades_instead_of_raising PASSED [ 92%]
tests/pipeline/test_runner.py::test_a_stage_that_returns_none_is_a_programming_error_not_silent_data_loss PASSED [100%]

============================== 13 passed in 0.03s ==============================
```

**2. `python3 -m pytest -q`** (whole suite: 118 pre-A7 + 13 in test_runner.py)

```
........................................................................ [ 54%]
...........................................................              [100%]
131 passed in 0.10s
```

**3. `python3 -m mypy src/docintel/core --strict`**

```
Success: no issues found in 7 source files
```

**4. `python3 docs/corpus/validate_gold.py`**

```
gold documents : 10
checks run     : 95
failures       : 0

all gold labels are internally consistent ✓
```

**5. `ruff check src tests`**

```
All checks passed!
```

**6. Chaos-invariant stress script (200 documents, random exceptions/None returns,
now with hook dispatch wired in)**

```
records: 200 stats: {'intaken': 200, 'emitted': 200}
INVARIANT HOLDS under 200 docs with random failures
```

### Final test count

131 tests total (118 pre-A7 + 13 in `tests/pipeline/test_runner.py`), all green.

### Commit

Committed on `feat/pipeline`, scoped to exactly `src/docintel/pipeline/runner.py`
and `tests/pipeline/test_runner.py`.
