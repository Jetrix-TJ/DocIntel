# Task A8 Report: The 10 thin stage modules (walking skeleton)

Branch: `feat/pipeline`, base commit `7313570`, work committed as `b26f77b`.

## Files created

- `src/docintel/adapters/__init__.py`
- `src/docintel/adapters/vision/__init__.py`
- `src/docintel/adapters/vision/port.py` (`VisionResult`, `VisionExtractor` Protocol)
- `src/docintel/adapters/vision/fake.py` (`FakeVision`)
- `src/docintel/pipeline/stages/__init__.py` (`build_default_stages`)
- `src/docintel/pipeline/stages/s1_intake.py` (`Intake`, name=`"intake"`)
- `src/docintel/pipeline/stages/s2_filter.py` (`AttachmentFilter`, name=`"attachment_filter"`)
- `src/docintel/pipeline/stages/s3_classify.py` (`Classify`, name=`"classify"`)
- `src/docintel/pipeline/stages/s4_persona.py` (`PersonaLookup`, name=`"persona_lookup"`)
- `src/docintel/pipeline/stages/s5a_cached.py` (`ApplyCachedRules`, name=`"apply_cached_rules"`)
- `src/docintel/pipeline/stages/s5b_vision.py` (`VisionOneShot`, name=`"vision_one_shot"`)
- `src/docintel/pipeline/stages/s5c_agent.py` (`AgentEscalation`, name=`"agent_escalation"`)
- `src/docintel/pipeline/stages/s6_capture.py` (`CaptureFields`, name=`"capture_fields"`)
- `src/docintel/pipeline/stages/s7_gate.py` (`ConfidenceGate`, name=`"confidence_gate"`)
- `src/docintel/pipeline/stages/s8_emit.py` (`EmitRecord`, name=`"emit_record"`)
- `tests/pipeline/test_stages_skeleton.py`

All content transcribed verbatim from the brief. No `src/docintel/core/` or
`src/docintel/pipeline/{hooks,runner}.py` files were touched. Pre-existing
unrelated working-tree modifications to two docs files
(`docs/superpowers/plans/2026-07-27-pipeline-implementation.md`,
`docs/superpowers/specs/2026-07-27-pipeline-implementation-design.md`) were
left untouched and NOT staged/committed by this task, per brief scope.

## Verification (real output)

### 1. `python3 -m pytest tests/pipeline/test_stages_skeleton.py -v`

```
collected 6 items

tests/pipeline/test_stages_skeleton.py::test_every_stage_runs_and_is_logged PASSED [ 16%]
tests/pipeline/test_stages_skeleton.py::test_the_default_sequence_is_ten_modules_in_pipeline_order PASSED [ 33%]
tests/pipeline/test_stages_skeleton.py::test_every_stage_records_that_it_ran PASSED [ 50%]
tests/pipeline/test_stages_skeleton.py::test_hard_miss_routes_to_vision_not_cached_rules PASSED [ 66%]
tests/pipeline/test_stages_skeleton.py::test_unsupported_file_type_is_skipped_with_a_reason_never_dropped PASSED [ 83%]
tests/pipeline/test_stages_skeleton.py::test_document_id_is_stable_for_the_same_source PASSED [100%]

============================== 6 passed in 0.03s ===============================
```

Note: the brief's Step 5 says "Expected: PASS, 5 tests" but the test file
it specifies (Step 1) actually contains 6 `def test_...` functions. This is
a minor inconsistency in the brief's own narrative, not a deviation on my
part — I transcribed the test file exactly as given, and all 6 of its tests
pass.

### 2. `python3 -m pytest -q` (whole suite)

```
........................................................................ [ 52%]
.................................................................        [100%]
137 passed in 0.10s
```

131 pre-existing + 6 new = 137. Suite stayed green.

### 3. `python3 -m mypy src/docintel/core --strict`

```
Success: no issues found in 7 source files
```

0 errors, as required. Ran only against `src/docintel/core` (not bare
`mypy`); did not create a `grammar` directory or touch `pyproject.toml`.

### 4. `python3 docs/corpus/validate_gold.py`

