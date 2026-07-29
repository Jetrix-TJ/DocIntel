# Task 1 Report: A wrong-inbox invoice must not auto-approve

## What I implemented

1. **`src/docintel/core/senders.py`** — added `bill_to_matches_roster(printed, roster)`.
   Imports `normalize_name` from `docintel.packs.registry` (verified not circular:
   `packs/registry.py` imports only `docintel.core.models` and `docintel.pipeline.hooks`,
   neither of which imports `core.senders`; `packs/__init__.py` does not eagerly import
   pack submodules). Exactly one implementation of `normalize_name` still exists, in
   `packs/registry.py`; `senders.py` re-uses it rather than duplicating it.

2. **`src/docintel/grammar/ops/infer.py`** — in `resolve_bill_to_alias`, the `printed
   is not None` branch now calls `bill_to_matches_roster(printed, _pack_bill_to_roster(ctx))`
   and, when it returns `False`, adds the `bill_to_mismatch` tag and logs why. The
   roster-read rung (rung 2) is untouched — it can never disagree with the roster
   because it read the name off the roster in the first place.

3. **`src/docintel/pipeline/stages/s7_gate.py`** — `DEFAULT_FORCED_REVIEW_TAGS` now
   contains `{"has_flattened_annotations", "bill_to_mismatch"}`, with a comment
   explaining why the new tag joins the F3 tag as an unconditional forcing signal.

## Two deviations from the brief's literal code, both verified necessary

