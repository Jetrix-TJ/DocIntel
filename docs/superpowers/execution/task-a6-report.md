# Task A6 Report: Hook Sockets with Failure Isolation

**Status:** DONE

## Files Created

- `src/docintel/pipeline/__init__.py` (empty)
- `src/docintel/pipeline/hooks.py` (62 lines, implementation)
- `tests/pipeline/test_hooks.py` (63 lines, 7 tests)

## Implementation Notes

Transcribed the code from task-a6-brief.md verbatim. No design changes or deviations from the specification.

### Key Design Points Implemented

1. **8 hook sockets** (tuple): `beforeIntake`, `afterFilter`, `classifySignals`, `beforePersonaLookup`, `afterExtraction`, `beforeConfidenceGate`, `beforeEmit`, `onRegenTrigger`
2. **Type aliases**: `Next` and `HookFn` for middleware chain callables
3. **HookRegistry class** with three public methods:
   - `register(socket, fn, pack)` — validates socket name, appends hook to chain
   - `run(socket, ctx)` — executes chain or returns same context if empty
   - `registered(socket)` — returns list of pack-qualified names
4. **Recursive closure dispatch** with proper error isolation:
   - `PackError` re-raised without wrapping (prevents message accumulation)
   - Other exceptions wrapped in `PackError` naming the pack, socket, and hook
   - Empty socket returns same context object (identity preserved with `is`)

## Verification Results

All checks pass:

```bash
$ python3 -m pytest tests/pipeline/test_hooks.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.0, pytest-9.0.2, pluggy-1.6.0
collecting ... collected 7 items

tests/pipeline/test_hooks.py::test_eight_sockets_exactly PASSED          [ 14%]
tests/pipeline/test_hooks.py::test_registering_an_unknown_socket_fails_loudly PASSED [ 28%]
tests/pipeline/test_hooks.py::test_chain_runs_in_registration_order PASSED [ 42%]
tests/pipeline/test_hooks.py::test_hook_can_short_circuit_by_not_calling_next PASSED [ 57%]
tests/pipeline/test_hooks.py::test_a_throwing_hook_raises_PackError_naming_the_pack PASSED [ 71%]
tests/pipeline/test_hooks.py::test_empty_socket_is_a_no_op PASSED        [ 85%]
tests/pipeline/test_hooks.py::test_registered_reports_pack_qualified_names PASSED [100%]

============================== 7 passed in 0.02s ===============================
```

**Whole Suite:**
```bash
$ python3 -m pytest -q
........................................................................ [ 65%]
......................................                                   [100%]
110 passed in 0.09s
```
Test count: 103 (baseline) + 7 (new hooks tests) = **110 tests, all pass**

**Type Checking:**
```bash
$ python3 -m mypy src/docintel/core --strict
Success: no issues found in 7 source files
```

**Gold Validation:**
```bash
$ python3 docs/corpus/validate_gold.py
gold documents : 10
checks run     : 95
failures       : 0
all gold labels are internally consistent ✓
```

**Code Quality:**
```bash
$ ruff check src tests
All checks passed!
```

## Commit

```
Commit: 73d430b
Message: feat(pipeline): 8 hook sockets with chain dispatch and failure isolation
Branch: feat/pipeline
```

## Fix round 1

Applied four critical fixes from coordinator review to harden the module against pack code bugs:

### Finding 1 (Critical) — Hook return value validation
- **Issue**: Hooks returning None, dict, str, etc. were passed to caller with no error, crashing later stages with unclear errors
- **Fix**: Added isinstance check on result; raises PackError naming pack, socket, and returned type
- **Test**: `test_hook_returning_none/dict/str_raises_PackError`

### Finding 2 (Important) — Chain snapshotting
- **Issue**: Hooks could register new hooks mid-dispatch and splice themselves into running chain
- **Fix**: Changed `chain = self._chains[socket]` to `chain = tuple(self._chains[socket])` at start of `run()`
- **Test**: `test_hook_registering_mid_dispatch_does_not_affect_current_run`

