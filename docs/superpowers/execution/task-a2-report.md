# Task A2 Report

## Files Created

- `src/docintel/core/dates.py` - Date parsing ladder with two-digit year flagging
- `tests/core/test_dates.py` - Test suite for date parsing

## Implementation

Faithfully transcribed the complete implementation from task-a2-brief.md:

1. `DateResult` frozen dataclass with fields: `raw`, `iso`, `parsed`, `ambiguous_two_digit_year`
2. `parse_date(raw: str) -> DateResult` function implementing:
   - Numeric date format: `M/D/YY` or `M/D/YYYY` via `_NUMERIC` regex
   - Month-name format: `Month D, YYYY` (case-insensitive) via `_MONTH_NAME` regex
   - Two-digit years detected and flagged with `ambiguous_two_digit_year=True`, assumed 2000-2099
   - Invalid dates (bad month/day) return `parsed=False` without inventing values
   - Unparseable strings return `parsed=False, iso=None` with raw value preserved

Module follows existing `money.py` style: `from __future__ import annotations`, module docstring, frozen dataclass.

## Verification Output

### Test Suite - Task A2
```
$ python3 -m pytest tests/core/test_dates.py -v
============================= test session starts ==============================
collected 15 items

tests/core/test_dates.py::test_parse_date[9/15/2025-2025-09-15] PASSED   [  6%]
tests/core/test_dates.py::test_parse_date[08/14/2025-2025-08-14] PASSED  [ 13%]
tests/core/test_dates.py::test_parse_date[10/24/2025-2025-10-24] PASSED  [ 20%]
tests/core/test_dates.py::test_parse_date[05/31/2025-2025-05-31] PASSED  [ 26%]
tests/core/test_dates.py::test_parse_date[Dec 09, 2025-2025-12-09] PASSED [ 33%]
tests/core/test_dates.py::test_parse_date[September 01, 2025-2025-09-01] PASSED [ 40%]
tests/core/test_dates.py::test_parse_date[January 01, 2026-2026-01-01] PASSED [ 46%]
tests/core/test_dates.py::test_parse_date[July 22, 2025-2025-07-22] PASSED [ 53%]
tests/core/test_dates.py::test_parse_date[MARCH 31, 2025-2025-03-31] PASSED [ 60%]
tests/core/test_dates.py::test_two_digit_year_parses_but_is_flagged PASSED [ 66%]
tests/core/test_dates.py::test_unparseable_passes_through_without_inventing_a_day[25TH OF THE MONTH] PASSED [ 73%]
tests/core/test_dates.py::test_unparseable_passes_through_without_inventing_a_day[EOM plus 15] PASSED [ 80%]
tests/core/test_dates.py::test_unparseable_passes_through_without_inventing_a_day[Due on receipt] PASSED [ 86%]
tests/core/test_dates.py::test_unparseable_passes_through_without_inventing_a_day[Net 30] PASSED [ 93%]
tests/core/test_dates.py::test_unparseable_passes_through_without_inventing_a_day[] PASSED [100%]

============================== 15 passed in 0.02s ==============================
```

### Full Test Suite
```
$ python3 -m pytest -q
.......................................                                  [100%]

39 passed in 0.02s
```

### Gold Corpus Validation
```
$ python3 docs/corpus/validate_gold.py
gold documents : 10
checks run     : 95
failures       : 0

all gold labels are internally consistent ✓
```

### Code Quality
```
$ ruff check src tests
All checks passed!
```

## Commit

```
git add src/docintel/core/dates.py tests/core/test_dates.py
git commit -m "feat(core): date parse ladder with two-digit-year flagging"
```

**Commit SHA:** `460f08c`

## Deviations from Brief

None. Complete faithful transcription as required.

## Test Count Verification

Brief expected: 15 tests
Actual: 15 tests

- 9 parametrized tests in `test_parse_date`
- 1 test for two-digit year flagging
- 5 parametrized tests for unparseable dates
Total: 15 tests passing

## Notes

- No modifications to other files (`money.py`, existing tests, etc.)
- All requirements honored:
  1. `parse_date` never invents values (e.g., "25TH OF THE MONTH" returns `parsed=False`)
  2. Two-digit years detected and flagged (e.g., "03/31/25" → `ambiguous_two_digit_year=True`)
- Valid dates that fall outside calendar range (e.g., Feb 30) correctly return `parsed=False`
