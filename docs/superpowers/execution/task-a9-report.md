# Task A9 Report: Filesystem Intake Adapter & CLI

## Status
**DONE**

## Files Created
- `src/docintel/adapters/intake/__init__.py` — Package marker
- `src/docintel/adapters/intake/port.py` — Port definitions (IntakeItem, IntakeSource protocol)
- `src/docintel/adapters/intake/filesystem.py` — FilesystemIntake implementation with stable ID derivation
- `src/docintel/cli.py` — Command-line entry point with `process` and `replay-gold` subcommands
- `tests/adapters/__init__.py` — Test package marker
- `tests/adapters/test_filesystem_intake.py` — Intake adapter tests (3 tests)
- `tests/test_cli_process.py` — CLI process command tests (3 tests)

## Commit
- **SHA:** `3fd6ce7`
- **Branch:** `feat/pipeline`
- **Message:** `feat(cli): filesystem intake and docintel process`

## Verification Results

### 1. New Tests (6 tests)
```
$ python3 -m pytest tests/adapters/test_filesystem_intake.py tests/test_cli_process.py -v

tests/adapters/test_filesystem_intake.py::test_ids_are_stable_across_runs PASSED
tests/adapters/test_filesystem_intake.py::test_ids_differ_between_documents PASSED
tests/adapters/test_filesystem_intake.py::test_directory_expands_to_its_pdfs PASSED
tests/test_cli_process.py::test_process_prints_a_valid_record PASSED
tests/test_cli_process.py::test_process_reports_the_invariant PASSED
tests/test_cli_process.py::test_missing_file_is_a_skip_not_a_crash PASSED

6 passed in 0.02s
```

### 2. Full Test Suite (147 tests)
```
$ python3 -m pytest -q

147 passed in 0.10s
```
Previous count was 141 tests; added 6 new tests as specified.

### 3. MyPy Strict Type Check
```
$ python3 -m mypy src/docintel/core --strict

Success: no issues found in 7 source files
```

### 4. Gold Corpus Validation
```
$ python3 docs/corpus/validate_gold.py

gold documents : 10
checks run     : 95
failures       : 0

all gold labels are internally consistent ✓
```

### 5. Ruff Linter
```
$ ruff check src tests

All checks passed!
```

### 6. CLI Human-Readable Output
```
$ python3 -m docintel.cli process docs

processed    low     standard_invoice       docs/CANADIAN WITHOUT NOTES U- PAK 4378107 (1).pdf
processed    low     standard_invoice       docs/CONTRA ONLY Everything already on AR Federal Recycling 1330123.pdf
processed    low     standard_invoice       docs/Centracom_0384043574_01012026_BILL.pdf
processed    low     standard_invoice       docs/Comcast_8495 44 462 0365242_12092025_BILL.pdf
processed    low     standard_invoice       docs/EDCO 77087APR25 current charges can be misleading, paying $69.62.pdf
processed    low     standard_invoice       docs/Lumen - 5-QXH7QKM7.pdf
processed    low     standard_invoice       docs/Windstream_041069076_07222025_BILL.pdf
processed    low     standard_invoice       docs/_AP Invoice 32930 Complete Beverage Destruction 1177.70000.pdf
processed    low     standard_invoice       docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf
processed    low     standard_invoice       docs/_AP Invoice 715-33905296    Veritiv Operating Company 4908.00000.pdf

Exit code: 0
```
10 lines emitted (one per document in corpus). Invariant satisfied: intaken == emitted.

### 7. CLI JSON Output (First 2 Records)
```
$ python3 -m docintel.cli process docs --json | head -2

{"schema_version":"1","document_id":"fs-c8e849b5b0e4ea4f","doc_type":"standard_invoice",...,"disposition":"processed","lane":"low"}
{"schema_version":"1","document_id":"fs-cbe91ddc6a5774e3","doc_type":"standard_invoice",...,"disposition":"processed","lane":"low"}
```
Both records contain required fields: `schema_version`, `disposition`, `lane`.

### 8. Console Script Entry Point
```
$ docintel process "docs/Lumen - 5-QXH7QKM7.pdf"

processed    low     standard_invoice       docs/Lumen - 5-QXH7QKM7.pdf
```
Entry point declared in `pyproject.toml` (`docintel = "docintel.cli:main"`) is installed and functional.

## Implementation Notes

**Stable Document ID:**
- Derived from absolute path + file size using SHA256 hash (first 16 chars)
- Prefixed with `"fs-"` to distinguish from other sources
- Handles missing files gracefully (size = -1 if OSError)
- IDs stable across multiple reads of same file (test confirms)

**Filesystem Traversal:**
- Treats directory arguments as directories, expands to sorted `.pdf` files
- Treats file arguments as files (whether or not they exist)
- Missing files yielded as IntakeItem; Pipeline handles as skip

**Invariant Guard:**
- `_cmd_process` checks `stats["intaken"] != stats["emitted"]` after pipeline completes
- Returns exit code 2 on violation (logs to stderr)
- All 10 corpus documents successfully emitted; no silent drops

