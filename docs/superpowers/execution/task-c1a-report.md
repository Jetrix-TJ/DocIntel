# Task C1a Report: The extract layer — pdf, ocr, normalize

**Status:** DONE

**Scope:** Cluster C1a only (per coordinator instructions narrowing `task-c1-brief.md`):
`src/docintel/extract/{__init__,pdf,ocr,normalize}.py`, the `s2_filter.py` wiring, and
`tests/extract/{__init__,test_normalize}.py`. `pageroles.py`, `annotations.py`, `scanline.py`
and their tests are cluster C1b and were **not** created, per explicit instruction. `PageMeta.role`
is left at its dataclass default `"unknown"`.

**Base commit:** `f18e80e` (branch `feat/pipeline`) — note this differs from the brief's stated
base `40be4e2`; `git log` shows the branch has moved on since, and `f18e80e` is what `git rev-parse
--short HEAD` reported at the start of this task. Working tree was clean before starting.

## Files created

- `src/docintel/extract/__init__.py` — package docstring only.
- `src/docintel/extract/pdf.py` — `read_pages(path)`, `read_meta(path)`, using `pdfplumber`.
  Word boxes mapped directly from `extract_words()`'s `x0/top/x1/bottom` (already PDF points).
- `src/docintel/extract/ocr.py` — `ocr_pages(path, page_numbers)`, using
  `page.to_image(resolution=200).original` + `pytesseract.image_to_data`. Pixel boxes scaled by
  `72/200` into points; rows with blank text or `conf == -1` are dropped.
- `src/docintel/extract/normalize.py` — `NATIVE_CHAR_THRESHOLD = 50`, `load_document(path)`.
  Decides `native` vs `ocr` once per document from `total_chars / page_count`, never mixes within
  one document. Always reads `meta` from the text layer; OCR only replaces `pages`.
- `tests/extract/__init__.py` — empty (matches `tests/adapters/`'s convention; other `tests/*`
  subpackages have no `__init__.py`, so this was needed for consistency, not required by pytest).
- `tests/extract/test_normalize.py` — the brief's test file transcribed verbatim (13 tests).

## Files modified

- `src/docintel/pipeline/stages/s2_filter.py` — after the existing suffix/exists checks,
  `AttachmentFilter.run` now calls `load_document(ctx.source_path)` and sets `ctx.pages`,
  `ctx.page_meta`, `ctx.text_source`. Docstring extended to note this is where text is first read.
  No other stage touched.

## Verification — exact commands and real output

### 1. `python3 -m pytest tests/extract/ -v`
```
collected 13 items

tests/extract/test_normalize.py::test_native_documents_use_the_text_layer[...D.T.S.S...-1] PASSED
tests/extract/test_normalize.py::test_native_documents_use_the_text_layer[...Veritiv...-1] PASSED
tests/extract/test_normalize.py::test_native_documents_use_the_text_layer[...U- PAK...-5] PASSED
tests/extract/test_normalize.py::test_native_documents_use_the_text_layer[...Centracom...-10] PASSED
tests/extract/test_normalize.py::test_native_documents_use_the_text_layer[...Comcast...-6] PASSED
tests/extract/test_normalize.py::test_native_documents_use_the_text_layer[...EDCO...-1] PASSED
tests/extract/test_normalize.py::test_native_documents_use_the_text_layer[...Lumen...-6] PASSED
tests/extract/test_normalize.py::test_native_documents_use_the_text_layer[...Windstream...-4] PASSED
tests/extract/test_normalize.py::test_image_only_documents_route_to_ocr[...Complete Beverage...-4] PASSED
tests/extract/test_normalize.py::test_image_only_documents_route_to_ocr[...Federal Recycling...-1] PASSED
tests/extract/test_normalize.py::test_ocr_output_has_the_same_shape_as_native PASSED
tests/extract/test_normalize.py::test_edco_current_charges_survives_extraction PASSED
tests/extract/test_normalize.py::test_upak_total_is_on_the_last_page_not_the_first PASSED

13 passed in 8.96s
```

### 2. `python3 -m pytest -q` (whole suite)
```
........................................................................ [ 33%]
........................................................................ [ 66%]
........................................................................ [ 99%]
..                                                                       [100%]
218 passed in 210.53s (0:03:30)
```
205 (baseline) + 13 new = 218. Green.