```
gold documents : 10
checks run     : 95
failures       : 0

all gold labels are internally consistent ✓
```

95 green, as required.

### 5. `ruff check src tests`

```
All checks passed!
```

### 6. Stage-name / hook-contract proof

```
names: ['intake', 'attachment_filter', 'classify', 'persona_lookup', 'apply_cached_rules', 'vision_one_shot', 'agent_escalation', 'capture_fields', 'confidence_gate', 'emit_record']
exact match: True
hook keys with no stage: set()
```

`exact match` is `True`; `hook keys with no stage` is the empty set, i.e.
`HOOKS_BEFORE = {"intake", "persona_lookup", "capture_fields", "confidence_gate"}`
and `HOOKS_AFTER = {"attachment_filter"}` both resolve against real stage
names.

### 7. All 10 real corpus PDFs traverse the pipeline

```
pdfs found: 10
  processed   low     CANADIAN WITHOUT NOTES U- PAK 4378107 (1).pdf
  processed   low     CONTRA ONLY Everything already on AR Federal 
  processed   low     Centracom_0384043574_01012026_BILL.pdf
  processed   low     Comcast_8495 44 462 0365242_12092025_BILL.pdf
  processed   low     EDCO 77087APR25 current charges can be mislea
  processed   low     Lumen - 5-QXH7QKM7.pdf
  processed   low     Windstream_041069076_07222025_BILL.pdf
  processed   low     _AP Invoice 32930 Complete Beverage Destructi
  processed   low     _AP Invoice 6060DTSS        D.T.S.S. Inc. 699
  processed   low     _AP Invoice 715-33905296    Veritiv Operating
stats: {'intaken': 10, 'emitted': 10}
ALL 10 EMITTED, INVARIANT HOLDS
```

All 10 PDFs land as `processed` / lane `low` — expected per the brief's note
that `ctx.pages` is empty at this point (PDF extraction arrives in a later
cluster), so `FakeVision` returns no fields, `ctx.confidence` stays empty,
and `s7_gate.ConfidenceGate` routes every document to the `low` lane with
`review_flag=True`. `intaken == emitted == 10` holds.

## Deviations from the brief

None. Every file, class name, stage `name` string, function signature, and
test was transcribed exactly as given. Cross-checked every stage module
against the real (already-landed) `JobContext`, `build_record`,
`apply_modifiers`, `HookRegistry`, and `Runner` APIs in
`src/docintel/core/models.py`, `contract.py`, `confidence.py`, and
`src/docintel/pipeline/{hooks,runner}.py` before writing — all matched the
brief's assumed API with no adjustment needed.

## Anything questionable in the brief

- Step 5's "Expected: PASS, 5 tests" undercounts by one; the test file
  itself (Step 1) has 6 test functions. Noted above; not corrected since
  correcting would mean altering the verbatim test file, which the brief
  forbids.
- Everything else was internally consistent and matched the already-landed
  core/pipeline code exactly — no other issues found.

## Test count

137 tests total, all passing (131 pre-existing + 6 new in
`tests/pipeline/test_stages_skeleton.py`).

## Fix round 1

Coordinator review found the transcription was faithful but the brief's own
code (round 1) had two important defects plus a coverage gap. The brief was
corrected (regen_flag fix, docstring fix, four new tests + two stubs) and
this round transcribes those corrections.

### Changes

- `src/docintel/pipeline/stages/s5c_agent.py` (FINDING 1 / FINDING 2): on a
  hard miss, `AgentEscalation.run()` now sets `ctx.review_flag = True`
  instead of `ctx.regen_flag = True`, with the brief's comment explaining
  why (a first-time sender has no rules, so "the rules are wrong" is
  meaningless; Stage 7 stays the sole writer of `regen_flag`).
- `src/docintel/pipeline/stages/s5b_vision.py` (FINDING 3): `_collapsed()`
  docstring corrected to state it also returns `True` for the
  zero-fields-extracted case, not just "several fields below threshold".
