# Task A10 Report — The Gold Scorecard

Branch: `feat/pipeline` (base `05bad8d`)
Commit: `92ae4a9` — "feat: gold scorecard - the convergence loop objective function"

## Files created

- `src/docintel/scorecard.py` — transcribed verbatim from the brief. `load_gold`,
  `Assertion`, `matches`, `MONEY_FIELDS`, `CHECKED_FIELDS`, `CHECKED_DERIVED`,
  `assertions_for`, `replay_gold`.
- `tests/test_scorecard.py` — transcribed verbatim from the brief, with one
  deviation (see below).
- `.loop/scorecard.json` — output of `replay-gold --json` (Iteration 0 baseline).
- `.loop/journal.md` — seeded exactly as the brief's Step 6 specifies.

Nothing else was touched. `src/docintel/cli.py` was read only to confirm it
already imports `docintel.scorecard.replay_gold` lazily inside
`_cmd_replay_gold`, exactly as the task context described — not modified.

## Deviation from the brief, and why

The brief's test file (Step 1) opens with:

```python
import json
import pathlib
```

`json` is never referenced anywhere in the test body — it's an unused import.
`ruff check` (a mandatory verification step, and one I'm told not to weaken)
fails on it with `F401 'json' imported but unused`. I'm also told not to edit
`pyproject.toml` to add an ignore rule. Since removing an unused import line
changes zero test semantics or assertions, I removed the `import json` line.
Every test body, every assertion value, and `matches`/`replay_gold` behavior
is untouched and verbatim.

Also noted, not acted on: the brief's Step 4 says "Expected: PASS, 6 tests,"
but the test file it hands over actually contains 7 test functions. All 7
pass; I did not add or remove any test to make the count match the brief's
prose — the code block is the actual spec, the comment is just off by one.

No gold value looked wrong to me during this task; I did not need to invoke
the "gold value looks wrong, report don't change" escape hatch.

## Verification — real output

### 1. `python3 -m pytest tests/test_scorecard.py -v`

```
collected 7 items

tests/test_scorecard.py::test_loads_all_ten_gold_documents PASSED        [ 14%]
tests/test_scorecard.py::test_every_gold_source_file_exists PASSED       [ 28%]
tests/test_scorecard.py::test_scorecard_shape PASSED                     [ 42%]
tests/test_scorecard.py::test_scorecard_actually_evaluates_assertions PASSED [ 57%]
tests/test_scorecard.py::test_money_assertions_compare_by_value_not_by_string PASSED [ 71%]
tests/test_scorecard.py::test_centracom_assertions_include_the_trap PASSED [ 85%]
tests/test_scorecard.py::test_replay_never_mutates_gold PASSED           [100%]

============================== 7 passed in 0.03s ===============================
```

### 2. `python3 -m pytest -q` (whole suite)

```
........................................................................ [ 45%]
........................................................................ [ 91%]
.............                                                            [100%]
157 passed in 0.11s
```

150 pre-existing + 7 new = 157. Green.

### 3. `python3 -m mypy src/docintel/core --strict`

```
Success: no issues found in 7 source files
```

(Run exactly as scoped — against `src/docintel/core` only, not bare `mypy`.
No `grammar` directory created, `pyproject.toml` untouched.)

### 4. `python3 docs/corpus/validate_gold.py`

```
gold documents : 10
checks run     : 95
failures       : 0

all gold labels are internally consistent ✓
```

### 5. `ruff check src tests`

```
All checks passed!
```

### 6. `python3 -m docintel.cli replay-gold`

```
FAIL  digitaldirection-centracom-0384043574  (2/15)
FAIL  digitaldirection-comcast-8495444620365242  (2/16)
FAIL  digitaldirection-lumen-5-QXH7QKM7  (2/16)
FAIL  digitaldirection-windstream-041069076  (2/15)
FAIL  northstar-complete-beverage-32930  (2/11)
FAIL  northstar-dtss-6060  (3/11)
FAIL  northstar-edco-077087  (3/13)
FAIL  northstar-federal-recycling-1330123  (2/12)
FAIL  northstar-upak-4378107  (6/14)
FAIL  northstar-veritiv-715-33905296  (3/14)

0/10 documents green
```

Exit code 1 (non-zero because `summary.failed > 0`, per `_cmd_replay_gold`).

Assertions: 137 total, 27 passed (from `.loop/scorecard.json` summary:
`{"total": 10, "passed": 0, "failed": 10, "assertions_passed": 27,
"assertions_total": 137}`). `assertions_total > 50` as the shape test
requires, and every document fails, as expected for this phase — the fake
vision extractor and unbuilt selector grammar/adjust ops/domain packs mean
nearly every field assertion is a miss. This is the intended starting point
per the brief, not a bug.

### 7. `git status --short docs/corpus/gold/`

```
(empty)
```

No output — confirms `replay_gold()` never touched any gold file, and
`test_replay_never_mutates_gold` (byte-for-byte before/after comparison)
passed independently confirming the same thing.

## Anything questionable in the brief

- The unused `import json` in the test file (see Deviation above) — cosmetic,
  fixed.
- The "PASS, 6 tests" expectation in Step 4's prose vs. 7 actual test
  functions in the Step 1 code block — cosmetic, did not act on it since the
  code block is authoritative and all 7 legitimately pass.
- No gold value in the 10 files looked incorrect or suspicious during this
  task. `validate_gold.py` stayed green at 95 checks throughout, and gold
  file bytes were verified unchanged both by the CLI git-status check and by
  the test suite's own byte-comparison test.

## Commit

```
92ae4a9 feat: gold scorecard - the convergence loop objective function
 4 files changed, 1371 insertions(+)
 create mode 100644 .loop/journal.md
 create mode 100644 .loop/scorecard.json
 create mode 100644 src/docintel/scorecard.py
 create mode 100644 tests/test_scorecard.py
```

Note: `docs/superpowers/plans/2026-07-27-pipeline-implementation.md` showed as
modified (`M`) in `git status` before this task began and was left untouched
and unstaged — it is not part of this task's deliverable.

## Fix round 1

The coordinator found a real defect in the original brief's design (not in my
transcription of it): the scorecard asserted only 12 scalar fields plus 4
routing flags, so a convergence loop could reach "10/10 documents green"
while leaving `reference_list` empty and emitting no tags — the instrument
was blind to ten documented `docs/corpus-analysis.md` findings (F1b, F3, F5,
F7, F8, F11, F13, F14, F18) and all fifteen gold tags. The updated brief
(`.superpowers/sdd/2026-07-27-pipeline-implementation/task-a10-brief.md`) was
re-read and transcribed verbatim for the fix.