### 3. `python3 -m mypy src/docintel/core --strict`
```
Success: no issues found in 7 source files
```

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

### 6. `python3 -m docintel.cli process docs`
```
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
Exit code: `0`. All 10 documents still emit — none newly dead-lettered by the OCR path.

### 7. `python3 -m docintel.cli replay-gold`
```
FAIL  digitaldirection-centracom-0384043574  (2/25)
FAIL  digitaldirection-comcast-8495444620365242  (2/25)
FAIL  digitaldirection-lumen-5-QXH7QKM7  (2/24)
FAIL  digitaldirection-windstream-041069076  (2/24)
FAIL  northstar-complete-beverage-32930  (3/19)
FAIL  northstar-dtss-6060  (3/16)
FAIL  northstar-edco-077087  (3/19)
FAIL  northstar-federal-recycling-1330123  (3/17)
FAIL  northstar-upak-4378107  (6/20)
FAIL  northstar-veritiv-715-33905296  (3/24)

0/10 documents green
```
Exit code 1 (as expected — no selectors exist yet, so document-level green is unreachable this
task).

**Before/after, measured directly** — stashed the C1a changes, re-ran `replay-gold --json`
against the untouched baseline (`ctx.text_source` stuck at its dataclass default `"native"`,
`ctx.pages`/`ctx.page_meta` empty), then popped the stash and re-ran:

| | documents green | assertions passed / total | `text_source` per doc |
|---|---|---|---|
| **Before** (baseline, stashed) | 0/10 | 27/213 | 8/10 pass by coincidence (default is `"native"`); `northstar-complete-beverage-32930` and `northstar-federal-recycling-1330123` fail (`actual: "native"`, expected `"ocr"`) |
| **After** (this task) | 0/10 | 29/213 | **10/10 pass** — the two OCR documents now correctly report `"ocr"` |

Read honestly: document-level green is unchanged at 0/10 (expected — no `fields.*` selectors
exist yet, exactly per the exit criterion), and the net assertion gain is small (+2) because 8 of
10 `text_source` checks already passed by coincidence against the unpopulated default. The
substantive result is qualitative, not the delta count: `ctx.pages`/`ctx.page_meta` are now
populated with real, correctly-sourced content for all 10 documents (previously empty tuples),
which is what makes the ~136 `fields.*` assertions *reachable* for the next cluster — they were
not counted as failing assertions before or after this task because no selector exists yet to
produce a value for the scorecard to compare.

### 8. Same-shape proof (native vs OCR)
```
native  pages=1 words_p1=84 lines_p1=21
        first word 'D.T.S.S.,' at (39.0,39.4)-(83.4,51.4)
        page box 612x792 pts
ocr     pages=1 words_p1=261 lines_p1=49
        first word 'RECYCLING' at (112.0,50.8)-(256.3,67.7)
        page box 609x791 pts
