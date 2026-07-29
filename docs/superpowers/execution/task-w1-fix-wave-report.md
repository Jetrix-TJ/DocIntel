# Fix-wave report — whole-branch review remediation

Base: `dev` at `f5f0423`. Final: `0d9107a`. Five commits, no gold-file edits.

```
b34c22b docs(grammar,extract): correct three false claims found by whole-branch review
dbdf077 fix(core): move normalize_name into core.senders to break the packs import
3019bd3 fix(pipeline): set possible_duplicate_of before beforeEmit fires
9910c78 fix(extract): enforce OCR completeness on all branches and classify it right
0d9107a refactor(core): drop IdentityIndex.see and document _first's unbounded growth
```

## Scorecard

Before: 203/263, 1/10 green. After: 203/263, 1/10 green. Unchanged, as required
(`python3 -m docintel.cli replay-gold`, exit 1 both times — expected, not a
broken build).

## Group A — merge-blocking corrections (all verified true before editing)

### A1. `tests/grammar/ops/test_infer.py::test_a_roster_supplied_name_is_never_tagged`

Verified independently before touching anything:
- Counted `"field": "bill_to_name"` selectors in all ten persona JSONs:
  `comcast`, `windstream`, `edco`, `upak`, `veritiv` = 0; the other five ≥ 1.
  Matches the finding exactly.
- Read `_roster_match` (`infer.py:365-386`): a plain `re.search` over the whole
  primary-page text, no head-of-line requirement, unlike `_candidate_lines`
  (`infer.py:285-307`).

Rewrote the docstring to state the gap plainly (rung 2 cannot detect a wrong
inbox because it *is* the roster it would need to check against; five of ten
personas always take it; the mechanism that makes it unsafe). Assertions
unchanged. Also trimmed the section-banner comment above the test group to
point at the test's docstring instead of duplicating the explanation.

Covering test: `python3 -m pytest tests/grammar/ops/test_infer.py -q` →
all passed (part of the 1508 total below; this file's tests unchanged in
count, docstring-only edit).

### A2. `src/docintel/grammar/schema.py:181-186` (`anchor_occurrence` comment)

Verified by instrumenting the real `Executor._find_anchors` against the actual
corpus PDFs (not just grepping text):
- `veritiv`: anchor `"VERITIV OPERATING COMPANY"` → exactly 2 hits on the
  primary page; `last` (index -1) lands on the remittance block. Matches.
- `windstream`: anchor `"WINDSTREAM"` → exactly 2 hits on the (single) primary
  page; `last` lands on the remittance block. Matches.
- `edco`: anchor `"EDCO WASTE & RECYCLING SERVICE"` → **3** hits on the
  primary page (y≈33 letterhead, y≈165 remittance block, y≈304
  "FOR SERVICE AT:" header). `last` (index -1) lands on the **third**
  occurrence — the service-location header, not the remittance block. The
  comment's claim ("the occurrence... is the LAST one" for all three
  personas) is false for edco specifically, which is exactly why `edco`'s
  actual `remit_address` selector still anchors on the literal value
  `"P.O. BOX 5488"` rather than the payee name, and remains in
  `ANCHOR_IN_VALUE_DEBT`.

Corrected the comment to state veritiv/windstream print exactly twice (so
`last` is correct for them) and edco prints three times (so `last` is wrong
for it), with the reasoning for why edco is not a one-line fix.

Covering test: `python3 -m pytest tests/packs/test_no_hardcoded_values.py -q`
and the full grammar/schema suite — passed (comment-only change, no assertion
touched).

### A3. `src/docintel/extract/normalize.py` (bimodality claim, 3 locations)

Verified by running `pdf.read_meta` directly on the three named corpus PDFs:

```
Comcast:    p1 1320  p2 58  p3 1900  p4 144  p5 144  p6 144
Centracom:  p1 1430 p2 1423 p3 4743 p4 2789 p5 2795 p6 2803 p7 2721 p8 2813 p9 675 p10 60
Windstream: p1 2180  p2 4246  p3 3461  p4 160
```

Confirms Comcast p2 (58, margin 8 above the 50-char threshold) and Centracom
p10 (60, margin 10) are the two nearest pages — exactly the numbers the review
cited. Corrected the module docstring, the `NATIVE_CHAR_THRESHOLD` inline
comment (now "chars per PAGE", not "a document"), and the routing-decision
comment in `_load_document_uncached` to state the measured per-page margin
instead of the false "0 or 500+, never mixed" per-page claim. `NATIVE_CHAR_THRESHOLD`
itself is untouched (Wave 2, re-baseline required).

