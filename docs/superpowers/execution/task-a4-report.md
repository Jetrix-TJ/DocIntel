# Task A4 Report

## Status
DONE

## Files Created
- `src/docintel/core/errors.py`
- `src/docintel/core/confidence.py`
- `tests/core/test_confidence.py`

## Implementation
Transcribed all three files from the brief exactly as specified:

### errors.py
- Created base `DocIntelError` exception class
- Added five subclasses: `TransientError`, `PermanentError`, `PackError`, `ValidationError`, `ContractError`
- Each with docstring describing its purpose in the pipeline

### confidence.py
- Defined `MODIFIERS` dict with exactly 16 entries, all as `Decimal` types
- Set constants: `BOOST_CAP = Decimal("1.10")`, `CEILING = Decimal("0.99")`, `_PER_BOOST = Decimal("1.03")`
- Implemented `apply_modifiers(base: float, names: Sequence[str]) -> float`
  - Raises `ValueError` with message "unknown confidence modifier: {name!r}" for unrecognized names
  - Floors result at zero
  - Uses `Decimal(str(base))` to avoid binary-float artifacts
- Implemented `apply_boosts(base: float, count: int) -> float`
  - Caps boost factor at `BOOST_CAP` (1.10)
  - Caps final result at `CEILING` (0.99)
  - Returns unmodified base when count <= 0

### test_confidence.py
- Created 7 test cases as specified
- All tests verify the exact behaviors required by the brief

## Verification Commands and Output

### 1. Task A4 Specific Tests
```bash
$ python3 -m pytest tests/core/test_confidence.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.0, pytest-9.0.2, pluggy-1.6.0 -- /Users/iamanam/.pyenv/versions/3.12.0/bin/python3
cachedir: .pytest_cache
django: version: 4.2.27
rootdir: /Users/iamanam/projects/techjays/poc/doc-intelligence
configfile: pyproject.toml
plugins: anyio-4.12.1, repeat-0.9.4, xdist-3.8.0, deepeval-3.9.4, django-4.11.1, asyncio-1.3.0, rerunfailures-16.1
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_fixture_loop_scope=function
collecting ... collected 7 items

tests/core/test_confidence.py::test_all_sixteen_modifiers_are_registered PASSED [ 14%]
tests/core/test_confidence.py::test_modifiers_are_multiplicative_and_composable PASSED [ 28%]
tests/core/test_confidence.py::test_unknown_modifier_is_rejected PASSED  [ 42%]
tests/core/test_confidence.py::test_modifier_order_does_not_matter PASSED [ 57%]
tests/core/test_confidence.py::test_boosts_are_capped_at_1_10 PASSED     [ 71%]
tests/core/test_confidence.py::test_boost_can_never_exceed_the_ceiling PASSED [ 85%]
tests/core/test_confidence.py::test_confidence_floors_at_zero PASSED     [100%]

============================== 7 passed in 0.02s ===============================
```

### 2. Full Test Suite
```bash
$ python3 -m pytest -q
................................................................         [100%]

64 passed in 0.04s
```
Note: Brief stated 57 existing tests; adding 7 new tests = 64 total (confirmed).

### 3. Type Checking (mypy strict)
```bash
$ python3 -m mypy src/docintel/core --strict
Success: no issues found in 6 source files
```

### 4. Gold Corpus Validation
```bash
$ python3 docs/corpus/validate_gold.py
gold documents : 10
checks run     : 95
failures       : 0

all gold labels are internally consistent ✓
```

### 5. Linting (ruff)
```bash
$ ruff check src tests
All checks passed!
```

## Commit
```
Commit: e2b361f
Message: feat(core): error taxonomy and closed confidence-modifier enum
Branch: feat/pipeline
```

## Key Implementation Details
1. **16 Modifiers Verified**: All 16 entries in MODIFIERS dict present and correct per brief specification
2. **Decimal Arithmetic**: All monetary/confidence values use `Decimal` type throughout; `apply_modifiers` and `apply_boosts` both convert from float via `Decimal(str(...))` to avoid binary-float artifacts
3. **Closed Enum Enforcement**: `apply_modifiers` rejects unknown modifier names with explicit `ValueError`
4. **Boost Ceiling**: `apply_boosts` correctly limits to `CEILING` (0.99), never allowing certainty through corroboration alone
5. **Type Safety**: All functions properly typed; mypy strict passes with zero errors

## Deviations from Brief
None. All specifications transcribed and implemented exactly as written.

## Concerns
None. All verification checks pass, all tests pass, no typing errors, no linting issues.

## Fix round 1

**Defects Found:** Two critical violations of the Global Constraint "a field may never exceed 0.99":

