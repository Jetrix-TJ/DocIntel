# Task 3 Report: Decide OCR per page, not per document

## What was implemented

`src/docintel/extract/normalize.py::_load_document_uncached` no longer averages
`char_count` across the whole document. It now computes `starved` — the list
of page numbers whose `char_count < NATIVE_CHAR_THRESHOLD` — and routes on
that, per page:

- No starved pages → `pdf.read_pages(path)`, `"native"` (unchanged behaviour).
- All pages starved → `ocr.ocr_pages(path, starved)`, `"ocr"` (unchanged
  behaviour, same call shape as before — `starved` is the full page list).
- Some pages starved (the new case) → native pages read via `pdf.read_pages`,
  starved pages OCR'd via `ocr.ocr_pages(path, starved)`, the two dicts merged
  back into document order. `text_source` is `"ocr"` — the two-valued
  contract is preserved exactly, per the eng review decision in the brief
  (no `"mixed"` value).
- **Critical-gap guard**: if `ocr.ocr_pages` returns fewer pages than
  requested, the missing page numbers are computed and a `TransientError` is
  raised before any fallback can happen. This is the code path that stops
  `ocred.get(n) or native[n]` from silently returning a wordless native page.

The module docstring (previously "Decide once, per document...") was updated
to describe per-page routing, since it was actively wrong after this change
and would have misled the next reader.

`core/models.py` was not touched — no change was needed or made.

## What was tested and the results

Added 5 tests to `tests/extract/test_normalize.py` (verbatim from the brief,
plus the critical-gap test the brief said to add but did not template):

1. `test_a_mixed_document_ocrs_only_the_starved_pages`
2. `test_any_starved_page_makes_the_document_ocr_sourced`
3. `test_an_all_native_document_still_reports_native`
4. `test_an_all_scanned_document_still_reports_ocr`
5. `test_only_the_starved_pages_are_sent_to_tesseract`
6. `test_ocr_returning_a_short_result_raises_transient_not_silently_falls_back`
   (the critical-gap test named in the brief but not templated — patches
   `ocr.ocr_pages` to return a truncated tuple and asserts `TransientError`)

All 19 tests in `tests/extract/test_normalize.py` pass. Full suite: 1490
passed, 12 skipped (skips are pre-existing, unrelated — `printed-fields-only`
deferrals in `test_f1_centracom_trap.py`).

## TDD Evidence

**RED** — `python3 -m pytest tests/extract/test_normalize.py -q -k "mixed or starved or native_document or scanned_document or tesseract or transient"`, run against the fixture + tests with the *old* `_load_document_uncached` still in place:

```
AssertionError: assert 'native' == 'ocr'      # test_any_starved_page_makes_the_document_ocr_sourced
assert [] == [[2, 3, 4]]                       # test_only_the_starved_pages_are_sent_to_tesseract
Failed: DID NOT RAISE <class 'docintel.core.errors.TransientError'>   # the critical-gap test
4 failed, 10 passed, 5 deselected in 4.49s
```

Why these failures were expected: the document-wide average for
`[2343, 0, 0, 0]` is `2343/4 ≈ 586`, above `NATIVE_CHAR_THRESHOLD` (50), so the
old code took the whole-document native path and never called `ocr.ocr_pages`
at all — hence `'native' == 'ocr'` failing, `seen == []`, and no raise. (Two
of the five brief tests, `test_an_all_native_document_still_reports_native`
and `test_an_all_scanned_document_still_reports_ocr`, already passed under the
old code, since a uniform document's average happens to agree with the
per-page result — expected, and not evidence of anything broken.)

**GREEN** — `python3 -m pytest tests/extract/test_normalize.py -q` after the
`_load_document_uncached` rewrite:

```
19 passed in 6.50s
```

## Fixture verification

`_pdf_with_page_char_counts(tmp_path, char_counts)` hand-rolls a minimal PDF
(objects + a classic xref table) rather than depending on a PDF-writing
library, because none is a project dependency (`pyproject.toml` lists only
`pdfplumber`, `pytesseract`, `Pillow`) — `reportlab` and `fpdf` are not
installed, and `pymupdf`/`pypdf`, while present in this venv, are not
declared anywhere in the project and I did not want to add an undeclared
hidden dependency for a test fixture.

- A nonzero count builds a **native text page**: a single `Tj` run of filler
  text truncated to exactly that many characters, no image, no rendering
  needed for `pdfplumber` to read it.
- A zero count builds a **genuinely scanned-style page**: a real JPEG
  (grayscale, built with Pillow, containing legible drawn text via
  `ImageFont.load_default(size=90)` — Pillow 10.1+'s scalable default font, so
  no filesystem font path dependency) embedded as an Image XObject
  (`/Filter /DCTDecode`), drawn with `cm`/`Do` in the content stream. The
  content stream for these pages has **no text-drawing operator at all** —
  not a text page with a handful of characters — so `pdfplumber`'s text-layer
  extraction returns exactly `""`.

Printed proof (`src/docintel/extract/pdf.read_meta` / `read_pages` against
`_pdf_with_page_char_counts(tmp_path, [2343, 0, 0, 0])`):

```
1 char_count= 2343 image_count= 0
2 char_count= 0 image_count= 1
3 char_count= 0 image_count= 1
4 char_count= 0 image_count= 1
1 native words= 353 source= native
2 native words= 0 source= native
3 native words= 0 source= native
4 native words= 0 source= native
```

Page 1's `char_count` matches the requested 2343 exactly (the filler text is
truncated to precisely that length); pages 2-4 are `char_count == 0`,
`image_count == 1` (one real image XObject each), and `read_pages` (the
native-only reader) returns zero words for them, confirming there is really
no text layer to fall back on.