Covering test: `python3 -m pytest tests/extract/test_normalize.py -q` → 20
passed (comment-only portion of this file; code changes covered separately
under B3-B5 below).

## Group B — code fixes

### B1. `core.senders` / `packs.registry` import cycle risk

Moved `normalize_name` from `packs/registry.py` into `core/senders.py`;
`packs/registry.py` now does `from docintel.core.senders import normalize_name
as normalize_name` (explicit re-export, satisfies ruff F401). `core/senders.py`
no longer imports anything from `packs`.

Verification:
- `grep -rn "def normalize_name" src/` → exactly one hit
  (`src/docintel/core/senders.py:50`).
- `python3 -c "import docintel.packs.registry as r, docintel.core.senders as s; assert r.normalize_name is s.normalize_name"`
  → passes (same function object).
- All four existing callers (`digitaldirection/__init__.py`, `.aliases`,
  `northstar/__init__.py`, `.aliases`) still import
  `from docintel.packs.registry import normalize_name` unchanged and resolve.
- `python3 -m pytest -q` → 1508 passed / 12 skipped.
- `ruff check src tests` and `python3 -m mypy` → clean.

### B2. `possible_duplicate_of` set after `beforeEmit`

Moved the `IdentityIndex.peek()` call above `self.hooks.run("beforeEmit", ctx)`
in `Runner._emit`. `commit()` is untouched — still after
`build_record`/`validate_record` succeed.

Verification: `python3 -m pytest tests/pipeline/test_runner.py
tests/test_invariant.py -q` → all passed (both suites are part of the 1508
total; specifically re-run in isolation to confirm the duplicate-detection and
emit-invariant tests still hold after the reorder).

### B3. Dead `or` in the mixed-OCR branch

`ocred.get(m.page_number) or native[m.page_number]` → `ocred[m.page_number] if
m.page_number in ocred else native[m.page_number]`. Same behaviour today
(the `missing` check above guarantees no dead branch is hit), but no longer
silently depends on `PageText` staying falsy-averse.

### B4. Completeness invariant only on the mixed branch

Factored the missing-page check into `_ocr_and_check_complete(path,
page_numbers) -> dict[int, PageText]`; both the all-scanned branch
(`len(starved) == len(meta)`) and the mixed branch now call it. Added
`test_the_all_scanned_branch_also_enforces_completeness` (monkeypatches
`ocr.ocr_pages` to return a short result on an all-scanned synthetic PDF) to
cover the previously-unchecked branch, alongside the renamed short-result test
for the mixed branch.

### B5. `TransientError` vs `PermanentError` — my judgement

**Decision: reclassified to `PermanentError`.**

Reasoning:
- The only reachable trigger is `pdf.read_meta` naming a page that
  `pdfplumber.pages` does not — a deterministic, structural mismatch specific
  to that file. Retrying calls `ocr.ocr_pages` again with the same arguments
  and gets the same answer; nothing about a wall-clock delay or a fresh
  attempt changes the outcome.
- It is actively counterproductive to retry: `ocr.ocr_pages` writes its result
  to the on-disk OCR cache (`ocr_cache.py`, via `ocr.py:51`) *before*
  `_ocr_and_check_complete`'s check runs. The first attempt caches the short
  result; every subsequent attempt — in the same process or a fresh one run
  hours later — reads that same incomplete result back from cache rather than
  re-running tesseract. Calling this "transient" invites `_run_one` to spend
  `max_retries` attempts that cannot ever see a different answer.
- Precedent already in the codebase: `adapters/vision/anthropic_adapter.py`
  draws exactly this line — 5xx/unreachable → `TransientError` (genuinely
  retry-worthy), 4xx/malformed/structural → `PermanentError`. This failure is
  the structural kind.
- Checked `Runner._run_one`: it only special-cases `TransientError` (retry
  loop); any other exception, including `PermanentError`, propagates
  immediately to `Runner.process`'s blanket `except Exception`, which sets
  `disposition = "dead_letter"`, `review_flag = True`, and still calls
  `self._emit(ctx)` — so `count(intaken) == count(emitted)` is not weakened;
  the only observable change is that this specific, unfixable failure now
  dead-letters after 1 attempt instead of after `max_retries + 1`.