```
Both `type(native[0]) is type(ocr[0])` (`PageText` in both cases) and both page boxes land at
~612x792 points (US Letter) — the OCR path's `page.width`/`page.height` come from pdfplumber's
point-space page object, not the rendered pixel image, so no pixel-to-point scaling bug is
possible on the box dimensions themselves. The 261-word OCR count on Federal Recycling matches
the environment-verification figure given in the brief exactly.

## Deviations from the brief

None in implementation. One factual correction: the brief states the base commit is `40be4e2`;
`git rev-parse --short HEAD` at task start reported `f18e80e` instead, on a clean `feat/pipeline`
working tree with no uncommitted changes — i.e., the branch had already advanced past `40be4e2`
by prior tasks. Proceeded from the actual `HEAD` since that's what "base commit" operationally
means; flagging per the brief's own transparency requirement rather than silently absorbing the
discrepancy.

## Things worth flagging (not blocking)

- `ocr.py`'s per-page loop OCRs every page in `page_numbers` unconditionally with no page-count
  cap; on the corpus this is 5 pages total (1-2s/page, matches the brief's performance note), but
  a pathological huge scanned PDF routed here would OCR every page serially. Left as-is because
  the brief scoped no batching/parallelism requirement and `load_document` already guarantees
  OCR runs at most once per document per pipeline run.
- `pdf.read_meta` and `pdf.read_pages` each open the PDF with `pdfplumber` independently (so
  `load_document` opens the file twice on the native path: once for meta, once for pages). This
  mirrors the brief's two-function interface (`read_pages`/`read_meta` as separate top-level
  functions) rather than a fused single-open call; correct per the specified interface, just
  noting the minor double I/O cost since nothing in the brief asked for a single-open fast path.

## Summary

- 13 new tests, all passing; 218/218 total suite green (up from 205)
- mypy strict clean on `core/`, ruff clean on `src`/`tests`
- gold validator: 95/95
- CLI process: 10/10 emit, exit 0
- replay-gold: 0/10 documents green (expected — no selectors yet), 29/213 assertions passed,
  **`text_source` assertion green on all 10 documents** — the exit criterion this task was scoped
  to satisfy
- OCR/native shape parity proven: identical `PageText` type, matching ~612x792pt page boxes,
  scaled word coordinates in points on both paths

## Fix round 1: repeat-run cost — disk OCR cache, then the real hotspot (in-process memo)

**Commit SHA:** (see bottom of this section)

### What happened, in order

The coordinator's first message reported the full suite going from 0.16s (pre-C1a) to 120s+ and
attributed it to OCR itself, asking for a persistent disk-backed OCR cache keyed on path/size/
mtime_ns/resolution/tesseract-version, JSON-serialized, with a `DOCINTEL_OCR_CACHE=0` escape
hatch and graceful fallback on a corrupt entry. That was implemented first (`ocr_cache.py` +
`ocr.py` wired to it) exactly as specified — nothing in `pdf.py`, `normalize.py`'s decision rule,
or `s2_filter.py` changed.

A follow-up correction retracted the diagnosis: the "one page didn't finish in 110s" measurement
had been taken while a 210s `pytest` run was fighting it for CPU, so it wasn't a valid number.
The real, uncontended figures the coordinator supplied: `load_document` on the 1-page OCR
document is 0.89s, `replay-gold` over all 10 documents (5 OCR pages) is 7.68s — both already
fine. The actual hotspot is `tests/test_invariant.py`: 48 tests, each re-processing the same
10-document corpus via fault injection at every stage position, which — because `s2_filter` now
calls `load_document` — means 400+ repeat *native-text-layer* parses of the same 6-page
`docs/Lumen - 5-QXH7QKM7.pdf` inside one process, dwarfing the actual OCR cost. The disk cache
built in step one does not help here: it only skips re-running *tesseract*, and this hotspot is
pdfplumber re-parsing text-layer PDFs it already parsed a moment ago in the same process.

**Fix:** an in-process memo on `load_document` itself, keyed on
`(abspath, st_size, st_mtime_ns)`, via `functools.lru_cache(maxsize=64)`. Implementation lives in
`src/docintel/extract/normalize.py`:
- `load_document(path)` computes the key (skipping the memo entirely, and falling through to a
  real, unmemoized load, if the file can't be `stat`'d) and delegates to `_load_document_cached`.
- `_load_document_cached(key)` is the `lru_cache`-wrapped function; it re-derives `path` from
  `key[0]` and calls `_load_document_uncached`, which is the original (unmodified) decision logic
  — the `NATIVE_CHAR_THRESHOLD` comparison and OCR-routing branch were not touched.
- Safety reasoning documented in a docstring on `_load_document_cached`: `PageText`, `Word`, and
  `PageMeta` are frozen dataclasses and `pages`/`meta` are tuples, so the cached tuple is
  structurally immutable — safe to hand to arbitrarily many callers without copying.
- Bounded at `maxsize=64` so a long-running process over many documents can't grow the memo
  without limit.

The disk-backed OCR cache from step one was kept as-is (it still earns its place across separate
process invocations — `pytest`, `replay-gold`, and `validate_gold` are three different processes
that would otherwise each cold-OCR the 5 image pages).

### New test: `tests/extract/test_normalize_memo.py` (3 tests)

Per the coordinator's spec: load a document, copy it to a new temp path with different content
and assert no collision; and assert touching mtime forces a re-parse rather than a stale hit.
Implemented against `_load_document_cached.cache_info()` (hits/misses) so the tests assert on
memoization behavior directly, not just on output equality:
- `test_different_files_do_not_collide_in_the_memo` — two different real corpus PDFs copied to
  two temp paths; their `PageText` and word content differ.
- `test_repeated_calls_are_a_cache_hit_not_a_reparse` — first call is a miss, second call for the
  same untouched file is a hit with `misses` unchanged, and both calls return equal results.
- `test_touching_mtime_forces_a_reparse_not_a_stale_hit` — `os.utime` bumps mtime forward 5s,
  next call increments `misses` by exactly 1 (a real re-parse happened, not a cache hit on stale
  content).

### Verification — exact commands and real output

`python3 -m pytest tests/extract/ -v` — 18 passed in 4.20s (13 from the original C1a submission +
2 `test_ocr_cache.py` + 3 `test_normalize_memo.py`).

`python3 -m pytest -q` (warm, everything cached):
```
........................................................................ [ 32%]
........................................................................ [ 64%]
........................................................................ [ 96%]
.......                                                                  [100%]
223 passed in 4.15s
```
(218 + 5 new = 223.) **Down from 210.49s to 4.15s.**

`python3 -m pytest tests/test_invariant.py -q` (warm) — the reported hotspot:
```
................................................                         [100%]
48 passed in 3.70s
```
**Down from >120s (did not complete in the coordinator's timeout) to 3.70s.**

`python3 -m mypy src/docintel/core --strict` → `Success: no issues found in 7 source files`

`python3 docs/corpus/validate_gold.py` → `checks run: 95, failures: 0`

`ruff check src tests` → `All checks passed!`

`python3 -m docintel.cli replay-gold`, disk OCR cache **cold** (`rm -rf var/ocr-cache` first):
```
0/10 documents green
python3 -m docintel.cli replay-gold  7.22s user 0.19s system 98% cpu 7.540 total
```
Same command **warm** (cache populated by the cold run above, fresh process each time so this
isolates the disk cache, not the in-process memo):
```
0/10 documents green
python3 -m docintel.cli replay-gold  3.55s user 0.13s system 96% cpu 3.795 total
```
Assertions unchanged from the original C1a submission (29/213 passed, `text_source` green on all
10 documents) — this round changed performance only, not behavior.

`load_document` on the 4-page OCR document (`_AP Invoice 32930 Complete Beverage Destruction`),
each measured in a fresh `python3 -c` process so only the disk cache (not the in-process memo) is
in play:
- **Cold** (`rm -rf var/ocr-cache` first): `3.09s user 0.15s system → 3.351 total`
- **Warm**: `0.22s user 0.06s system → 0.373 total`

Cache-transparency test (`tests/extract/test_ocr_cache.py`) run standalone:
```
tests/extract/test_ocr_cache.py::test_cached_result_matches_what_ocr_pages_returned PASSED
tests/extract/test_ocr_cache.py::test_repeated_calls_return_the_same_pages PASSED
2 passed in 1.08s
```

`git status --short var/` → empty output (confirmed `var/` stays untracked; `.gitignore` already
had `var/` from before this task).

### Honest cold-start note

A completely fresh clone (empty `var/ocr-cache/`, cold in-process memo, i.e. the very first
`pytest -q` after `git clone`) pays for OCR once: 5 pages at ~1-2s/page plus tesseract/model
overhead, on the order of a few seconds total — not the "many minutes" threshold the coordinator
asked me to flag. Committed OCR fixtures are **not** needed on the evidence gathered here. The
number that actually mattered (>120s) was never OCR cost; it was 400+ redundant *native* PDF
re-parses in one process, which the in-process memo eliminates independent of any fixture
question.

### Files changed this round

- `src/docintel/extract/ocr_cache.py` — new. Disk-backed OCR cache (path/size/mtime_ns/
  resolution/tesseract-version key, JSON entries, atomic write, `DOCINTEL_OCR_CACHE=0` bypass,
  any read failure treated as a miss).
- `src/docintel/extract/ocr.py` — `ocr_pages` now checks `ocr_cache` first and saves on a miss;
  OCR logic itself moved into `_run_ocr` unchanged. Added `tesseract_version()` helper.
- `src/docintel/extract/normalize.py` — added the `functools.lru_cache`-based memo
  (`_memo_key`, `_load_document_cached`, `_load_document_uncached`); `load_document`'s public
  signature and the OCR-routing decision logic are unchanged.
- `tests/extract/test_ocr_cache.py` — new, 2 tests.
- `tests/extract/test_normalize_memo.py` — new, 3 tests.

### Deviations

None from either round of instructions. One addition beyond the disk cache's literal 5-component
key spec: `ocr_cache.cache_key` also folds in the sorted `page_numbers` tuple requested, so a
cache entry can never be served for a page range narrower than what's being asked for. The only
current caller (`normalize.load_document`) always requests every page, so this doesn't change
behavior today; it only removes a latent trap if a future caller ever requests a subset.

### Concerns for the coordinator

- The in-process memo is process-lifetime only (by design — `lru_cache` doesn't persist). Every
  separate `pytest`/`replay-gold`/`validate_gold` invocation still pays the disk-OCR-cache cost
  (a few seconds, not zero) plus a full native re-parse of all 8 text-layer documents each time,
  since there's no cross-process cache for `pdf.read_meta`/`pdf.read_pages`. That's why cold and
  warm `replay-gold` differ by ~3.7s rather than converging to near-zero — the remaining time is
  legitimate native-PDF parsing work, not cache misses. Flagging in case sub-4s becomes a target
  for `replay-gold` specifically; nothing in either instruction round asked for that.

## Fix round 2: content-hash the cache keys, fix a dead bypass, cap disk growth

**Commit SHA:** (see bottom of this section)

A review of round 1 found one critical correctness hole and three smaller issues. All four are
fixed below.

### Finding 1 (critical) — memo/disk-cache keys were forgeable by a same-size, same-mtime overwrite

**The hole.** `(abspath, st_size, st_mtime_ns)` is not a content key. A file overwritten in place
at the same path, padded/rewritten to the identical byte size, with its mtime explicitly restored
— exactly what `rsync -t`, `cp --preserve=timestamps`, and timestamp-preserving archive extraction
do — collides on all three fields and serves the *previous* file's parsed content for the new
bytes on disk.

**Reproduced against the pre-fix code before touching anything**, per instruction. Script: write
the larger corpus PDF (Veritiv, 248,788 bytes) to a temp path, `load_document` it, then overwrite
that same path in place with the smaller corpus PDF's real bytes (D.T.S.S., 64,658 bytes) padded
with trailing null bytes out to Veritiv's exact original size (trailing bytes after a PDF's
`%%EOF` are inert — verified separately that pdfplumber/pypdfium2 parse straight through them),
restore the exact original `st_mtime_ns`, and load again:
```
Traceback (most recent call last):
  File "<string>", line 38, in <module>