Then, running the *real* `ocr.ocr_pages(path, [2, 3, 4])` (actual Tesseract,
not mocked) against the same fixture:

```
2 words= ['SCANNED', 'ATTACHMENT', 'PAGE', '2', 'REFERENCE', 'COPY', 'NOT', 'AN', 'ORIGINAL'] source= ocr
3 words= ['SCANNED', 'ATTACHMENT', 'PAGE', '3', 'REFERENCE', 'COPY', 'NOT', 'AN', 'ORIGINAL'] source= ocr
4 words= ['SCANNED', 'ATTACHMENT', 'PAGE', '4', 'REFERENCE', 'COPY', 'NOT', 'AN', 'ORIGINAL'] source= ocr
```

Tesseract genuinely reads the embedded image's text back — this is not a
faked "scanned" page. No substitutions were made from the brief's test
snippet; the fixture helper it referenced (and said didn't exist) was built
as described above.

## Cache check

Read `ocr_cache.cache_key` (`src/docintel/extract/ocr_cache.py:63-91`):
`page_numbers` is folded into the SHA-256 payload as
`",".join(str(n) for n in sorted(page_numbers))`, alongside path, size,
mtime, content hash, resolution, and tesseract version. Consequences verified:

- **All-scanned branch** (`len(starved) == len(meta)`) calls
  `ocr.ocr_pages(path, starved)` with `starved` equal to the *entire* page
  list — byte-for-byte the same call this code made before the change — so
  its cache key is unchanged and existing entries for image-only corpus
  documents remain valid.
- **Mixed branch** calls `ocr.ocr_pages(path, starved)` with a strict subset
  of pages. Because `page_numbers` is part of the hash, this subset produces
  a cache key distinct from both the full-page key and any other subset —
  it cannot collide with, overwrite, or be served by an existing entry.

Empirically confirmed against the real corpus cache
(`var/ocr-cache/`, 175 entries): captured the sorted list of cache filenames,
ran `python3 -m docintel.cli replay-gold` under the new code, and recaptured
the list — **identical**, byte-for-byte, no additions or removals. No corpus
document is mixed, so this is exactly the expected/required outcome: the
change is inert for every existing cache entry.

## Scorecard

Before and after: **202/263 assertions, 1/10 documents green** (unchanged, as
required). Ran `python3 docs/corpus/validate_gold.py` (10 gold documents, 95
checks, 0 failures) and `python3 -m docintel.cli replay-gold`:

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

Sum of passes: 202. Sum of totals: 263. All ten `text_source` gold assertions
still pass (verified via `validate_gold.py`'s 0 failures and the full test
suite, which includes `test_native_documents_use_the_text_layer` and
`test_image_only_documents_route_to_ocr` for all ten corpus documents) — no
corpus document is mixed, so none changed value, as expected.

## Files changed

- `src/docintel/extract/normalize.py` — per-page routing in
  `_load_document_uncached`, updated module docstring, `TransientError`
  import.
- `tests/extract/test_normalize.py` — fixture helpers
  (`_pdf_with_page_char_counts`, `_PDFObjects`, `_scanned_page_jpeg`) and six
  new tests.

## Verification commands run

```
python3 -m pytest -q                       # 1490 passed, 12 skipped
python3 -m mypy                            # Success: no issues found in 26 source files
ruff check src tests                       # All checks passed!
python3 docs/corpus/validate_gold.py       # 95 checks, 0 failures
python3 -m docintel.cli replay-gold        # 202/263, 1/10 green
```

## Self-review

- **Completeness**: all five brief steps done — failing test, confirmed RED,
  per-page routing, full verification, commit. The critical-gap test was
  added as instructed (not templated in the brief, built per its
  description).
- **Naming**: test names and the fixture helper name match the brief
  verbatim (`_pdf_with_page_char_counts`, all five given test names).
- **YAGNI**: no `"mixed"` value, no speculative per-page confidence scoring
  (explicitly deferred to C7 per the brief), no changes to
  `core/models.py`, no changes outside the two files the brief scopes.
- **Test quality**: the mixed-document fixture is genuinely image-only where
  it claims to be (verified by printed `char_count`/`image_count` output) and
  genuinely OCR-able (verified against real Tesseract, not a stub). The
  critical-gap test exercises the real `TransientError` path via a
  monkeypatched short-return, not a mock of the whole function.
- **Pristine output**: `pytest -v` on the full file shows no warnings; mypy
  and ruff are clean.

## Issues or concerns

- **Minor, out-of-scope edge case noticed during review**: for a
  zero-page PDF (`meta == ()`), the *old* code's average
  (`0.0 < NATIVE_CHAR_THRESHOLD`) took the OCR branch and called
  `ocr.ocr_pages(path, [])`; the *new* code's `starved == []` takes the
  native branch and calls `pdf.read_pages(path)`. Both return an empty page
  tuple either way — the only difference is the `text_source` label on a
  document with zero pages, which is not exercised by the corpus, the brief,
  or any existing test, and has no observable effect (there are no pages to
  apply the label to). Flagging it rather than silently deciding it doesn't
  matter; happy to add a guard if desired, but did not add one to avoid
  YAGNI on an edge case nothing in the codebase depends on.
- `pymupdf`/`pypdf` are present in this dev venv but are not project
  dependencies; I deliberately did not use them for the fixture, hand-rolling
  minimal PDF bytes instead so the test suite doesn't gain a hidden,
  undeclared dependency.