- Updated `tests/extract/test_normalize.py`'s covering test
  (renamed `test_ocr_returning_a_short_result_raises_permanent_not_silently_falls_back`,
  now asserts `pytest.raises(PermanentError)`) and its docstring to carry the
  same reasoning inline.

Covering tests: `python3 -m pytest tests/extract/test_normalize.py -q` → 20
passed; `python3 -m pytest tests/pipeline/test_runner.py -q` → passed
(confirms `_run_one`'s retry/no-retry split is unaffected for other error
types).

### B6. `duplicates.py` — two loose ends

- **`IdentityIndex.see`**: confirmed via `grep -rn "\.see(" src/` that it had
  zero callers in `src/` (only `Runner._emit`, which always uses
  `peek`/`commit` separately, per the class's own docstring history). Dropped
  it rather than mark it test-only, since an unused public method inviting a
  future caller to reintroduce the exact bug the peek/commit split fixed is
  worse than removing it. Rewrote all four `see`-based unit tests in
  `tests/core/test_duplicates.py` to compose `peek()` + `commit()` via a
  small private test-only helper (`_see`) — coverage is unchanged, same
  assertions, same scenarios.
- **`_first` unbounded growth**: confirmed `_cmd_process`
  (`src/docintel/cli.py:58-59`) builds exactly one `Runner` per batch, so
  `_first` lives for one batch's lifetime. Documented in the class docstring
  why no eviction was added: an evicted identity is a silently missed
  duplicate (the exact failure this module exists to prevent), unlike
  `extract.normalize`'s `_load_document_cached` memo (bounded at 64), where a
  stale eviction just costs a re-parse of the PDF — a real fallback that
  duplicates.py has no equivalent of.

Covering tests: `python3 -m pytest tests/core/test_duplicates.py -q` → 9
passed (same 9 test functions as before, `see`-based coverage preserved via
`_see`).

## Full verification (final state, `HEAD` = `0d9107a`)

```
$ python3 -m pytest -q
1508 passed, 12 skipped in ~15-23s   (baseline was 1507 passed; +1 new test, B4)

$ python3 -m mypy
Success: no issues found in 27 source files

$ ruff check src tests
All checks passed!

$ python3 docs/corpus/validate_gold.py
gold documents : 10
checks run     : 95
failures       : 0
all gold labels are internally consistent ✓

$ python3 -m docintel.cli replay-gold
FAIL  digitaldirection-centracom-0384043574  (26/29)
FAIL  digitaldirection-comcast-8495444620365242  (25/29)
FAIL  digitaldirection-lumen-5-QXH7QKM7  (26/29)
FAIL  digitaldirection-windstream-041069076  (24/27)
FAIL  northstar-complete-beverage-32930  (19/25)
PASS  northstar-dtss-6060  (19/19)
FAIL  northstar-edco-077087  (16/26)
FAIL  northstar-federal-recycling-1330123  (16/23)
FAIL  northstar-upak-4378107  (12/25)
FAIL  northstar-veritiv-715-33905296  (20/31)
1/10 documents green
(exit 1, expected)
```

Scorecard: 203/263 before and after, 1/10 green before and after. No
`docs/corpus/gold/*.json` file touched (`git diff --stat f5f0423 HEAD --
docs/corpus/gold/` is empty).

## What I chose not to do, and why

- **Did not touch `NATIVE_CHAR_THRESHOLD`, `_roster_match`'s matching rule, or
  gate ordering** — explicitly out of scope; both A1 and A3 identify real
  gaps but fixing either changes which rendering some corpus documents
  resolve to, requiring the re-baseline already budgeted as Wave 2 work.
- **Did not restructure `ocr.py`'s caching** (B5's "worse" clause references
  it, but the cache-then-check ordering itself is out of scope per the brief).
- **Did not mark `IdentityIndex.see` test-only instead of dropping it** —
  chose the drop-and-rewrite path since the method had no production caller
  and the whole point of the peek/commit split was to prevent exactly the
  kind of single fused call `see` still offered to a future caller.
- All five Group A/B findings were independently re-verified against the real
  code and corpus PDFs before any edit (persona selector counts, live anchor
  occurrence counts via `Executor._find_anchors`, and per-page char counts via
  `pdf.read_meta`) — all matched the review's claims exactly, so nothing was
  contested or reverted.