### Finding 3 (Minor) — One-shot guard on `next()`
- **Issue**: Hook calling `next()` twice silently re-executed downstream chain
- **Fix**: Wrapped nxt function passed to each hook with tracked_next that guards against multiple calls
- **Test**: `test_hook_calling_next_twice_raises_PackError`

### Finding 4 (Minor) — Module docstring
- **Issue**: Docstring described mechanism but not the real-world problem (like other core modules)
- **Fix**: Updated to state plainly: "A domain pack must customize every stage without forking. Bugs in pack code must not crash the run."

### Additional Tests (malformed pack cases)
Added 8 new tests covering pack failure modes:
- Return type validation (None, dict, str)
- One-shot guard on next()
- Mid-dispatch registration isolation
- MemoryError wrapping (locks in Exception handling, not BaseException)
- KeyboardInterrupt propagation (locks in non-wrapping behavior)
- Context substitution through chain (locks in legitimate functional style)

### Verification after fixes

```bash
$ python3 -m pytest tests/pipeline/test_hooks.py -v
collected 15 items
tests/pipeline/test_hooks.py::test_eight_sockets_exactly PASSED          [  6%]
tests/pipeline/test_hooks.py::test_registering_an_unknown_socket_fails_loudly PASSED [ 13%]
tests/pipeline/test_hooks.py::test_chain_runs_in_registration_order PASSED [ 20%]
tests/pipeline/test_hooks.py::test_hook_can_short_circuit_by_not_calling_next PASSED [ 26%]
tests/pipeline/test_hooks.py::test_a_throwing_hook_raises_PackError_naming_the_pack PASSED [ 33%]
tests/pipeline/test_hooks.py::test_empty_socket_is_a_no_op PASSED        [ 40%]
tests/pipeline/test_hooks.py::test_registered_reports_pack_qualified_names PASSED [ 46%]
tests/pipeline/test_hooks.py::test_hook_returning_none_raises_PackError PASSED [ 53%]
tests/pipeline/test_hooks.py::test_hook_returning_dict_raises_PackError PASSED [ 60%]
tests/pipeline/test_hooks.py::test_hook_returning_str_raises_PackError PASSED [ 66%]
tests/pipeline/test_hooks.py::test_hook_calling_next_twice_raises_PackError PASSED [ 73%]
tests/pipeline/test_hooks.py::test_hook_registering_mid_dispatch_does_not_affect_current_run PASSED [ 80%]
tests/pipeline/test_hooks.py::test_MemoryError_is_wrapped_as_PackError PASSED [ 86%]
tests/pipeline/test_hooks.py::test_KeyboardInterrupt_propagates_raw PASSED [ 93%]
tests/pipeline/test_hooks.py::test_hook_passing_different_context_to_next_still_works PASSED [100%]

============================== 15 passed in 0.03s ===============================
```

**Whole Suite:**
```bash
$ python3 -m pytest -q
........................................................................ [ 61%]
..............................................                           [100%]
118 passed in 0.09s
```
Test count: 103 (baseline) + 7 (original) + 8 (fix round 1) = **118 tests, all pass**

**Type Checking:**
```bash
$ python3 -m mypy src/docintel/core --strict
Success: no issues found in 7 source files
```

**Gold Validation:**
```bash
$ python3 docs/corpus/validate_gold.py
gold documents : 10
checks run     : 95
failures       : 0
all gold labels are internally consistent ✓
```

**Code Quality:**
```bash
$ ruff check src tests
All checks passed!
```

## Commits

1. **73d430b**: feat(pipeline): 8 hook sockets with chain dispatch and failure isolation
2. **3f5bafc**: fix(pipeline): add fix round 1 for hooks - validation, snapshotting, one-shot guard, and tests

## Rejected Findings (preserved intentionally)

Per coordinator: Do NOT catch `BaseException` — catches only `Exception`, allowing `KeyboardInterrupt`, `SystemExit`, `GeneratorExit` to propagate raw (test verifies). Do NOT guard against hooks passing different context to `next()` — legitimate functional transform (test verifies).

## Final Status

All 15 tests pass. All verification checks pass. The module now resists pack code bugs at all critical surfaces: return types, call counts, registration timing, exception wrapping, and context flow.