**Deferred Import Pattern:**
- `_cmd_replay_gold` imports `docintel.scorecard.replay_gold` inside function body
- `scorecard.py` does not exist yet (arrives Task A10)
- No changes to this pattern per spec; CLI imports cleanly; `process` subcommand fully functional

## Deviations
None. All code transcribed verbatim from brief.

---

## Fix Round 1: Spec Compliance Corrections

### Findings Addressed
1. **FINDING 1 (Important):** A directory named `archive.pdf` was being yielded as an `IntakeItem` and processed as a document, while real PDFs inside it were invisible.
2. **FINDING 2 (Important):** No recursion meant PDFs one directory down were completely invisible — not skipped, not dead-lettered, not counted in `intaken` (violates Stage 1 invariant).
3. **FINDING 3 (Minor):** Exit code 0 could indicate "every document emitted" (correct) but an operator reading only the code might assume it meant "every document was clean". No disambiguation.

### Code Changes
- **`FilesystemIntake.items()`** now delegates directory handling to a new `_walk()` static method
- **`_walk()` uses `os.walk()`** which separates directories from files in different lists, preventing `archive.pdf/` directories from being mistaken for documents
- **Recursive traversal** via `os.walk()` ensures nested PDFs are found; `dirnames.sort()` + `sorted(filenames)` keeps traversal deterministic
- **Single-path branch** still yields missing/unreadable paths so the filter stage can skip them with a reason
- **CLI now imports `Counter`** and tallies dispositions per document
- **Summary line added** (human-readable mode only): `"10 emitted (10 processed)"` format shows per-disposition breakdown
- **Subparser description added** to `process` command explaining exit code semantics explicitly

### Test Results (9 total: 6 original + 3 new)
```
$ python3 -m pytest tests/adapters/test_filesystem_intake.py tests/test_cli_process.py -v

tests/adapters/test_filesystem_intake.py::test_ids_are_stable_across_runs PASSED
tests/adapters/test_filesystem_intake.py::test_ids_differ_between_documents PASSED
tests/adapters/test_filesystem_intake.py::test_a_directory_named_like_a_pdf_is_not_mistaken_for_a_document PASSED
tests/adapters/test_filesystem_intake.py::test_nested_pdfs_are_found_not_silently_ignored PASSED
tests/adapters/test_filesystem_intake.py::test_traversal_order_is_deterministic PASSED
tests/adapters/test_filesystem_intake.py::test_directory_expands_to_its_pdfs PASSED
tests/test_cli_process.py::test_process_prints_a_valid_record PASSED
tests/test_cli_process.py::test_process_reports_the_invariant PASSED
tests/test_cli_process.py::test_missing_file_is_a_skip_not_a_crash PASSED

9 passed in 0.03s
```

### Full Test Suite
```
$ python3 -m pytest -q

150 passed in 0.10s
```
All tests green (147 baseline + 3 new from fix round).

### Critical Test Verification
**`test_directory_expands_to_its_pdfs` still reports exactly 10 items:**
Recursion did not increase the count, confirming that `docs/` contains only 10 PDFs in its root with no PDFs in subdirectories (`architecture/`, `corpus/`, `packs/`, `superpowers/`). Recursive walk correctly handles this.

### CLI Output (Human-Readable with Summary)
```
$ python3 -m docintel.cli process docs

processed    low     standard_invoice       docs/CANADIAN WITHOUT NOTES U- PAK 4378107 (1).pdf
processed    low     standard_invoice       docs/CONTRA ONLY Everything already on AR Federal Recycling 1330123.pdf
processed    low     standard_invoice       docs/Centracom_0384043574_01012026_BILL.pdf
processed    low     standard_invoice       docs/Comcast_8495 44 462 0365242_12092025_BILL.pdf
processed    low     standard_invoice       docs/EDCO 77087APR25 current charges can be misleading, paying $69.62.pdf
processed    low     standard_invoice       docs/Lumen - 5-QXH7QKM7.pdf
processed    low     standard_invoice       docs/Windstream_041069076_07222025_BILL.pdf
processed    low     standard_invoice       docs/_AP Invoice 32930 Complete Beverage Destruction 1177.70000.pdf
processed    low     standard_invoice       docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf
processed    low     standard_invoice       docs/_AP Invoice 715-33905296    Veritiv Operating Company 4908.00000.pdf

10 emitted (10 processed)
```

**Exit code: 0** (verified with `echo $?`)

### All Verification Passed
- ✓ 9 new tests pass (6 original intake/CLI + 3 new from fix)
- ✓ Full suite 150 green (141 baseline → 150 with all A9 tests)
- ✓ MyPy strict on core: 0 errors
- ✓ Gold corpus validation: 95 checks pass
- ✓ Ruff: clean
- ✓ CLI human output: 10 documents + summary line, exit 0
- ✓ Critical test `test_directory_expands_to_its_pdfs` still passes with count=10

### Commit
- **SHA:** `05bad8d`
- **Branch:** `feat/pipeline`
- **Message:** `fix(cli): filesystem intake with recursion and disposition summary`