- **Step 5 test snippet used `ctx.extracted["bill_to_name"] = ...`.** `ExtractedFields`
  (`core/models.py`) deliberately has no `__setitem__` — its docstring says "Subclassing
  dict does not work here... so `set()` is the single insertion path." Using the literal
  brief code would raise `TypeError: 'ExtractedFields' object does not support item
  assignment`, not the expected `assert 'bill_to_mismatch' in []`. I used
  `ctx.extracted.set("bill_to_name", value, 1.0)` instead, matching every other test in
  the file (e.g. `_ctx`'s `ctx.extracted.set(name, value, 1.0)`). This is exactly the
  kind of fixture-shape mismatch the task's standing rule 7 warns about, so I verified it
  by reading `core/models.py` before writing the test.

- **Step 9 test snippet used `Gate()`.** No symbol named `Gate` exists anywhere in the
  codebase (grepped `src/` and `tests/`); the real class is `ConfidenceGate`
  (`s7_gate.py`), used directly (no alias) everywhere else, including
  `tests/pipeline/test_gate.py`. I used `ConfidenceGate()` directly rather than
  introducing a one-off `ConfidenceGate as Gate` alias, since an alias that exists for a
  single test would only confuse a future reader grepping for `Gate`. All literal
  values, assertions, the tag string, and the roster strings from the brief are
  preserved verbatim.

## TDD Evidence

### Group 1 — `tests/core/test_senders.py` (the comparison)

RED:
```
$ python3 -m pytest tests/core/test_senders.py -q
ImportError while importing test module '.../tests/core/test_senders.py'.
E   ImportError: cannot import name 'bill_to_matches_roster' from 'docintel.core.senders'
```
Expected failure — the function didn't exist yet.

GREEN:
```
$ python3 -m pytest tests/core/test_senders.py -q
....                                                                     [100%]
4 passed in 0.01s
```

### Group 2 — `tests/grammar/ops/test_infer.py -k bill_to` (the tag)

RED:
```
$ python3 -m pytest tests/grammar/ops/test_infer.py -q -k bill_to
..F                                                                      [100%]
FAILED tests/grammar/ops/test_infer.py::test_a_printed_bill_to_off_the_roster_is_tagged
E       AssertionError: assert 'bill_to_mismatch' in []
1 failed, 2 passed, 37 deselected
```
Expected failure — `resolve_bill_to_alias` did not yet compare the printed party
against the roster, so the tag was never added. (The other two new tests passed
trivially since nothing tagged them either — consistent with the brief's intent that
only the mismatch case should currently fail.)

GREEN:
```
$ python3 -m pytest tests/grammar/ops/test_infer.py -q -k bill_to
...                                                                      [100%]
3 passed, 37 deselected
```
Full file: `python3 -m pytest tests/grammar/ops/test_infer.py -q` → `40 passed`.

### Group 3 — `tests/test_f3_forced_review.py -k bill_to` (forced review)

RED:
```
$ python3 -m pytest tests/test_f3_forced_review.py -q -k bill_to
F                                                                        [100%]
FAILED tests/test_f3_forced_review.py::test_a_bill_to_mismatch_forces_review_whatever_the_confidence
E       AssertionError: assert False is True
1 failed, 6 deselected
```
Expected failure — `bill_to_mismatch` was not yet in `DEFAULT_FORCED_REVIEW_TAGS`, so
`ConfidenceGate` had no reason to force review despite 0.99 confidence.

GREEN:
```
$ python3 -m pytest tests/test_f3_forced_review.py -q -k bill_to
.                                                                        [100%]
1 passed, 6 deselected
```

## Scorecard: before and after

Before (baseline, confirmed prior to any change): `202/263`, `1/10 documents green`
(`northstar-dtss-6060` only).

After (full change set):
```
FAIL  digitaldirection-centracom-0384043574  (26/29)
FAIL  digitaldirection-comcast-8495444620365242  (25/29)
FAIL  digitaldirection-lumen-5-QXH7QKM7  (26/29)
FAIL  digitaldirection-windstream-041069076  (24/27)
FAIL  northstar-complete-beverage-32930  (19/25)
PASS  northstar-dtss-6060  (19/19)
FAIL  northstar-edco-077087  (16/26)
FAIL  northstar-federal-recycling-1330123  (16/23)
FAIL  northstar-upak-4378107  (12/25)
FAIL  northstar-veritiv-715-33905296  (19/31)
1/10 documents green
```
Sum of passing assertions: 26+25+26+24+19+19+16+16+12+19 = **202**; sum of totals:
29+29+29+27+25+19+26+23+25+31 = **263**. Identical to baseline — no corpus document
gained the `bill_to_mismatch` tag, confirming all ten are billed to their pack's roster.

## Full verification

```
$ python3 -m pytest -q
1484 passed, 12 skipped in 7.45s

$ python3 -m mypy
Success: no issues found in 26 source files

$ ruff check src tests
All checks passed!

$ python3 docs/corpus/validate_gold.py
gold documents : 10
checks run     : 95
failures       : 0
all gold labels are internally consistent ✓

$ python3 -m docintel.cli replay-gold
... (as above) ...
1/10 documents green
(exit code 1 — expected per brief, not a broken build)
```

`git status --short docs/corpus/gold/` confirmed no changes to the gold files (they
remain untouched, per the read-only constraint).

## Files changed

- `src/docintel/core/senders.py` — added `bill_to_matches_roster`; imports
  `normalize_name` from `packs.registry`.
- `src/docintel/grammar/ops/infer.py` — `resolve_bill_to_alias` now tags
  `bill_to_mismatch` when the printed party is off the roster; imports
  `bill_to_matches_roster`.
- `src/docintel/pipeline/stages/s7_gate.py` — `DEFAULT_FORCED_REVIEW_TAGS` gains
  `bill_to_mismatch`.
- `tests/core/test_senders.py` — new file, 4 tests for the comparison function.
- `tests/grammar/ops/test_infer.py` — appended `_ctx_with_pack_roster` helper and 3
  tests for the tagging behaviour.
- `tests/test_f3_forced_review.py` — appended `_high_confidence_ctx` helper and 1 test
  for forced review.

Commit: `f8abc65 fix(senders): a printed bill-to off the roster forces review`

## Self-review findings

- **Completeness:** all 13 brief steps executed in order; RED confirmed before each
  GREEN.
- **Naming:** `bill_to_matches_roster`, `bill_to_mismatch`, `_ctx_with_pack_roster`,
  `_high_confidence_ctx` all match the brief's specified names. No stray aliases
  introduced (rejected `ConfidenceGate as Gate` — see deviations above).
- **YAGNI:** no scope beyond the brief — did not touch `normalize_name`'s
  implementation (no circularity forced a move), did not add anything to
  `packs/northstar` or `packs/digitaldirection` (their `bill_to_roster` /
  `MANAGED_CLIENTS` properties are consumed as-is via `_pack_bill_to_roster`, already
  existing), did not modify the module docstring in `senders.py` beyond what's needed.
- **Test quality:** each test exercises real behaviour through the public functions
  (`bill_to_matches_roster`, `resolve_bill_to_alias`, `ConfidenceGate.run`), not
  internals. The synthetic fixture (`Contoso Manufacturing Inc` billed-to, off the
  Northstar roster) is exactly the corpus-overfit gap the brief calls out — none of the
  ten corpus documents exercise a mismatch, so this is the one fixture proving the
  behaviour change actually does something.
- **Output pristine:** ran the full suite (`1484 passed, 12 skipped`) — the 12 skips are
  pre-existing, unrelated `printed-fields-only` deferrals documented in
  `s7_gate.py`'s own module docstring, not introduced by this change.

## Issues or concerns

None. The two deviations from the brief's literal test code (documented above) were
required because the literal code referenced APIs that don't exist in this codebase
(`ExtractedFields.__setitem__`, a `Gate` symbol); both were caught by actually running
the fixtures rather than trusting the brief's snippets, per the task's own fixture
warning. All literal values (tag string, roster strings, docstrings, comments,
assertions) were used verbatim. Scorecard held exactly at 202/263, 1/10 — no
corpus-document regression.