AssertionError: BUG REPRODUCED: stale content served
first word: FSC
size/mtime preserved: 248788 1785146466077854816
second word (should be D.T.S.S., if correct): FSC
pages1 is pages2: True
```
`pages1 is pages2: True` — the second call returned the exact same cached object, i.e. Veritiv's
parse, for a file that now physically contains D.T.S.S.'s content. Confirmed exactly as the
coordinator described.

**Fix.** Added `ocr_cache.content_hash(path)` — `hashlib.blake2b(data, digest_size=16).hexdigest()`
over the full file — and folded it into both keys:
- `normalize._memo_key` now returns `(abspath, st_size, st_mtime_ns, content_hash)`.
- `ocr_cache.cache_key` now includes the same content hash alongside path/size/mtime/resolution/
  tesseract-version/page-numbers.

`st_size` and `st_mtime_ns` were kept in both keys per instruction — free, and make a cache
filename self-documenting — but the hash is what actually makes either key correct.

**Cost, measured by the coordinator before asking, confirmed by the resulting suite time:**
hashing the whole 10-document corpus (~7MB) is single-digit milliseconds; 400 hashes of the 0.61MB
Lumen PDF (what the invariant matrix does) is ~0.16s. Full suite went from 4.15s (round 1, no
hash) to ~5.0s warm (round 2, with hash) — see Verification below.

### Finding 2 (important) — `DOCINTEL_OCR_CACHE=0` didn't bypass the in-process memo

**The hole.** The env var gated `ocr_cache.load`/`save` (the disk layer) but `normalize.
load_document` consulted `_load_document_cached` (the in-process `lru_cache`) unconditionally. A
second `load_document` call for the same file in one process returned the memoized tuple without
ever reaching `ocr.ocr_pages`, so the "force a real OCR run" escape hatch silently did nothing for
repeat calls — worse than no escape hatch, because it looks like it works.

**Fix.** `load_document` now checks `ocr_cache.enabled()` first and calls `_load_document_uncached`
directly (skipping the memo entirely) when `DOCINTEL_OCR_CACHE=0`. Documented in both modules'
docstrings — `normalize.py`'s top docstring now states explicitly that the env var clears *both*
layers, and why a partial bypass would be worse than none.

### Finding 3 (important) — unbounded disk cache growth

**Fix.** `ocr_cache.save` now calls `_evict_oldest_past_cap` after every successful write:
list `var/ocr-cache/*.json`, sort by `st_mtime`, and unlink the oldest entries past `MAX_ENTRIES =
512`. Wrapped so a listing or unlink failure is swallowed (`except OSError: pass` at both the
per-file and whole-function level) — eviction is best-effort and must never break the OCR run that
triggered it.

**Smoke-tested directly** (not part of the corpus test suite, run by hand): backed up the 5 real
cache entries, created 520 synthetic entries with staggered mtimes, called
`_evict_oldest_past_cap()`, and confirmed the directory was pruned to exactly 512, oldest-first:
```
existing entries before smoke test: 5
created: 520
after eviction: 512
oldest remaining: fake0008.json newest remaining: fake0519.json
restored entries: 5
```

### Finding 4 (minor) — disk-cache test couldn't distinguish a hit from a recompute

`test_repeated_calls_return_the_same_pages` asserted only that two `ocr_pages` calls returned
equal results — true even with the cache disabled, since real OCR is deterministic. Replaced with
`test_second_call_is_served_from_the_disk_cache_not_a_recompute` in
`tests/extract/test_ocr_cache.py`: runs real OCR once on a private tmp-path copy (populating the
cache), then `monkeypatch`es `ocr.pytesseract.image_to_data` to raise `AssertionError` on any
further call, then calls `ocr_pages` again and asserts it still succeeds and matches the first
result. This can only pass if the second call is actually served from disk.

### Finding 5 (minor) — collision test was structurally unable to fail

`test_different_files_do_not_collide_in_the_memo` compared two different absolute paths, which
guarantees different keys regardless of any hashing logic — it could never have caught Finding 1.
Replaced with `test_overwriting_the_file_in_place_is_detected_even_with_same_size_and_mtime` in
`tests/extract/test_normalize_memo.py`, built from the exact reproduction script above (same-path
overwrite, same size via null-byte padding, restored `st_mtime_ns`). Confirmed failing on pre-fix
code (output above) and passing on the fixed code (see Verification).

### Verification — exact commands and real output

**Reproduction test, pre-fix → post-fix.** Pre-fix failure is the standalone script output shown
under Finding 1 above (captured before any fix-round-2 code was written, per instruction). Post-fix,
the same scenario as a pytest test:
```
tests/extract/test_normalize_memo.py::test_overwriting_the_file_in_place_is_detected_even_with_same_size_and_mtime PASSED
```

`python3 -m pytest tests/extract/ -v` (18 tests: 13 original + 2 `test_ocr_cache.py` + 3
`test_normalize_memo.py`):
```
tests/extract/test_normalize.py::test_native_documents_use_the_text_layer[...] PASSED  (x8)
tests/extract/test_normalize.py::test_image_only_documents_route_to_ocr[...] PASSED    (x2)
tests/extract/test_normalize.py::test_ocr_output_has_the_same_shape_as_native PASSED
tests/extract/test_normalize.py::test_edco_current_charges_survives_extraction PASSED
tests/extract/test_normalize.py::test_upak_total_is_on_the_last_page_not_the_first PASSED
tests/extract/test_normalize_memo.py::test_overwriting_the_file_in_place_is_detected_even_with_same_size_and_mtime PASSED
tests/extract/test_normalize_memo.py::test_repeated_calls_are_a_cache_hit_not_a_reparse PASSED
tests/extract/test_normalize_memo.py::test_touching_mtime_forces_a_reparse_not_a_stale_hit PASSED
tests/extract/test_ocr_cache.py::test_cached_result_matches_what_ocr_pages_returned PASSED
tests/extract/test_ocr_cache.py::test_second_call_is_served_from_the_disk_cache_not_a_recompute PASSED

18 passed in 8.48s
```

`python3 -m pytest -q` (warm — same 223 tests as round 1, no count change; this round is
correctness + a fixed cost, not new tests beyond replacing 2):
```
........................................................................ [ 32%]
........................................................................ [ 64%]
........................................................................ [ 96%]
.......                                                                  [100%]
223 passed in 5.04s
```
Wall clock (`time`, second run to rule out first-run noise): `6.18s user 0.33s system 90% cpu
7.191 total`. Landed close to the coordinator's ~4.5s estimate; the gap versus round 1's 4.15s is
the content-hashing cost the coordinator pre-measured and approved (~0.16s on the invariant matrix
alone, plus hashing overhead spread across the rest of the suite's repeat `load_document`/
`ocr_pages` calls).

`python3 -m mypy src/docintel/core --strict` → `Success: no issues found in 7 source files`

`python3 docs/corpus/validate_gold.py` → `checks run: 95, failures: 0`

`ruff check src tests` → `All checks passed!`

`python3 -m docintel.cli replay-gold`:
```
0/10 documents green
```
`--json` summary: `{'total': 10, 'passed': 0, 'failed': 10, 'assertions_passed': 29,
'assertions_total': 213}` — **unchanged from round 1**, confirming this round is behavior-neutral.

**`DOCINTEL_OCR_CACHE=0` bypasses both layers** — repeat `load_document` call, same process, disk
cache and memo both off:
```
first call:  0.85s  source=ocr
second call: 0.83s  source=ocr
both calls took real OCR time (bypass working): True
pages1 is pages2: False
```
Both calls pay full OCR cost (~0.85s each, matching the un-cached per-page figure from round 1)
and return distinct objects (`pages1 is pages2: False`) — the memo genuinely did not serve the
second call, proving the bypass now covers both layers as Finding 2 required.

**Trap values still reachable, shape still correct:**
```
EDCO CURRENT CHARGES in text: True
EDCO 69.62 in text: True
Federal source: ocr
Federal 1330123 in text: True
Federal 481.20 in text: True
Federal page box: 609x791 pts
```

`git status --short var/` → empty output; `var/ocr-cache/` held exactly its 5 real corpus entries
after the eviction smoke test restored them.

### Files changed this round

- `src/docintel/extract/ocr_cache.py` — added `content_hash()`, folded it into `cache_key()`;
  added `MAX_ENTRIES = 512` and `_evict_oldest_past_cap()`, called from `save()`.
- `src/docintel/extract/normalize.py` — `_memo_key` now includes `ocr_cache.content_hash(path)`;
  `load_document` checks `ocr_cache.enabled()` before consulting the memo at all; docstrings
  updated to explain both.
- `tests/extract/test_normalize_memo.py` — `test_different_files_do_not_collide_in_the_memo`
  (Finding 5, couldn't fail) replaced with
  `test_overwriting_the_file_in_place_is_detected_even_with_same_size_and_mtime`.
- `tests/extract/test_ocr_cache.py` — `test_repeated_calls_return_the_same_pages` (Finding 4, no
  hit/miss instrumentation) replaced with
  `test_second_call_is_served_from_the_disk_cache_not_a_recompute`.

### Deviations

None. `RESOLUTION` untouched, invariant matrix untouched, no existing assertion weakened.

### Concerns for the coordinator

- None new. The round-1 concern about cross-process cost (separate `pytest`/`replay-gold`
  invocations each re-hashing and re-parsing native documents) still applies and is now very
  slightly larger, since every memo/disk-cache lookup also re-hashes the file's full content on
  every call, cold or warm, in-process or not. Still low single-digit seconds end to end; flagging
  only because "hash the whole file on every lookup" is a cost that scales with corpus size and
  would be worth revisiting (e.g. a faster non-cryptographic hash, or hashing only if size/mtime
  already match) if the corpus grows by orders of magnitude.
