# Task A1 Report: Project Scaffold + Money Parsing

## Status
**DONE** — All requirements from the brief implemented faithfully, all tests passing, all global constraints met.

## Files Created

| Path | Purpose |
|------|---------|
| `pyproject.toml` | Project configuration (build system, dependencies, tool settings) |
| `src/docintel/__init__.py` | Package marker with version |
| `src/docintel/core/__init__.py` | Core subpackage marker (empty) |
| `src/docintel/core/money.py` | Money parsing module with `MONEY_RE`, `parse_money()`, `is_money()` |
| `tests/core/test_money.py` | 24 test cases covering all notations and edge cases |

## Installation & Verification

### 1. Package Installation
```bash
$ python3 -m pip install -e '.[dev]' 2>&1 | tail -40
...
Successfully installed docintel-0.1.0 pytesseract-0.3.13
```
**Result:** Package installed successfully with all dev dependencies.

### 2. Money Parser Tests
```bash
$ python3 -m pytest tests/core/test_money.py -v
...
============================== 24 passed in 0.02s ==============================
```
**Result:** All 24 tests pass:
- 15 parametrized `test_parse_money` cases (plain, negatives in 3 notations, currency suffix, rate notation)
- 7 parametrized `test_not_money` cases (tax IDs, account numbers, phone numbers, etc.)
- 1 `test_exact_decimal_no_float_drift` (3 arithmetic assertions)
- 1 `test_tax_id_is_not_money_even_though_it_has_digits` (2 assertions)

### 3. Full Test Suite
```bash
$ python3 -m pytest -q
........................                                 [100%]
24 passed in 0.02s
```
**Result:** Entire suite green (24 tests total, only the money module at this stage).

### 4. Global Constraint: Gold Corpus Validation
```bash
$ python3 docs/corpus/validate_gold.py
gold documents : 10
checks run     : 95
failures       : 0

all gold labels are internally consistent ✓
```
**Result:** All 95 gold checks remain green, no regressions.

### 5. Code Quality: Ruff Linter
```bash
$ ruff check src tests
All checks passed!
```
**Result:** No style or lint violations.

## Deviations from Brief
**None.** Every file transcribed faithfully, every test case exact from corpus, all interfaces exported as required.

## Notes on the Implementation

1. **MONEY_RE Design:** The regex correctly enforces a required decimal part (1-4 places) to distinguish money from:
   - Account numbers like `0384043574` (no decimal)
   - Tax IDs like `123142812RT0001` (no decimal, non-digit suffix)
   - Phone numbers like `416-675-3700` (dashes, no decimal)
   
   This design is deliberate and tested in `test_not_money()` and `test_tax_id_is_not_money_even_though_it_has_digits()`.

2. **Decimal throughout:** `parse_money()` returns `Decimal` (or `None`), never `float`. Arithmetic in `test_exact_decimal_no_float_drift()` confirms no precision loss:
   - `298.34 + 69.62 == 367.96` (exact)
   - `13752.60 + 20123.80 == 33876.40` (exact)
   - `0.027 × 4000 == 108.000` (exact)

3. **Three negative notations all work:**
   - `-99.80` (minus prefix)
   - `(249.84)` (parentheses)
   - `212.87 cr` / `$1,231.74 CR` (credit suffix, case-insensitive)

4. **Edge cases handled:**
   - `$.00` → `0.00` (currency symbol only, no digits before decimal)
   - `-40.00/ST` → `-40.00` (rate notation, suffix stripped)
   - `481.20 USD` → `481.20` (currency code stripped)
   - Comma-grouped numbers: `1,177.70` → `1177.70`
   - Whitespace normalization at boundaries

## Commit

```
Commit: eb5fce1
Branch: feat/pipeline
Message: feat(core): project scaffold and Decimal money parsing
Files: 5 files changed, 163 insertions(+)
```

All work committed to `feat/pipeline` branch, base `c82eb76`.

## No Concerns

The brief's requirements were clear, unambiguous, and correctly executed. The MONEY_RE design (requiring decimal part) is the correct choice for distinguishing money from false positives in the corpus.