- `tests/pipeline/test_stages_skeleton.py` (FINDING 4): replaced with the
  brief's corrected version — added `from docintel.core.models import
  new_context`, the `_StubPersona`/`_StubStore`/`_StubExecutor` stubs, the
  `_routing_runner` helper, and four new tests:
  `test_persona_hit_with_good_confidence_takes_the_fast_lane_with_zero_vision_calls`,
  `test_persona_hit_whose_rules_collapse_falls_back_to_vision`,
  `test_soft_miss_still_runs_the_cached_rules_first`,
  `test_hard_miss_sets_review_not_regen`.
- `src/docintel/pipeline/stages/s7_gate.py` — untouched, confirmed via
  `git diff --stat` (empty output) before committing. Its `regen_flag` write
  on the very-low lane is unchanged and remains the sole writer.

No existing test failed or needed editing; all prior assertions still held
under the fix.

### Verification (real output)

**`python3 -m pytest tests/pipeline/test_stages_skeleton.py -v`**

```
collected 10 items

tests/pipeline/test_stages_skeleton.py::test_every_stage_runs_and_is_logged PASSED [ 10%]
tests/pipeline/test_stages_skeleton.py::test_the_default_sequence_is_ten_modules_in_pipeline_order PASSED [ 20%]
tests/pipeline/test_stages_skeleton.py::test_every_stage_records_that_it_ran PASSED [ 30%]
tests/pipeline/test_stages_skeleton.py::test_hard_miss_routes_to_vision_not_cached_rules PASSED [ 40%]
tests/pipeline/test_stages_skeleton.py::test_persona_hit_with_good_confidence_takes_the_fast_lane_with_zero_vision_calls PASSED [ 50%]
tests/pipeline/test_stages_skeleton.py::test_persona_hit_whose_rules_collapse_falls_back_to_vision PASSED [ 60%]
tests/pipeline/test_stages_skeleton.py::test_soft_miss_still_runs_the_cached_rules_first PASSED [ 70%]
tests/pipeline/test_stages_skeleton.py::test_hard_miss_sets_review_not_regen PASSED [ 80%]
tests/pipeline/test_stages_skeleton.py::test_unsupported_file_type_is_skipped_with_a_reason_never_dropped PASSED [ 90%]
tests/pipeline/test_stages_skeleton.py::test_document_id_is_stable_for_the_same_source PASSED [100%]

============================== 10 passed in 0.03s ==============================
```

**`python3 -m pytest -q`**

```
........................................................................ [ 51%]
.....................................................................    [100%]
141 passed in 0.09s
```

137 pre-round-1 + 4 new = 141. All previously-passing tests still pass.

**`python3 -m mypy src/docintel/core --strict`**

```
Success: no issues found in 7 source files
```

**`python3 docs/corpus/validate_gold.py`**

```
gold documents : 10
checks run     : 95
failures       : 0

all gold labels are internally consistent ✓
```

**`ruff check src tests`**

```
All checks passed!
```

**10-corpus-PDF script, extended with a regen_flag tally:**

```
pdfs found: 10
  processed   low     regen=False CANADIAN WITHOUT NOTES U- PAK 4378107 (1
  processed   low     regen=False CONTRA ONLY Everything already on AR Fed
  processed   low     regen=False Centracom_0384043574_01012026_BILL.pdf
  processed   low     regen=False Comcast_8495 44 462 0365242_12092025_BIL
  processed   low     regen=False EDCO 77087APR25 current charges can be m
  processed   low     regen=False Lumen - 5-QXH7QKM7.pdf
  processed   low     regen=False Windstream_041069076_07222025_BILL.pdf
  processed   low     regen=False _AP Invoice 32930 Complete Beverage Dest
  processed   low     regen=False _AP Invoice 6060DTSS        D.T.S.S. Inc
  processed   low     regen=False _AP Invoice 715-33905296    Veritiv Oper
stats: {'intaken': 10, 'emitted': 10}
ALL 10 EMITTED, INVARIANT HOLDS
records with regen_flag=True: 0 of 10
```

0 of 10 now, versus 10 of 10 before the fix. Confirms FINDING 1/2 are
resolved on the real corpus, not just in unit tests.

### Test count (updated)

141 tests total, all passing (137 pre-round-1 + 4 new stage-5-routing
tests).