1. **Finding 1 (Critical):** `apply_boosts` did not clamp when `count <= 0`, returning unmodified base even if > 0.99
   - Observed: `apply_boosts(1.5, count=0) == 1.5`
   - Root cause: Early `return base` before any clamping

2. **Finding 2 (Important):** `apply_modifiers` had no upper clamp, could return values > 0.99
   - Observed: `apply_modifiers(2.0, []) == 2.0` and `apply_modifiers(1.5, ["ocr_source"]) == 1.35`
   - Root cause: No ceiling enforcement on return

**Solution:** Added module-private `_clamp(value: Decimal) -> float` helper enforcing [0, CEILING] invariant on every return path of both functions. Updated docstring on `apply_boosts` to clarify the rationale: "Corroboration raises confidence a little, never to certainty."

**Tests Added:** 8 new test cases:
- `test_apply_boosts_clamps_above_ceiling_when_count_is_zero` — base=1.5, count=0 → 0.99
- `test_apply_boosts_clamps_above_ceiling_when_count_is_negative` — base=1.5, count=-5 → 0.99
- `test_apply_boosts_preserves_value_under_ceiling_when_count_is_zero` — base=0.9, count=0 → 0.9
- `test_apply_modifiers_clamps_above_ceiling_with_no_modifiers` — base=2.0, [] → 0.99
- `test_apply_modifiers_clamps_above_ceiling_after_multiplication` — base=1.5, ["ocr_source"] → 0.99
- `test_apply_modifiers_never_reports_certainty` — base=1.0, [] → 0.99
- `test_apply_modifiers_clamps_below_floor` — base=-5.0, [] → 0.0
- `test_confidence_stays_within_bounds` — property test: for all bases in [0, 2], all modifier combos, and all boost counts, results always in [0.0, 0.99]

**Backward Compatibility:** All 7 original tests still pass unchanged:
- `apply_modifiers(1.0, ["draft_rules", "ocr_source"]) == 0.765` ✓
- `apply_boosts(0.5, 99) == 0.55` ✓
- `apply_boosts(0.98, 3) == 0.99` ✓

### Fix round 1 Verification

### 1. Task A4 Specific Tests (15 tests total)
```bash
$ python3 -m pytest tests/core/test_confidence.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.0, pytest-9.0.2, pluggy-1.6.0

tests/core/test_confidence.py::test_all_sixteen_modifiers_are_registered PASSED [  6%]
tests/core/test_confidence.py::test_modifiers_are_multiplicative_and_composable PASSED [ 13%]
tests/core/test_confidence.py::test_unknown_modifier_is_rejected PASSED  [ 20%]
tests/core/test_confidence.py::test_modifier_order_does_not_matter PASSED [ 26%]
tests/core/test_confidence.py::test_boosts_are_capped_at_1_10 PASSED     [ 33%]
tests/core/test_confidence.py::test_boost_can_never_exceed_the_ceiling PASSED [ 40%]
tests/core/test_confidence.py::test_confidence_floors_at_zero PASSED     [ 46%]
tests/core/test_confidence.py::test_apply_boosts_clamps_above_ceiling_when_count_is_zero PASSED [ 53%]
tests/core/test_confidence.py::test_apply_boosts_clamps_above_ceiling_when_count_is_negative PASSED [ 60%]
tests/core/test_confidence.py::test_apply_boosts_preserves_value_under_ceiling_when_count_is_zero PASSED [ 66%]
tests/core/test_confidence.py::test_apply_modifiers_clamps_above_ceiling_with_no_modifiers PASSED [ 73%]
tests/core/test_confidence.py::test_apply_modifiers_clamps_above_ceiling_after_multiplication PASSED [ 80%]
tests/core/test_confidence.py::test_apply_modifiers_never_reports_certainty PASSED [ 86%]
tests/core/test_confidence.py::test_apply_modifiers_clamps_below_floor PASSED [ 93%]
tests/core/test_confidence.py::test_confidence_stays_within_bounds PASSED [100%]

============================== 15 passed in 0.02s ===============================
```

### 2. Full Test Suite
```bash
$ python3 -m pytest -q
........................................................................[100%]

72 passed in 0.04s
```
Note: Before fix: 64 tests (57 existing + 7 initial). After fix: 72 tests (64 + 8 new gap-catching tests).

### 3. Type Checking (mypy strict)
```bash
$ python3 -m mypy src/docintel/core --strict
Success: no issues found in 6 source files
```

### 4. Gold Corpus Validation
```bash
$ python3 docs/corpus/validate_gold.py
gold documents : 10
checks run     : 95
failures       : 0

all gold labels are internally consistent ✓
```

### 5. Linting (ruff)
```bash
$ ruff check src tests
All checks passed!
```

### Commit (fix round 1)
```
Commit: 67f8e3c
Message: fix(core): enforce CEILING invariant on all confidence values
Branch: feat/pipeline
```
