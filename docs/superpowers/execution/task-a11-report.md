# Task A11 Report: The Invariant Test

## File Created
- `tests/test_invariant.py` (108 lines)

Transcribed faithfully from task-a11-brief.md lines 46-156, no changes to brief text.

## Verification Commands and Output

### 1. Invariant Test Suite
```bash
$ python3 -m pytest tests/test_invariant.py -v
============================== 48 passed in 0.05s ==============================
```

**Test count:** 48 total
- `test_invariant_holds_with_a_failure_injected_at_every_stage`: 40 tests (10 stage positions × 4 exception types)
- `test_the_invariant_holds_when_a_pack_hook_throws_at_any_socket`: 6 tests (6 hook sockets)
- `test_baseexception_escapes_by_design_and_the_counters_report_the_gap`: 1 test
- `test_invariant_holds_across_the_whole_corpus`: 1 test

### 2. Full Test Suite
```bash
$ python3 -m pytest -q
205 passed in 0.17s
```

Suite status: PASS (157 baseline + 48 invariant = 205 total)

### 3. Type Checking
```bash
$ python3 -m mypy src/docintel/core --strict
Success: no issues found in 7 source files
```

### 4. Gold Corpus Validation
```bash
$ python3 docs/corpus/validate_gold.py
gold documents : 10
checks run     : 95
failures       : 0

all gold labels are internally consistent ✓
```

### 5. Code Style
```bash
$ ruff check src tests
All checks passed!
```

### 6. Production Code Integrity
```bash
$ git status --short src/
(no output — verified clean)
```

## Commit
```
[feat/pipeline fb1ffa0] test: invariant holds under injected failures at every stage
 1 file changed, 108 insertions(+)
 create mode `tests/test_invariant.py`
```

**Commit SHA:** `fb1ffa0`

## Deviation Note

The brief predicted 42 invariant tests in Step 2. Actual count is 48. This is not a code deviation — the parametrization in the brief itself yields 48:
- 10 stage positions × 4 exception types = 40 parametrized cases
- 6 hook sockets = 6 parametrized cases
- 2 standalone tests = 2 cases
- Total = 48 ✓

The test code is exactly as written in the brief. The 42 estimate was imprecise; the actual parametrization creates 48 valid test cases.

## Summary

All five guardrails pass:
1. ✓ Invariant test suite: 48 tests, all green
2. ✓ Full suite: 205 tests green (no regression)
3. ✓ Mypy: 0 errors
4. ✓ Gold validator: 95/95 checks
5. ✓ Ruff: clean
6. ✓ `src/` unchanged: no production code modified

**The invariant is locked down:** `count(intaken) == count(emitted)` is now guarded by 48 explicit test cases covering stage failures, hook failures, BaseException escape, and corpus end-to-end processing.
