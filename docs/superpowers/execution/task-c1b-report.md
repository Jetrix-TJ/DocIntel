# Task C1b Report: page-level detectors — pageroles, annotations, scanline

**Status:** DONE

**Scope:** Cluster C1b only. `src/docintel/extract/{pageroles,annotations,scanline}.py`, the
`s2_filter.py` wiring (page-role assignment + `has_flattened_annotations` tag), the
`scorecard.py` `page_roles` assertion, and their tests under `tests/extract/`.
`pdf.py`, `ocr.py`, `normalize.py` (C1a), everything under `src/docintel/core/`, and every stage
other than `s2_filter.py` were not touched.

**Base commit:** `04d0adf` (branch `feat/pipeline`), confirmed via `git rev-parse --short HEAD`
at the start of the task, matching the brief.

## Files created

- `src/docintel/extract/pageroles.py` — `assign(pages, meta) -> tuple[PageMeta, ...]` (F10).
- `src/docintel/extract/annotations.py` — `detect_flattened(path, pages, meta) -> bool` (F3).
- `src/docintel/extract/scanline.py` — `find(pages) -> str | None`, `corroborates(scanline,
  value) -> bool` (F7).
- `tests/extract/test_pageroles.py`, `tests/extract/test_annotations.py`,
  `tests/extract/test_scanline.py`.

## Files modified

- `src/docintel/pipeline/stages/s2_filter.py` — after `load_document`, `ctx.page_meta` is now
  `pageroles.assign(pages, page_meta)` (replacing the tuple, never mutating it), and
  `annotations.detect_flattened(...)` sets the `has_flattened_annotations` tag via
  `ctx.add_tag`. Wiring that tag into confidence/review (s6/s7) is out of scope — `s7_gate.py`
  has no notion of tags yet; that is presumably a later cluster (confidence.py already defines
  the `flattened_annotations` modifier, unused so far).
- `src/docintel/scorecard.py` — added a `page_roles` assertion (`kind="exact"`) comparing gold
  `classification.page_roles` against the record's `page_roles`.
- `src/docintel/extract/__init__.py` — one line added (see "Deviation / gotcha" below); nothing
  else changed.

## Design notes: how each detector's rule was derived

The brief said "design to them" for page roles and gave verified digit examples for the
scanline; it did not give exact algorithms for any of the three. All three were reverse-engineered
directly from the ten real PDFs and validated against gold before being written up here.

