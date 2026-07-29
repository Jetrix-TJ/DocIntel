# Task 6 Report: The two classification branches with no test at all

## Branches covered

### Digital Direction (`tests/packs/test_digitaldirection_ladder.py`)

Added `doc_type_for` to the existing import line, then appended four tests:

- `test_a_credit_memo_title_wins_over_everything` — asserts
  `doc_type_for(ctx) == ("credit_memo", "credit_memo_title")`.
- `test_suspension_language_without_current_charges_is_a_disconnect_notice` —
  asserts `doc_type_for(ctx) == ("disconnect_notice", "suspension_without_current_charges")`.
- `test_a_bill_that_merely_warns_about_disconnection_is_still_a_bill` — negative
  case: suspension language **with** a current-charges block stays
  `("telecom_bill", "default")`.
- `test_an_account_summary_naming_statements_is_still_a_bill` — negative case:
  an `Account Summary` page with "statement" printed twice stays
  `("telecom_bill", "default")`. Docstring states this pack has no statement
  type on purpose (per the module docstring's Centracom/$20,123.80 rationale).

All four assert the full `(doc_type, signal)` tuple, not just the type.

Note on the brief's snippet: this file's real `_ctx(text: str)` takes the raw
page text directly and builds the page internally — it does **not** take a
`PageText` object. The brief's snippet wrote `_ctx(_page(text))`, which would
have raised a type error. I used the file's actual helper, `_ctx(text)`.

### Northstar (`tests/packs/test_northstar_ladder.py`)

Added two tests for `statement_of_account`, using the file's existing
`_page`/`_ctx` helpers (unchanged signatures):

- `test_a_statement_title_with_no_table_is_a_statement_of_account` — title
  present, no line with 3+ money tokens → `("statement_of_account",
  "statement_title_no_table")`.
- `test_a_statement_title_with_a_table_is_not_a_statement_of_account` —
  title present but a line carries 3 money tokens (a table) → falls through to
  `("standard_invoice", "default")`.

Avoided the fixture trap the task warned about: neither fixture contains the
phrase "northstar recycling" (the `_is_own_paperwork` letterhead pattern), so
neither risks tripping `own_paperwork` instead of the intended branch. Both
fixtures are single-page with the default `primary` role, so
`invoice_with_attachment` (which needs a supporting page) cannot fire either.

## Meaningfulness evidence (perturb / observe / restore)

For each test below I edited the fixture in place, ran the single test with
`pytest -k <name>`, confirmed a `FAILED` with the expected wrong tuple, then
reverted the edit with a matching `Edit` call.

1. **DD credit_memo** — replaced `Credit Memo` with `PERTURBED NO SIGNAL WORD`.
   Result: `AssertionError: ('telecom_bill', 'default') == ('credit_memo',
   'credit_memo_title')` → FAILED. Restored the original text; re-ran, PASSED.

2. **DD disconnect_notice** — changed `Balance Due 1,204.00` to
   `Current Charges 412.00` (i.e., added the current-charges block the signal
   requires to be absent). Result: `AssertionError: ('telecom_bill', 'default')
   == ('disconnect_notice', 'suspension_without_current_charges')` → FAILED.
   Restored the original line; re-ran, PASSED.

3. **DD negative (merely warns)** — removed the `Current Charges 412.00` line
   from the fixture that is supposed to carry both suspension language and a
   current-charges block. Result: `AssertionError: ('disconnect_notice',
   'suspension_without_current_charges') == ('telecom_bill', 'default')` →
   FAILED (the fixture now correctly becomes a disconnect notice, proving the
   negative assertion was pinned on the current-charges half actually being
   present). Restored; re-ran, PASSED.

4. **Northstar statement_of_account (positive)** — replaced `Statement of
   Account` with `PERTURBED NO TITLE`. Result: `AssertionError:
   ('standard_invoice', 'default') == ('statement_of_account',
   'statement_title_no_table')` → FAILED. Restored; re-ran, PASSED.

5. **Northstar statement_of_account (negative/table)** — reduced the fixture's
   table line from three money tokens to one (`100.00 Total Due` instead of
   `100.00 200.00 300.00 Total Due`). Result: `AssertionError:
   ('statement_of_account', 'statement_title_no_table') == ('standard_invoice',
   'default')` → FAILED (fixture now correctly becomes a statement, proving the
   "no table" half of the negative assertion was load-bearing). Restored;
   re-ran, PASSED.

All five perturbations produced the expected failure, and all five were
restored to their original committed text before the final full-suite run.

## Branches found already covered / unreachable

None. All four target branches (DD `credit_memo`, DD `disconnect_notice`, and
both halves of Northstar `statement_of_account`) were previously completely
untested, matching the brief. No branch was unreachable.

## Real bugs found

None. All new tests passed on first run, confirming the ladder branches behave
as documented in the source. No source files were touched.

## Scorecard

| | Before | After |
|---|---|---|
| pytest | 1501 passed, 12 skipped | 1507 passed, 12 skipped (6 new tests, all green) |
| gold replay assertions | 203/263 | 203/263 (unchanged) |
| documents green | 1/10 (`northstar-dtss-6060`) | 1/10 (unchanged) |
| mypy | clean | clean |
| ruff | clean | clean |
| validate_gold.py | 95 checks, 0 failures | 95 checks, 0 failures |

Full verification commands run, in order, after all perturb/restore cycles
were complete:

```
python3 -m pytest -q                     # 1507 passed, 12 skipped
python3 -m mypy                          # Success: no issues found in 27 source files
ruff check src tests                     # All checks passed!
python3 docs/corpus/validate_gold.py     # 95 checks, 0 failures
python3 -m docintel.cli replay-gold      # 203/263, 1/10 documents green (exit 1, expected)
```

## Files changed

- `tests/packs/test_digitaldirection_ladder.py` — added `doc_type_for` import,
  appended 4 tests.
- `tests/packs/test_northstar_ladder.py` — appended 2 tests.
- No file under `src/` was modified. No `docs/corpus/gold/*.json` was touched.

One pre-existing unrelated modification, `docs/superpowers/plans/2026-07-29-weakness-remediation.md`,
was already present in the working tree before this task started (not made by
me) and was deliberately left uncommitted and untouched — it is out of this
task's scope.

## Commit

`00a7cf4` — `test(packs): cover the four untested ladder branches`

## Self-review

- Every new test asserts the full `(doc_type, signal_that_fired)` tuple, not
  just the type string — stronger than an index-0 check, and it is what pins
  *which* branch fired, per the brief's guidance.
- Checked both DD fixtures and both Northstar fixtures against the
  `own_paperwork` first-four-lines trap and the `_short_line_has` /
  line-length trap: none of the six new fixtures contain "northstar
  recycling", none rely on prose-line length distinguishing signals (this
  task's signals are title regexes and a current-charges/table presence
  check, not the short-line banner checks), so that trap does not apply here.
- Verified none of the six new fixtures accidentally satisfy an earlier rung
  of either ladder (checked against `_CREDIT_MEMO`, `_UNIT_RATE`,
  primary/supporting counts, and `_NORTHSTAR_LETTERHEAD` by inspection of the
  source regexes).
- Output of all verification commands is clean; `replay-gold`'s exit 1 is
  expected per the task's stated full-verification command.

## Issues or concerns

None. This was a coverage-only task; all tests passed on first run as
expected for characterisation tests, and each was independently confirmed
capable of failing via perturbation.