### What changed in `src/docintel/scorecard.py`

- `matches()` gained two comparison kinds: `superset` (every expected member
  present in actual, extras allowed — `set(expected) <= set(actual)`) and
  `set` (exact set equality). Both treat `actual is None` as `not expected`.
- `MONEY_FIELDS` grew from 9 to 15 entries to cover the new monetary fields
  (`taxes_and_fees`, `discount_amount`, `balance_from_last_statement`,
  `amount_previously_due`, `credits_adjustments`, `balance`, `total_weight`).
- `CHECKED_FIELDS` grew from 12 to 32 entries, grouped by finding with
  comments (amounts/F1-F1b, identity/F5-F6, dates and terms/F18, allocation
  and guards/F13, currency/F14, match keys/F11).
- `assertions_for` gained two new assertion builders at the end: `tags`
  (kind `superset`, built only when the gold label has tags) and
  `reference_list.values` (kind `set` when `reference_list_complete` is
  true, `superset` when false — 6 of 10 gold files transcribe page 1 only).
- Per the coordinator's explicit instruction, `line_items`, `charges`,
  `scanline`, and `sub_account` were NOT added — they have no corresponding
  key on the Stage 8 record yet and are scheduled into cluster C2's brief.
  No placeholder keys were invented for them.

`tests/test_scorecard.py` was not modified in this round — the brief's Step 1
test file is unchanged from round 0 (still 7 tests, same bodies); my earlier
`import json` removal (unused import, ruff F401) still stands and needed no
further change.

### Verification — real output

**`python3 -m pytest tests/test_scorecard.py -v`**

```
collected 7 items

tests/test_scorecard.py::test_loads_all_ten_gold_documents PASSED        [ 14%]
tests/test_scorecard.py::test_every_gold_source_file_exists PASSED       [ 28%]
tests/test_scorecard.py::test_scorecard_shape PASSED                     [ 42%]
tests/test_scorecard.py::test_scorecard_actually_evaluates_assertions PASSED [ 57%]
tests/test_scorecard.py::test_money_assertions_compare_by_value_not_by_string PASSED [ 71%]
tests/test_scorecard.py::test_centracom_assertions_include_the_trap PASSED [ 85%]
tests/test_scorecard.py::test_replay_never_mutates_gold PASSED           [100%]

============================== 7 passed in 0.03s ===============================
```

**`python3 -m pytest -q`**

```
........................................................................ [ 45%]
........................................................................ [ 91%]
.............                                                            [100%]
157 passed in 0.11s
```

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

**`python3 -m docintel.cli replay-gold`**

```
FAIL  digitaldirection-centracom-0384043574  (2/25)
FAIL  digitaldirection-comcast-8495444620365242  (2/25)
FAIL  digitaldirection-lumen-5-QXH7QKM7  (2/24)
FAIL  digitaldirection-windstream-041069076  (2/24)
FAIL  northstar-complete-beverage-32930  (2/19)
FAIL  northstar-dtss-6060  (3/16)
FAIL  northstar-edco-077087  (3/19)
FAIL  northstar-federal-recycling-1330123  (2/17)
FAIL  northstar-upak-4378107  (6/20)
FAIL  northstar-veritiv-715-33905296  (3/24)

0/10 documents green
```

Exit code 1. `.loop/scorecard.json` regenerated from `replay-gold --json`;
new summary: `{"total": 10, "passed": 0, "failed": 10, "assertions_passed":
27, "assertions_total": 213}`.

Assertions-total rose from 137 to 213 (+76), exactly as expected from adding
20 new scalar fields, tags, and reference_list.values across 10 documents.
Assertions-passed held flat at 27 — the newly-added assertions are all
currently failing too, since the fake vision extractor and unbuilt selector
grammar/domain packs don't populate any of these fields either. Documents
green held at 0/10, confirming the widened instrument is measuring more
without changing pipeline behaviour — the coordinator's stated expected
result.

**`git status --short docs/corpus/gold/`**

```
(empty)
```

No output — gold untouched, confirmed again after this round.

### Journal

Appended a "Fix round 1" subsection to `.loop/journal.md` under Iteration 0,
recording why the baseline assertion figures changed (instrument widening,
not behaviour) and the before/after totals (137 -> 213 assertions,
27 passed / 0/10 green in both rounds).

### Commit