**Page roles (F10).** A page is `primary` if it carries, on a *short* visual line (≤12 words —
long enough for a bundled table-header row like U-PAK's "AGE CURRENT 30 DAYS 60 DAYS 90 DAYS
Please Pay", short enough to exclude prose), both a document-identity anchor label ("Invoice
Number", "Account No.", etc.) and a totals label ("Total Amount Due", "Please Pay", "Balance
Due", "Current Charges", etc.). Naive substring search over the whole page fails: Lumen page 2's
FAQ prose contains "...the amount due to the Federal Universal Service Fund..." and would false-
positive; restricting to short lines fixes that. Rule: page 1 is always `primary`; every other
page is `primary` too only if *every* page in the document independently carries both signals
(U-PAK's repeating-template case — F9's blank "Please Pay" cell on early pages still counts, since
only the label is required, not a resolved value); otherwise every page after the first is
`supporting`. Verified against all ten gold `page_roles` lists exactly (parametrized test).

**Flattened annotations (F3).** Two pixel signals on the rendered page (100 dpi), both required:
(1) at least 3% of the page falls in a moderate-saturation, high-value HSV band (40≤S≤170,
V≥140) — the "pastel wash" a highlighter or comment-box fill leaves, as opposed to a fully
saturated print-shop logo colour; (2) that colour is spread across ≥50 cells of a 40×52
downsampled grid, ruling out a single large logo/masthead block. Both thresholds were picked by
measuring every page of all ten documents (39 pages) and choosing a cut with >2x margin either
side; see the module docstring for the actual numbers (Federal Recycling: 4.45% / 193 cells;
nearest false-candidate: Comcast page 5/6 at ~2.0% / EDCO at 114 cells — neither clears *both*
thresholds simultaneously on any page).

**Scanline (F7).** `find` looks for a visual line containing a pure-digit word (`str.isdigit()`,
no punctuation) of ≥18 characters, then returns every pure-digit word on that line joined with
spaces — not the single longest token, because Lumen's scan line is split into several digit
groups (`251001 000000752233001 00000000000586878247 8 2 00000024809 2`) and the digits that
corroborate its invoice total (`24809`) live in a shorter group, not the longest one. Returning
only the digit-words (not the whole line verbatim) also keeps incidental adjacent text out of the
result — Centracom's scan line shares a visual row with "Due Amount - Please Remit: $33,876.40"
purely by page-layout coincidence.

## Verification — exact commands and real output

### 1. `python3 -m pytest tests/extract/ -v`
50 passed (18 pre-existing `test_normalize`/`test_normalize_memo`/`test_ocr_cache` tests + 32
new: 4 `test_annotations.py`, 14 `test_pageroles.py` [10 gold-parametrized + 4 direct], 14
`test_scanline.py`).
```
tests/extract/test_annotations.py::test_federal_recycling_flattened_annotations_are_detected PASSED
tests/extract/test_annotations.py::test_clean_document_is_not_flagged PASSED
tests/extract/test_annotations.py::test_only_federal_recycling_is_flagged_across_the_whole_corpus PASSED
tests/extract/test_annotations.py::test_detection_is_memoized_and_does_not_mutate_shared_state PASSED
...
tests/extract/test_pageroles.py::test_assigned_roles_match_the_gold_label[digitaldirection-centracom-0384043574] PASSED
tests/extract/test_pageroles.py::test_assigned_roles_match_the_gold_label[digitaldirection-comcast-8495444620365242] PASSED
tests/extract/test_pageroles.py::test_assigned_roles_match_the_gold_label[digitaldirection-lumen-5-QXH7QKM7] PASSED
tests/extract/test_pageroles.py::test_assigned_roles_match_the_gold_label[digitaldirection-windstream-041069076] PASSED
tests/extract/test_pageroles.py::test_assigned_roles_match_the_gold_label[northstar-complete-beverage-32930] PASSED
tests/extract/test_pageroles.py::test_assigned_roles_match_the_gold_label[northstar-dtss-6060] PASSED
tests/extract/test_pageroles.py::test_assigned_roles_match_the_gold_label[northstar-edco-077087] PASSED
tests/extract/test_pageroles.py::test_assigned_roles_match_the_gold_label[northstar-federal-recycling-1330123] PASSED
tests/extract/test_pageroles.py::test_assigned_roles_match_the_gold_label[northstar-upak-4378107] PASSED
tests/extract/test_pageroles.py::test_assigned_roles_match_the_gold_label[northstar-veritiv-715-33905296] PASSED
tests/extract/test_pageroles.py::test_upak_is_primary_on_every_page PASSED
tests/extract/test_pageroles.py::test_complete_beverage_bol_pages_are_supporting_not_primary PASSED
tests/extract/test_pageroles.py::test_assign_does_not_mutate_or_corrupt_the_memoized_meta PASSED
tests/extract/test_pageroles.py::test_assign_on_empty_pages_returns_meta_unchanged PASSED
tests/extract/test_scanline.py::test_scanline_encodes_the_printed_total[...] PASSED (x5)
tests/extract/test_scanline.py::test_documents_without_a_scanline_return_none PASSED
tests/extract/test_scanline.py::test_the_five_documents_without_a_scanline_all_return_none[...] PASSED (x5)
tests/extract/test_scanline.py::test_centracom_scanline_corroborates_the_printed_total_not_the_payable_amount PASSED
tests/extract/test_scanline.py::test_corroborates_strips_punctuation_from_a_decimal_value PASSED
tests/extract/test_scanline.py::test_corroborates_rejects_degenerate_short_values PASSED

======================== 50 passed, 1 warning in 5.39s =========================
```
(The one warning is a Pillow `Image.getdata` deprecation notice, scheduled for removal in
Pillow 14 (2027-10-15); intentionally not switched to `get_flattened_data()` because that method
doesn't exist on the project's declared floor, `Pillow>=10.0` — see the code comment.)

### 2. `python3 -m pytest -q`
```
255 passed, 1 warning in 6.23s
```
223 baseline + 32 new tests (the three new `tests/extract` files above) = 255, wall clock 6.23s,
within the "stay near 5-6s" target. This
number is only reachable because `annotations.detect_flattened` is memoized (see "Deviation" #2
below) — without that memo, `tests/test_invariant.py`'s fault-injection matrix alone (which
reprocesses one document across ~40+ pipeline configurations) would re-render that document's
pages on every single call.

### 3. `python3 -m mypy src/docintel/core --strict`
```
Success: no issues found in 7 source files
```
(Unaffected by this task — `extract/` is outside mypy's configured `files` in `pyproject.toml`.)

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

### 6. `python3 -m docintel.cli replay-gold` — full output
```
FAIL  digitaldirection-centracom-0384043574  (3/26)
FAIL  digitaldirection-comcast-8495444620365242  (3/26)
FAIL  digitaldirection-lumen-5-QXH7QKM7  (3/25)
FAIL  digitaldirection-windstream-041069076  (3/25)
FAIL  northstar-complete-beverage-32930  (4/20)
FAIL  northstar-dtss-6060  (4/17)
FAIL  northstar-edco-077087  (4/20)
FAIL  northstar-federal-recycling-1330123  (4/18)
FAIL  northstar-upak-4378107  (7/21)
FAIL  northstar-veritiv-715-33905296  (4/25)

0/10 documents green
```
**Scorecard: before 0/10 documents green, 29/213 assertions — after 0/10 documents green,
39/223 assertions.** Documents-green is unchanged (expected: the brief's exit criterion is that
`fields.*` assertions become *reachable*, not that they pass — extraction doesn't exist yet).
The +10/+10 delta is exactly the ten new `page_roles` assertions, one per gold document, and all
ten pass (confirmed by inspecting `replay_gold()`'s per-assertion output directly). This is an
**instrument** change, not a behaviour change: `page_roles` was already computed and emitted on
every record (`contract.py` already had `"page_roles": [m.role for m in ctx.page_meta]`); the
scorecard simply wasn't asserting on it before.

### 7. Per-document detector evidence
```
CANADIAN WITHOUT NOTES U- PAK 4378107    native  roles=['primary', 'primary', 'primary', 'primary', 'primary'] ann=False scanline=-
CONTRA ONLY Everything already on AR F   ocr     roles=['primary'] ann=True scanline=-
Centracom_0384043574_01012026_BILL.pdf   native  roles=['primary', 'supporting', 'supporting', 'supporting', 'supporting', 'supporting', 'supporting', 'supporting', 'supporting', 'supporting'] ann=False scanline=03840384043574000033876408
Comcast_8495 44 462 0365242_12092025_B   native  roles=['primary', 'supporting', 'supporting', 'supporting', 'supporting', 'supporting'] ann=False scanline=849544462036524200221119
EDCO 77087APR25 current charges can be   native  roles=['primary'] ann=False scanline=25600770871000367962
Lumen - 5-QXH7QKM7.pdf                   native  roles=['primary', 'supporting', 'supporting', 'supporting', 'supporting', 'supporting'] ann=False scanline=251001 000000752233001 000
Windstream_041069076_07222025_BILL.pdf   native  roles=['primary', 'supporting', 'supporting', 'supporting'] ann=False scanline=70004440000000041069076225
_AP Invoice 32930 Complete Beverage De   ocr     roles=['primary', 'supporting', 'supporting', 'supporting'] ann=False scanline=-
_AP Invoice 6060DTSS        D.T.S.S. I   native  roles=['primary'] ann=False scanline=-
_AP Invoice 715-33905296    Veritiv Op   native  roles=['primary'] ann=False scanline=-
```
Matches gold `page_roles` exactly on all ten; `has_flattened_annotations` fires on exactly
Federal Recycling; scan line present (and matching the required digit substrings) on exactly the
five documents the brief names, `None` on the other five.

### 8. Memo non-corruption check
```
roles in cached meta unchanged: True
```
Confirms the precondition: calling `pageroles.assign` does not corrupt what a later
`load_document` call for the same file returns from its memo.

## Deviations, and why

1. **`src/docintel/extract/__init__.py` — one line added.** Not listed in the brief's file list,
   but necessary for the brief's own verification script (§7 above, `from docintel.extract import
   pageroles, annotations, scanline`) to work at all. Root cause: `__init__.py` already has
   `from __future__ import annotations` at module scope, which — as an unavoidable side effect of
   Python's import semantics — binds the *package's own* `annotations` attribute to a
   `__future__._Feature` object. `from docintel.extract import annotations` (or bare
   `docintel.extract.annotations`) then resolves via `getattr` to that pre-existing attribute and
   *never triggers the submodule import*, silently returning the wrong object
   (`AttributeError: '_Feature' object has no attribute 'detect_flattened'` at the call site,
   deep inside `s2_filter.py` and inside the brief's own verification snippet). This is a Python
   gotcha specific to naming a submodule `annotations.py` inside any package that also does
   `from __future__ import annotations` in `__init__.py` — it would have bitten regardless of how
   `annotations.py`'s own contents were written. Fixed with a single explicit dotted import
   (`import docintel.extract.annotations as annotations  # noqa: E402,F401`) after the future
   import, which unconditionally rebinds the package attribute to the real submodule (dotted
   `import a.b.c` always overwrites the parent's attribute after loading `c`, unlike
   `from a.b import c`, which only reads it). Verified no circular-import issue: `annotations.py`
   imports `ocr_cache` from the same package, and that resolves fine even mid-init because
   `from package import name` falls back to a real submodule import when the attribute lookup
   fails, which is exactly what happens here since `ocr_cache` was never given the same "shadowed
   by `__init__.py`" treatment. This is documented at length in both `__init__.py` and
   `annotations.py`'s module docstrings so nobody "fixes" the import back to the broken form.
2. **`annotations.detect_flattened` is memoized in-process**, keyed identically to
   `normalize.load_document`'s memo (`(abspath, size, mtime, content_hash)`, honouring
   `DOCINTEL_OCR_CACHE=0`). Not explicitly requested by the interface spec, but required by the
   "stay near 5-6s" verification target: `tests/test_invariant.py`'s fault-injection matrix
   reprocesses the same document through `s2_filter` roughly 40+ times within one pytest process,
   and each call renders every page of that document to check for annotations — unmemoized, that
   alone would have added several seconds. This mirrors an existing, explained pattern in
   `normalize.py`, not a new one.
3. **`numpy`/`scipy` were deliberately avoided** in `annotations.py` even though both are
   importable in this environment — neither is a declared dependency in `pyproject.toml` (they're
   present transitively via unrelated packages, likely `pandas`/`scikit-learn`, not via
   `pdfplumber`/`Pillow`/`pytesseract`). Using them would have made the module depend on
   incidental environment state that a clean install per `pyproject.toml` would not have. The
   pixel/colour-band logic is implemented with `PIL.Image`/`ImageChops`/`point()` lookup tables
   only, which is fast (all C-level) and stays within the project's declared dependency floor.

## Things worth flagging (not gold-file edits — reported per instructions)

- **`s7_gate.py` does not yet look at `ctx.tags`.** `has_flattened_annotations` is set correctly
  by this task, and `confidence.py` already defines the `flattened_annotations` modifier
  (`Decimal("0.75")`), but nothing currently wires the tag to either the confidence modifier or
  to `review_flag`. The gold file for Federal Recycling expects `review_flag: true` unconditionally
  because of this tag (`expected_routing.reason`), so that assertion will keep failing until a
  later cluster (confidence/gating, likely C3 given the modifier is already defined) reads tags.
  This is explicitly out of C1b's scope per the brief ("Modify s2_filter.py to apply page roles
  and set the tag" — setting, not consuming) and is not something I changed, but it's worth
  surfacing so it isn't mistaken for a C1b bug later.
- **No issues found with any of the ten gold `page_roles` labels** — all ten were reproduced
  exactly by an independently-derived rule (built from layout signals, not by reading the labels
  and special-casing), which is reasonably strong evidence they're correct.

## Commit

`ac02966` on `feat/pipeline`, parent `04d0adf`. Commit message describes the three new
detectors, the `s2_filter.py`/`scorecard.py` wiring, and the `__init__.py` shadowing fix.
Working tree clean after commit (`git status --short` empty aside from the gitignored
`.superpowers/sdd/` report directory, which no prior task report in this series has tracked
either).

## Fix round 1

Coordinator review found the page-role rule was corpus-fitted rather than principled (Finding 1,
critical), the scanline field restriction was docstring-only and unenforced (Finding 2), the
annotation detector's saturation-only blind spot was undocumented and untested (Finding 3), and
a leftover Pillow deprecation warning (Finding 4). The review's diagnosis of the root cause —
"all 32 new tests run against the 10 real corpus documents and none uses a synthetic fixture...
structurally unable to detect corpus-overfit" — was correct, and the fix for Finding 1 required
tightening the underlying regexes, not just deleting the page-1 special case (see below).

### Finding 1: `pageroles.assign` rewritten to a per-page rule with an explicit, logged fallback

**Verified, not trusted, per the coordinator's instruction.** The coordinator's hypothesis —
"I believe this reproduces all 10 gold labels without any page-1 exception" — was directionally
right but not true of the *original* regex set: with the broad totals regex (`AMOUNT DUE`,
`CURRENT CHARGES` included), dropping the page-1/`every_page_primary` collapse alone made Lumen
page 3 and Windstream page 3 both false-positive to `primary` (Lumen page 3's aging-recap table
contains a bare "Amount Due 248.09" line; Windstream page 3 has a section header "Windstream
Current Charges"; both matched the old totals regex on a short line, and both also carry the
account-number anchor in their running header). The actual fix was narrowing `_TOTALS_RE` to the
six phrases that only ever appear on a genuine totals block in this corpus (`TOTAL AMOUNT DUE`,
`PLEASE PAY`, `BALANCE DUE`, `TOTAL DUE`, `GRAND TOTAL`, `TOTAL AMT` — dropping bare `AMOUNT DUE`
and `CURRENT CHARGES`), and giving the anchor regex its own, tighter line-length cap (8 words vs.
totals' 12) so EDCO's incidental "...have the last 6 digits of your account number ready..."
sentence (10 words) stops coincidentally counting as an identity anchor. With both regexes
tightened, the rule is now purely `primary = has_anchor(page) and has_totals(page)`, decided
per page, no page-index special case anywhere in the main rule.

Verified against real per-page signal output (not assumed) before writing the new tests. Result,
confirmed with the actual code:

| Document | How primary is decided |
|---|---|
| U-PAK (5pp) | Direct rule, all 5 pages independently qualify (identical template, `Please Pay` row present but blank until the last page — F9) |
| Federal Recycling, Comcast, Centracom, Lumen, Windstream, Veritiv | Direct rule, page 1 only qualifies |
| Complete Beverage Destruction | **Tier-1 fallback**: page 1 has a totals label ("Total Due" in a header row) but no machine-findable anchor label |
| DTSS | **Tier-1 fallback**: page 1 has "Balance Due" but no machine-findable anchor label |
| EDCO | **Tier-2 fallback**: page 1 has neither signal under the tightened regexes (its account number and total live in a scan-line code and a bare "Current Charges:" recap, neither of which qualifies) |

All 10 gold `page_roles` labels reproduced exactly — **no gold label required reintroducing a
special case**; report per the coordinator's stop-and-report instruction: none needed.

Also added, per Finding 1 points 2-3:
- A two-tier, logged fallback (`logging.getLogger("docintel.extract.pageroles").warning(...)`):
  first, the page carrying a totals label on its own; if none, page 1 unconditionally, "as a last
  resort" (exact phrase asserted in tests). Confirmed firing on exactly Complete Beverage/DTSS
  (tier 1) and EDCO (tier 2) — see the captured warnings in the verification output below.
- `"unknown"` is now reachable: a non-primary page with zero words (`len(page.words) == 0`) is
  `unknown` rather than `supporting`, since a blank page carries no information to classify
  either way. No document in the corpus has a blank page, so this is covered only by synthetic
  tests (`test_blank_page_is_unknown_not_supporting`,
  `test_blank_first_page_still_becomes_primary_via_last_resort_fallback` — the latter confirms
  the fallback takes priority over the blank-page default, i.e. a document of all-blank pages
  still gets exactly one `primary` page).
- `every_page_primary` is gone entirely — it was a symptom of the wrong rule, not a needed
  mechanism; U-PAK's all-primary result now falls out of the per-page rule with no collapse step.

Six new synthetic tests in `tests/extract/test_pageroles.py`, built from fabricated
`PageText`/`Word`/`PageMeta` objects (a `_page(number, lines)` / `_blank_page(number)` / `_meta(pages)`
helper trio), covering exactly the coordinator's required list:
`test_page_2_is_primary_when_the_anchor_and_totals_first_appear_there`,
`test_fallback_fires_when_no_page_carries_both_signals`,
`test_single_page_with_anchor_but_no_totals_is_still_primary`,
`test_page_with_neither_signal_in_a_multipage_document_is_supporting`,
`test_blank_page_is_unknown_not_supporting`,
`test_blank_first_page_still_becomes_primary_via_last_resort_fallback` — plus three new
corpus-based tests (`test_dtss_falls_back_to_the_page_with_a_totals_label`,
`test_edco_falls_back_to_page_1_as_a_last_resort`, and the updated
`test_complete_beverage_bol_pages_are_supporting_not_primary`) that assert on the captured log
message so the fallback path is exercised and named, not just its output.

### Finding 2: `scanline.corroborates` now takes a required `field` argument

Added `CORROBORATABLE_FIELDS: frozenset[str] = frozenset({"total_printed", "account_number",
"invoice_number", "due_date"})` and changed the signature to
`corroborates(scanline: str, value: object, field: str) -> bool`, raising `ValueError` naming the
offending field for anything outside that set. No existing callers (confirmed by grep — nothing
outside `scanline.py`/`test_scanline.py` references `corroborates`), so the signature change was
free, as the coordinator noted. Added `test_corroborates_accepts_exactly_the_four_grammar_fields`
and the required `test_corroborates_rejects_fields_outside_the_grammar_constraint`, parametrized
over `amount_payable` and `current_charges`, both asserting `pytest.raises(ValueError, match=field)`.

### Finding 3: greyscale blind spot documented and pinned

Added a "Known blind spot" paragraph to the module docstring stating plainly that detection is
entirely saturation-dependent and therefore cannot see a greyscale scan or black/grey-pen
annotation — the exact failure mode F3 cares about most (a contradicted value passing with no
forced review). Refactored `_page_is_annotated` to split out a pure-pixel `_image_is_annotated(img:
Image.Image) -> bool`, so the limitation could be pinned directly against a `PIL.Image` without
needing a synthetic PDF. The test (`test_greyscale_annotations_are_a_known_blind_spot_not_detected`)
takes Federal Recycling's own real annotated page — confirmed detected in colour first, as a
sanity check that the test pins something real — desaturates it (`.convert("L").convert("RGB")`,
same annotation geometry and coverage, saturation removed), and asserts detection now returns
`False`. The test's docstring states explicitly this is expected-but-undesired behaviour, not a
spec: if it ever starts failing (detection returns `True` on the greyscale version), that means
the blind spot has narrowed and the module docstring needs updating, not that the test is wrong.

### Finding 4: Pillow deprecation warning fixed

Swapped `grid.getdata()` for `grid.get_flattened_data()` in `_image_is_annotated` per the
coordinator's confirmation that the latter exists in the installed Pillow 12.1.1. The suite's one
warning is gone (see verification below). Note for whoever next touches this: `get_flattened_data`
is fairly recent and may not exist on `pyproject.toml`'s declared floor (`Pillow>=10.0`) — not
re-litigated here since the coordinator explicitly directed the swap, but worth knowing if this
project ever pins an older Pillow in CI.

### Verification — exact commands and real output

**1. `python3 -m pytest tests/extract/ -v`** — 62 passed (up from 50: +12 new tests — 8 in
`test_pageroles.py`, 3 in `test_scanline.py`, 1 in `test_annotations.py`), no warnings:
```
============================== 62 passed in 5.57s ==============================
```

**2. `python3 -m pytest -q`** — 267 passed (255 + 12), wall clock 6.32s, within the "stay near
6s" target:
```
267 passed in 6.32s
```

**3. `python3 -m mypy src/docintel/core --strict`**
```
Success: no issues found in 7 source files
```

**4. `python3 docs/corpus/validate_gold.py`**
```
gold documents : 10
checks run     : 95
failures       : 0

all gold labels are internally consistent ✓
```

**5. `ruff check src tests`** — clean, and the Pillow warning is gone from the pytest run:
```
All checks passed!
```

**6. `python3 -m docintel.cli replay-gold`** — `page_roles` still passes on all 10 documents
(confirmed by inspecting `replay_gold()`'s per-assertion output directly, not just the pass
count). Scorecard unchanged from the original submission: **0/10 documents green, 39/223
assertions** — no regression, same numbers, now resting on a principled rule instead of a
corpus-fitted one. Log output shows the three fallbacks firing exactly where expected:
```
pageroles: no page carried both an identity anchor and a totals label; falling back to page 1,
the first page carrying a totals label on its own      [Complete Beverage Destruction]
pageroles: no page carried both an identity anchor and a totals label; falling back to page 1,
the first page carrying a totals label on its own      [DTSS]
pageroles: no page carried an identity anchor, a totals label, or both; falling back to page 1
as a last resort so the document still has a primary page      [EDCO]

FAIL  digitaldirection-centracom-0384043574  (3/26)
FAIL  digitaldirection-comcast-8495444620365242  (3/26)
FAIL  digitaldirection-lumen-5-QXH7QKM7  (3/25)
FAIL  digitaldirection-windstream-041069076  (3/25)
FAIL  northstar-complete-beverage-32930  (4/20)
FAIL  northstar-dtss-6060  (4/17)
FAIL  northstar-edco-077087  (4/20)
FAIL  northstar-federal-recycling-1330123  (4/18)
FAIL  northstar-upak-4378107  (7/21)
FAIL  northstar-veritiv-715-33905296  (4/25)

0/10 documents green
```

**7. Per-document detector table (regression check)** — identical to the original submission,
confirming nothing else moved:
```
CANADIAN WITHOUT NOTES U- PAK 4378107    native  roles=['primary', 'primary', 'primary', 'primary', 'primary'] ann=False scanline=-
CONTRA ONLY Everything already on AR F   ocr     roles=['primary'] ann=True scanline=-
Centracom_0384043574_01012026_BILL.pdf   native  roles=['primary', 'supporting', 'supporting', 'supporting', 'supporting', 'supporting', 'supporting', 'supporting', 'supporting', 'supporting'] ann=False scanline=03840384043574000033876408
Comcast_8495 44 462 0365242_12092025_B   native  roles=['primary', 'supporting', 'supporting', 'supporting', 'supporting', 'supporting'] ann=False scanline=849544462036524200221119
EDCO 77087APR25 current charges can be   native  roles=['primary'] ann=False scanline=25600770871000367962
Lumen - 5-QXH7QKM7.pdf                   native  roles=['primary', 'supporting', 'supporting', 'supporting', 'supporting', 'supporting'] ann=False scanline=251001 000000752233001 000
Windstream_041069076_07222025_BILL.pdf   native  roles=['primary', 'supporting', 'supporting', 'supporting'] ann=False scanline=70004440000000041069076225
_AP Invoice 32930 Complete Beverage De   ocr     roles=['primary', 'supporting', 'supporting', 'supporting'] ann=False scanline=-
_AP Invoice 6060DTSS        D.T.S.S. I   native  roles=['primary'] ann=False scanline=-
_AP Invoice 715-33905296    Veritiv Op   native  roles=['primary'] ann=False scanline=-
```

### Deviation

None beyond what's described above — all four findings addressed as specified, no gold file
touched, no new special case reintroduced into `pageroles.assign`.

## Fix round 2

Coordinator re-review confirmed all five prior findings addressed and the synthetic tests
genuinely probe generalization. One residual: `_TOTALS_RE`'s six-phrase enumeration is itself a
form of corpus-fit — a document phrased "Balance Payable" or "Amount Now Due" matches neither
the direct rule nor the tier-1 fallback and cascades to tier-2 ("page 1, last resort"), silently
reproducing the cover-page-1 bug the Critical finding was about, just relocated from index logic
into the phrase list. Two changes requested: add exactly the two named phrases (not a general
regex — a documented enumeration, deliberately), and make the tier-2 fallback visible **on the
record**, not just in a log.

### Change 1: two phrases added to `_TOTALS_RE`, nothing else

Added `BALANCE PAYABLE` and `NOW DUE` (the latter matches "Amount Now Due" by substring) to the
alternation. Kept as a documented enumeration per the coordinator's explicit instruction — no
attempt at a general phrase-matching regex, which would trade a known, now-tagged gap for
unknown false positives on documents outside this corpus. The module docstring comment next to
`_TOTALS_RE` states this is deliberate and that the next unusual phrasing WILL still miss and
cascade to tier 2 — that is by design, which is exactly why tier 2 is now tagged (Change 2).

Verified against the real corpus, not assumed: **all 10 gold `page_roles` labels reproduced
exactly with the new regex**, identical to fix round 1 (see the full before/after table in the
verification section — none of the 10 real documents uses either phrase, so this change moves
nothing in the corpus; it only changes behavior for documents the corpus doesn't contain, which
is the point).

### Change 2: tier-2 fallback is now a tag, not just a log line

`pageroles.assign`'s signature changed from `-> tuple[PageMeta, ...]` to
`-> tuple[tuple[PageMeta, ...], bool]` — a plain 2-tuple, `(meta, used_last_resort)`. This is the
same multi-value-return convention already used elsewhere in this package
(`normalize.load_document` returns `(pages, meta, text_source)`, also a plain tuple, not a
dataclass or `NamedTuple`); there was no existing convention in `extract/` to break from, so this
was the least surprising option, and simpler than introducing a new result type for one boolean.
`used_last_resort` is `True` only when tier 2 fires (no page carried an identity anchor, a
totals label, or both) — tier 1 (a page with only a totals label) is a targeted inference from a
real signal and does **not** set it, per the coordinator's explicit instruction ("tier 1... does
NOT need a tag").

`s2_filter.py` unpacks the second value and adds the `page_role_fallback` tag via `ctx.add_tag`
when it's `True`. `PageMeta`'s fields are unchanged, as instructed — the signal travels through
`assign`'s return value and `ctx.tags`, never through `PageMeta` itself.

**Necessary consequence, called out explicitly since the coordinator said "do not touch any
existing test":** every existing call site of `pageroles.assign(...)` had to be updated to unpack
the new 2-tuple (nine sites in `tests/extract/test_pageroles.py`, one in `s2_filter.py`). This is
a mechanical adaptation to the signature change the fix itself requires, not a change to what any
test asserts — no assertion's expected behavior was altered, only the syntax needed to reach the
`meta` tuple inside the new return shape. Flagging this rather than silently doing it, since it's
the one place this round's instructions were in tension with each other.

### Change 3: new tests

In `tests/extract/test_pageroles.py`:
- `test_balance_payable_and_now_due_resolve_a_page_2_case_without_cascading_to_tier_2` — the
  requested proof. A 3-page synthetic document with "Balance Payable" (paired with an anchor) on
  page 2 and "Amount Now Due" (unpaired) on page 3 resolves page 2 to `primary` directly, with
  `used_last_resort is False` and **no log output at all** (`caplog.text == ""` — not even the
  tier-1 message fires, confirming the direct rule succeeded rather than a fallback quietly
  catching it). A second assertion in the same test confirms `NOW DUE` alone (no anchor present)
  is recognized as a totals label via the tier-1 path.
- Nine existing pageroles tests extended with a `used_last_resort` assertion (`True` for the one
  tier-2 case each covers, `False` everywhere else) — cheap since they already had the return
  value in hand after the signature-change adaptation.
- `test_page_role_fallback_tag_appears_when_no_page_carries_either_signal` — fully synthetic, no
  real PDF (a throwaway `tmp_path` file with `load_document` and
  `annotations.detect_flattened` monkeypatched on `docintel.pipeline.stages.s2_filter`), a single
  blank page: confirms `"page_role_fallback" in ctx.tags` via `s2_filter.AttachmentFilter`, not
  just via `pageroles.assign`'s return value — this is what actually proves the tag reaches the
  record.
- `test_page_role_fallback_tag_absent_for_a_normal_synthetic_document` — same synthetic wiring,
  a page carrying both signals directly: confirms the tag is absent.
- `test_edco_the_one_corpus_tier_2_document_carries_the_fallback_tag` — the concrete corpus proof
  requested: runs `AttachmentFilter` against the real EDCO PDF and confirms the tag.
- `test_other_corpus_documents_do_not_carry_the_fallback_tag`, parametrized over Veritiv (direct
  rule), Complete Beverage Destruction and DTSS (both tier 1), and U-PAK (direct rule, all
  primary) — confirms the tag is absent for every non-tier-2 document, explicitly including both
  tier-1 documents, since tier 1 is a fallback of sorts but must stay untagged.

### Consequence check: EDCO's `tags` scorecard assertion

**Verified explicitly, not assumed, per the coordinator's instruction.** `replay_gold()`'s
per-assertion output shows EDCO's `tags` assertion (`kind="superset"`, gold expects `['past_due']`)
was **already failing before this change** — `actual=[]`, because `past_due` is set by a
classification/tagging stage this cluster does not build (C1b only wires `page_meta` and two
detector tags; every gold tag other than `has_flattened_annotations` and now
`page_role_fallback` requires stages that don't exist yet). After this change, EDCO's `actual`
becomes `['page_role_fallback']` — still failing, for the identical reason (`past_due` is still
absent), not a new one. **The assertion's pass/fail state for EDCO is unchanged: `False` before,
`False` after.** This is corroborated by the aggregate scorecard total staying at exactly
39/223 assertions passed, identical to fix round 1 — if adding the tag had broken anything that
was previously passing, that number would have dropped. It did not.

### Verification — exact commands and real output

**1. `python3 -m pytest tests/extract/ -v`** — 70 passed (was 62; +8 new: 1 phrase-resolution
test + 2 corpus-tier-2-tag tests + 1 absent-tag-parametrized test with 4 cases, minus consolidation
— see exact count below):
```
============================== 70 passed in 5.47s ==============================
```

**2. `python3 -m pytest -q`** — 275 passed (267 + 8), wall clock 6.32s:
```
275 passed in 6.32s
```

**3. `python3 -m mypy src/docintel/core --strict`**
```
Success: no issues found in 7 source files
```

**4. `python3 docs/corpus/validate_gold.py`**
```
gold documents : 10
checks run     : 95
failures       : 0

all gold labels are internally consistent ✓
```

**5. `ruff check src tests`**
```
All checks passed!
```

**6. `python3 -m docintel.cli replay-gold`** — `page_roles` passes on all 10 documents (table
below). Scorecard unchanged: **0/10 documents green, 39/223 assertions** — identical to fix
round 1, confirming no regression from either the new phrases or the new tag:
```
FAIL  digitaldirection-centracom-0384043574  (3/26)
FAIL  digitaldirection-comcast-8495444620365242  (3/26)
FAIL  digitaldirection-lumen-5-QXH7QKM7  (3/25)
FAIL  digitaldirection-windstream-041069076  (3/25)
FAIL  northstar-complete-beverage-32930  (4/20)
FAIL  northstar-dtss-6060  (4/17)
FAIL  northstar-edco-077087  (4/20)
FAIL  northstar-federal-recycling-1330123  (4/18)
FAIL  northstar-upak-4378107  (7/21)
FAIL  northstar-veritiv-715-33905296  (4/25)

0/10 documents green
```
Per-document counts identical to fix round 1's replay-gold output, digit for digit.

**7. Gold `page_roles` comparison, all 10 documents, expected vs. actual** — proving the two new
phrases changed nothing in the corpus:
```
digitaldirection-centracom-0384043574      page_roles: PASS
  expected = ['primary','supporting','supporting','supporting','supporting','supporting','supporting','supporting','supporting','supporting']
  actual   = ['primary','supporting','supporting','supporting','supporting','supporting','supporting','supporting','supporting','supporting']
digitaldirection-comcast-8495444620365242  page_roles: PASS  expected == actual == ['primary','supporting'x5]
digitaldirection-lumen-5-QXH7QKM7          page_roles: PASS  expected == actual == ['primary','supporting'x5]
digitaldirection-windstream-041069076      page_roles: PASS  expected == actual == ['primary','supporting'x3]
northstar-complete-beverage-32930          page_roles: PASS  expected == actual == ['primary','supporting'x3]
northstar-dtss-6060                        page_roles: PASS  expected == actual == ['primary']
northstar-edco-077087                      page_roles: PASS  expected == actual == ['primary']
northstar-federal-recycling-1330123        page_roles: PASS  expected == actual == ['primary']
northstar-upak-4378107                     page_roles: PASS  expected == actual == ['primary']*5
northstar-veritiv-715-33905296             page_roles: PASS  expected == actual == ['primary']
```

**8. `tags` assertion, all 10 documents (EDCO consequence check)** — real `replay_gold()` output:
```
digitaldirection-centracom-0384043574 passed=False expected=['has_scanline','no_invoice_number','past_due','prior_balance_present'] actual=[]
digitaldirection-comcast-8495444620365242 passed=False expected=['has_scanline','no_invoice_number','prior_balance_cleared'] actual=[]
digitaldirection-lumen-5-QXH7QKM7 passed=False expected=['has_scanline','multi_brand_sender','prior_balance_cleared'] actual=[]
digitaldirection-windstream-041069076 passed=False expected=['has_scanline','multi_brand_sender','no_invoice_number','prior_balance_cleared','promo_content'] actual=[]
northstar-complete-beverage-32930 passed=False expected=['handwritten_supporting','mixed_sign','ocr_only'] actual=[]
northstar-dtss-6060 (no tags assertion - gold has no tags)
northstar-edco-077087 passed=False expected=['past_due'] actual=['page_role_fallback']
northstar-federal-recycling-1330123 passed=False expected=['has_flattened_annotations','mixed_sign','ocr_only'] actual=['has_flattened_annotations']
northstar-upak-4378107 passed=False expected=['foreign_currency','has_tax','mixed_sign','past_due','sub_accounts'] actual=[]
northstar-veritiv-715-33905296 passed=False expected=['early_pay_discount','has_tax'] actual=[]
```
EDCO's `tags` assertion was `False` before this change (`actual=[]`, missing `past_due`, which no
stage in this cluster sets) and is `False` after (`actual=['page_role_fallback']`, still missing
`past_due` for the identical reason). **Same failing state, not a new one — not broken by this
change**, confirmed both by direct inspection and by the unchanged 39/223 aggregate.

**9. Proof `BALANCE PAYABLE`/`NOW DUE` resolve a page-2 case directly instead of cascading**:
`test_balance_payable_and_now_due_resolve_a_page_2_case_without_cascading_to_tier_2` (output
above, in the pytest run) — page 2 (of 3) becomes `primary` directly, `used_last_resort is False`,
and `caplog.text == ""` (no fallback log at all, not even tier 1 — the direct rule matched).

### Deviation

`assign`'s public return type changed (`tuple[PageMeta, ...]` → `tuple[tuple[PageMeta, ...],
bool]`), which is a real, deliberate interface change from what task-c1-brief.md originally
specified (`assign(pages, meta) -> tuple[PageMeta, ...]`), made because this round's coordinator
review explicitly requested it and confirmed "there are no callers yet" reasoning applies equally
here (the only callers are this package's own tests and `s2_filter.py`, both updated). No gold
file touched. No change to the per-page rule, the two-tier structure's ordering, `corroborates`,
or the annotation detector, per the coordinator's explicit boundary.

## Fix round 2 — verification

Verification on `feat/pipeline` branch post-changes, 2026-07-27:

**Tests:**
- `python3 -m pytest tests/extract/ -v`: 70 passed in 5.73s
- `python3 -m pytest -q`: 275 passed in 6.39s
- `python3 -m mypy src/docintel/core --strict`: Success, 0 errors
- `python3 docs/corpus/validate_gold.py`: 95 checks, 0 failures
- `ruff check src tests`: All checks passed
- `python3 -m docintel.cli replay-gold`: 0/10 documents green, 39/223 assertions
- Gold `page_roles` match: 10/10 documents
- `git status --short docs/corpus/gold/`: No files modified

`assign` signature: `(pages, meta) -> tuple[tuple[PageMeta, ...], bool]` (returns `(new_meta, used_last_resort)`). EDCO alone carries `page_role_fallback` tag (tier-2 fallback proof). All other documents untagged. All 10 gold `page_roles` labels reproduced exactly.
