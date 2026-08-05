# Verified-Findings Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the seven issues independently verified against live `dev` HEAD on 2026-08-05 (see the verification report earlier in this session): the Edco/Veritiv auto-approve gap, the U-Pak wrong-amount bug, the five-vendor wrong-inbox gap, the 6 invisible Edco invoices, the leaked blind-test reference material, and the three worst address-field misses. One task is a business ask, not engineering.

**Architecture:** No architectural change. Every fix is a persona JSON edit (`src/docintel/packs/*/personas/*.json`), a small pure-Python change in the shared grammar engine (`src/docintel/grammar/`) or a pack module (`src/docintel/packs/northstar/`), or a documentation edit. The extraction engine stays config-driven — "adding a vendor means adding a JSON file," per `docs/STATUS-SUMMARY.md` §1 — and this plan does not change that.

**Tech Stack:** Python 3.12, pytest, the existing closed-grammar selector engine (`docintel.grammar`), `pdfplumber` for one-off page-geometry checks during implementation.

## Global Constraints

- `docs/corpus/gold/*.json` is READ-ONLY. A gold change requires re-reading the source PDF and a written justification in the commit message.
- Never classify or extract from a filename.
- Corpus-only tests confirm corpus-fit, not corpus-overfit — every task that changes selector/engine behavior needs at least one synthetic fixture test, built the way `tests/packs/test_veritiv_invoice_number.py` already does: load the real selector out of the shipped persona via `docintel.packs.registry.load_packs()`, run it through the real `docintel.grammar.executor.Executor` against a hand-built `PageText`/`Word` fixture, assert on `ctx.extracted` and `ctx.extracted.match_quality`. Do not re-type the selector as a literal in the test — that tests a copy, not the rule.
- No assertion may pass against an empty record (`tests/test_scorecard_coverage.py`, GUARDRAIL 3).
- **Baseline to hold or beat: 243/310 assertions, verified fresh via `replay-gold` on 2026-08-05 (not the 222/287 in the currently-committed `docs/STATUS-SUMMARY.md`, which predates commit `e3bd6b7`).** Get the live figure with `python3 -m docintel.cli replay-gold --json` — `.loop/scorecard.json` is stale, do not trust it.
- The region vocabulary (`docs/architecture/selector-grammar.md` §2, enforced by `tests/grammar/test_regions.py::test_all_fifteen_regions_exist` and validator rule V3) is a **closed, deliberately-scoped enum**. Adding a new region name is a spec change, not a routine edit — confirm with the user before landing Task 8's stretch option.
- **Verify with:**
  `python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold --json`
- Commit after every task. One task, one commit, `type(scope): sentence` message style, matching the existing history (`fix(packs): ...`, `feat(scorecard): ...`).

---

## File Structure

| File | Responsibility | Tasks touching it |
|---|---|---|
| `src/docintel/packs/northstar/thresholds.py` | Per-field confidence bar for the `high` lane | 1 |
| `src/docintel/packs/northstar/personas/veritiv.json` | Veritiv's field selectors | 2 |
| `src/docintel/packs/northstar/personas/upak.json` | U-Pak's field selectors | 3, 6 |
| `src/docintel/packs/northstar/__init__.py` | `BILL_TO_MARKERS`, `NorthstarPack.claims()` | 4 |
| `src/docintel/packs/northstar/ladder.py` | `doc_type_for()` — the document-type classification ladder | 5 |
| `src/docintel/packs/digitaldirection/personas/comcast.json` | Comcast's field selectors | 7 |
| `src/docintel/packs/digitaldirection/personas/windstream.json` | Windstream's field selectors | 8 |
| `src/docintel/packs/northstar/personas/edco.json` | Edco's field selectors | 8, 10 |
| `src/docintel/grammar/regions.py` | Region resolver vocabulary (only touched if Task 8's stretch option is confirmed) | 8 (conditional) |
| `src/docintel/grammar/ops/derive.py`, `crosscheck.py`, `base.py`, `patterns.py`, `schema.py`, `regions.py`, `executor.py` | Grammar engine source — currently leaks gold answers in comments | 9 |
| `docs/persona-regeneration/reference/selector-grammar.md`, `pack-northstar.md` | "Redacted" reference material for blind persona authoring — currently under-redacted | 9 |
| `docs/persona-regeneration/*/persona.json` (9 folders) | Already-completed blind runs, contaminated by Task 9's leak | 9 |
| `src/docintel/packs/digitaldirection/personas/comcast.json` | `remit_address` selector | 10 |
| `src/docintel/packs/northstar/personas/upak.json` | `bill_to_address` selector | 10 |
| Federal Recycling persona (whichever pack owns it — confirm at Task 10) | `vendor_address`/`remit_address`/`bill_to_address` | 10 |

Tests live beside the existing convention: `tests/packs/test_<vendor>_<field>.py` for selector-level fixtures, `tests/grammar/` for engine-level changes, `tests/packs/northstar/` (or wherever the existing `claims()`/ladder tests live — check at Task 4/5 time) for pack-level classification logic.

---

### Task 1: Recalibrate Edco's `total_printed` threshold to what a region-only match can honestly clear

**Why not add an anchor instead:** read on the real, unrecognized-typo-free sample `all-docs/second-samples/edco/_AP Invoice 27267AUG25 ... .pdf` (or any healthy Edco sample), the `total_printed` value (e.g. `551.09`) is printed alone in a coupon-stub box with **no adjacent label text at all** — confirmed by dumping page-1 word coordinates: the only words within 150pt of the top are the letterhead, the account/invoice/date row, and the bare currency figure on its own line. Every other Edco field that clears `high` today does so because it has a real anchor. Forcing a fabricated anchor onto a field with nothing on the page to confirm it would be the "confident wrong" failure mode `executor.py`'s own module docstring explicitly warns against ("a loud empty result is recoverable; a confident wrong one is not"). The honest fix is to stop asking a region-only match to clear a bar only an anchored match can reach.

**Files:**
- Modify: `src/docintel/packs/northstar/thresholds.py:18`
- Test: `tests/packs/test_edco_total_printed_threshold.py` (new)

**Interfaces:**
- Consumes: `docintel.grammar.executor.QUALITY_REGION_ONLY` (0.90, unchanged) — the ceiling this task aligns the threshold to.
- Produces: nothing new; `THRESHOLDS["total_printed"]` is read by `src/docintel/core/confidence.py` (or wherever Stage 6 reads it — confirm the exact import site while implementing) at scoring time.

- [ ] **Step 1: Write the failing test**

```python
"""Edco's `total_printed` has no printed label on the page it's read from
(confirmed by reading the real second-sample PDFs), so a region-only match is
the strongest evidence this field can ever produce. Held at 0.95 - the same
bar as an anchored field - it can never clear `high`, even when the value is
correct, which it always was in the F1-verified corpus. See the commit this
test ships with for the page-geometry evidence."""

from __future__ import annotations

from docintel.grammar.executor import QUALITY_REGION_ONLY
from docintel.packs.northstar.thresholds import THRESHOLDS


def test_edco_total_printed_threshold_is_reachable_by_a_region_only_match() -> None:
    assert THRESHOLDS["total_printed"] <= QUALITY_REGION_ONLY
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/packs/test_edco_total_printed_threshold.py -v`
Expected: FAIL — `0.95 <= 0.90` is false.

- [ ] **Step 3: Lower the threshold with a reasoning comment matching the file's existing style**

In `src/docintel/packs/northstar/thresholds.py`, change:
```python
    "total_printed": 0.95,
```
to:
```python
    # Held at 0.95 until 2026-08-05: real Edco second samples print this value
    # with no adjacent label at all (a bare figure in a coupon-stub box), so a
    # region-only match - QUALITY_REGION_ONLY, 0.90 - is the strongest evidence
    # this field can produce on this vendor. 0.95 made `high` structurally
    # unreachable regardless of correctness. Every value measured against gold
    # was correct; the field just could never clear its own bar.
    "total_printed": 0.90,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/packs/test_edco_total_printed_threshold.py -v`
Expected: PASS

- [ ] **Step 5: Confirm this doesn't silently mask a real future miss on a different vendor**

`total_printed` is shared across every Northstar persona, not Edco-only. Run:
`python3 -m docintel.cli replay-gold --json` and confirm no OTHER vendor's `total_printed` assertion or lane changed — this task must be a net add (Edco's lane improves) with zero regressions elsewhere. If another vendor's `total_printed` currently relies on the 0.95 bar to force a legitimate review, stop and flag it before continuing — do not lower a shared threshold to fix one vendor if it silently downgrades another's safety net.

- [ ] **Step 6: Run full verification and commit**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold --json
git add src/docintel/packs/northstar/thresholds.py tests/packs/test_edco_total_printed_threshold.py
git commit -m "fix(scorecard): lower Edco total_printed threshold to its honest region-only ceiling"
```

---

### Task 2: Anchor Veritiv's `invoice_number` selector so it can reach `high`

**Evidence:** the real `689-`-prefixed sample (`all-docs/second-samples/veritiv/_AP Invoice 689-37578305 ...pdf`) prints `Invoice No.` at `(top=85.2, x0=374.9)` and the value `689-37578305` at `(top=99.5, x0=366.6)` — 14.3pt below, left-aligned within a few points. This is the exact same shape as the already-working `invoice_date` selector in the same persona (`anchor: "Invoice Date"`, `region: "near-anchor"`), which already correctly reads `10/07/2025` off the same row. `invoice_number` is currently the one sibling field left on `region: "header-block"` with no anchor, capping it at `QUALITY_REGION_ONLY = 0.90` — under its own 0.92 threshold. `Invoice No.` appears twice on the page (once in the header summary table, once lower in the line-item table); default `anchor_occurrence: "first"` picks the header occurrence, which is the one paired with the value — matches `invoice_date`'s already-proven behavior on the identical page.

**Files:**
- Modify: `src/docintel/packs/northstar/personas/veritiv.json:9-12`
- Test: `tests/packs/test_veritiv_invoice_number.py` (extend the existing file)

**Interfaces:**
- Consumes: `docintel.grammar.regions.RESOLVERS["near-anchor"]` (existing, unmodified).
- Produces: `ctx.extracted.match_quality["invoice_number"] == QUALITY_ANCHORED (1.0)` for downstream lane-routing tests.

- [ ] **Step 1: Write the failing test**

Add to `tests/packs/test_veritiv_invoice_number.py`:

```python
from docintel.grammar.executor import Executor, QUALITY_ANCHORED
from docintel.grammar.schema import parse_persona


def _extract_with_quality(invoice_no: str) -> tuple[str | None, float | None]:
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_veritiv_invoice_number_selector()],
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(_header_page(invoice_no)))
    return ctx.extracted.get("invoice_number"), ctx.extracted.match_quality.get("invoice_number")


def test_invoice_number_is_anchored_not_region_only() -> None:
    """The bug this fixes: region-only match_quality (0.90) sits under Veritiv's
    own 0.92 invoice_number threshold, so this field alone forces every Veritiv
    document to `medium` even when the value is correct. An anchored match
    (1.0) clears it."""
    _, quality = _extract_with_quality("689-37525600")
    assert quality == QUALITY_ANCHORED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/packs/test_veritiv_invoice_number.py::test_invoice_number_is_anchored_not_region_only -v`
Expected: FAIL — current quality is `QUALITY_REGION_ONLY` (0.90), not `QUALITY_ANCHORED` (1.0).

- [ ] **Step 3: Update the existing test fixture to include the label above the value**

The existing `_header_page` fixture already places `"Invoice"`/`"No."` on the same line as the value (a same-row layout), which `near-anchor` also covers (its box starts at `anchor.y0 - line_tolerance`, i.e. at the anchor's own line). No fixture change is required — confirm this by re-reading `_header_page` before editing anything, since the plan's Step 5 below has a fallback if this assumption is wrong.

- [ ] **Step 4: Change the persona selector**

In `src/docintel/packs/northstar/personas/veritiv.json`, change:
```json
{
  "field": "invoice_number",
  "region": "header-block",
  "pattern": "([0-9]{3}-[0-9]{8})"
}
```
to:
```json
{
  "field": "invoice_number",
  "anchor": "Invoice No.",
  "region": "near-anchor",
  "pattern": "([0-9]{3}-[0-9]{8})"
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/packs/test_veritiv_invoice_number.py -v`
Expected: all tests in the file PASS, including the three pre-existing ones (no regression on `715-`/`689-` prefixes or the account-number bleed guard).

If `test_invoice_number_is_anchored_not_region_only` still reports `QUALITY_REGION_ONLY`: the synthetic fixture's `Account No.` cell (same line, x0=250-358) may be getting picked up as a second `Invoice No.`-adjacent candidate ahead of the real value — read `near-anchor`'s exact x-bounds against the fixture's coordinates and adjust the fixture (not the persona) to match the real PDF's spacing (label at x0≈375, value at x0≈367 — closer together than the fixture's current label-at-10/value-at-82 gap) before concluding the persona change is wrong.

- [ ] **Step 6: Verify against the real corpus, not just the synthetic fixture**

```bash
python3 -m docintel.cli process --json "all-docs/second-samples/veritiv/_AP Invoice 689-37578305    Veritiv Operating Company 3312.50000.pdf" --vision cassette
```
Confirm `invoice_number` extracts `689-37578305` with `match_quality` at 1.0, and repeat against `all-docs/second-samples/veritiv/*.pdf` (all 7) plus the gold document (`docs/corpus/gold/northstar-veritiv-715-33905296.json`) via `replay-gold` to confirm none regress and the gold lane assertion, if any, is unaffected or improves.

- [ ] **Step 7: Run full verification and commit**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold --json
git add src/docintel/packs/northstar/personas/veritiv.json tests/packs/test_veritiv_invoice_number.py
git commit -m "fix(packs): anchor Veritiv invoice_number so it can reach the high lane"
```

---

### Task 3: Fix U-Pak's `please_pay` selector — reuse `totals-block`, the region already built for this exact case

**Evidence:** `docs/architecture/selector-grammar.md:145-147` documents, verbatim: *"Why `totals-block` searches the last page first: U-PAK's payable is on page 5 of 5 and page 1's `Please Pay` cell is blank (F9). Searching page 1 first finds an empty cell and reports a confident miss."* This is a pre-existing, purpose-built region for precisely this document. The current `please_pay` selector uses `region: "last-page"` instead, whose resolver (`regions.py:347-350`) ignores the `anchor` field entirely — `"anchor": "Please Pay"` is currently **dead configuration**. `last-page` returns the whole page 5 as one unstructured span; the executor's candidate scan then finds `Subtotal 8119.44` (the first currency figure on the page, at y=582.7) before reaching the real `Please Pay AMOUNT ... $14740.85` row (y=675.7). `totals-block`'s resolver (`_totals_block`/`_totals_on`, `regions.py:405-431`) bands the search to `[label_top - 2pt, label_top + ~69pt]` around whichever line matches `_TOTALS_RE` (which includes `PLEASE PAY` explicitly, `regions.py:227`) on page 5 — that band contains the `AMOUNT`/`$14740.85` row and excludes `Subtotal` (81pt above the band's top edge), by construction, on every page it searches.

**Files:**
- Modify: `src/docintel/packs/northstar/personas/upak.json:49-54`
- Test: `tests/packs/test_upak_please_pay.py` (new)

**Interfaces:**
- Consumes: `docintel.grammar.regions.RESOLVERS["totals-block"]` (existing, unmodified).
- Produces: `ctx.extracted["please_pay"] == "14740.85"` (or the pre-`adjust` raw string; confirm exact post-`derive_amount_payable` shape when running Step 6).

- [ ] **Step 1: Write the failing test**

```python
"""F9 regression: U-Pak's `please_pay` selector declared an `anchor` that its
`last-page` region silently ignored (region-only value pages return whole-page
spans and never consult `anchor`). The executor then took the first currency
figure on the last page - `Subtotal 8119.44` - instead of the real
`Please Pay AMOUNT ... $14740.85` row further down the same page. Confirmed
against the real 5-page source PDF: pages 1-4 print the same `Please Pay`
column header with a blank AMOUNT cell; only page 5 fills it in, and
`Subtotal` sits 81pt above that filled cell on page 5 itself.

This fixture models the two facts that matter: (1) an earlier page with the
same anchor and a blank value, and (2) the last page carrying both a
`Subtotal` figure ABOVE the totals band and the real `Please Pay` figure
INSIDE it.
"""

from __future__ import annotations

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs

WIDTH = 612.0
HEIGHT = 792.0


def _upak_please_pay_selector() -> dict:
    for pack in load_packs():
        if pack.name != "northstar":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint") == "northstar|upak":
                for selector in persona["field_selectors"]:
                    if selector.get("field") == "please_pay":
                        return selector
    raise AssertionError("northstar|upak persona (or its please_pay selector) not found")


def _blank_please_pay_page(number: int) -> PageText:
    words = [
        Word(text="Please", x0=528.0, y0=663.0, x1=550.0, y1=673.0),
        Word(text="Pay", x0=555.0, y0=663.0, x1=572.0, y1=673.0),
        Word(text="AMOUNT", x0=49.0, y0=675.0, x1=95.0, y1=685.0),
    ]
    return PageText(page_number=number, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def _filled_last_page(number: int) -> PageText:
    words = [
        Word(text="Subtotal", x0=462.0, y0=582.0, x1=505.0, y1=592.0),
        Word(text="8119.44", x0=541.0, y0=582.0, x1=580.0, y1=592.0),
        Word(text="Please", x0=528.0, y0=663.0, x1=550.0, y1=673.0),
        Word(text="Pay", x0=555.0, y0=663.0, x1=572.0, y1=673.0),
        Word(text="AMOUNT", x0=49.0, y0=675.0, x1=95.0, y1=685.0),
        Word(text="$14740.85", x0=532.0, y0=675.0, x1=580.0, y1=685.0),
    ]
    return PageText(page_number=number, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def _ctx(pages: tuple[PageText, ...]) -> JobContext:
    meta = tuple(
        PageMeta(
            page_number=p.page_number,
            char_count=sum(len(w.text) for w in p.words),
            image_count=0,
            annot_count=0,
            role="primary",
        )
        for p in pages
    )
    return JobContext(
        document_id="d1", source_path="x.pdf", pages=pages, page_meta=meta,
        doc_type="standard_invoice",
    )


def _extract_please_pay() -> str | None:
    pages = (_blank_please_pay_page(1), _filled_last_page(2))
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_upak_please_pay_selector()],
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(pages))
    return ctx.extracted.get("please_pay")


def test_please_pay_reads_the_filled_last_page_amount_not_the_subtotal() -> None:
    assert _extract_please_pay() == "14740.85"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/packs/test_upak_please_pay.py -v`
Expected: FAIL — currently returns `"8119.44"` (the Subtotal).

- [ ] **Step 3: Change the persona selector**

In `src/docintel/packs/northstar/personas/upak.json`, change:
```json
{
  "field": "please_pay",
  "anchor": "Please Pay",
  "region": "last-page",
  "pattern": "currency",
  "required": false
}
```
to:
```json
{
  "field": "please_pay",
  "anchor": "Please Pay",
  "region": "totals-block",
  "pattern": "currency",
  "required": false
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/packs/test_upak_please_pay.py -v`
Expected: PASS

- [ ] **Step 5: Verify against the real 5-page gold PDF**

```bash
python3 -m docintel.cli replay-gold --json
```
Confirm the `northstar-upak-4378107` result now shows `fields.please_pay: "14740.85"` (was `"8119.44"`), and check whether `derived.amount_payable`/`payable_basis` — currently `null`/`null` because `derive_amount_payable` correctly refuses when `total_printed` (14789.77) and `please_pay` disagree with nothing on the page explaining it — now resolve differently now that `please_pay` is correct. Read `upak.json`'s own `notes` field (already documents this refusal behavior) before concluding either outcome is a bug; if the refusal behavior changes, that is expected and should be reflected in the assertion, not treated as a regression.

- [ ] **Step 6: Run full verification and commit**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold --json
git add src/docintel/packs/northstar/personas/upak.json tests/packs/test_upak_please_pay.py
git commit -m "fix(packs): read U-Pak please_pay via totals-block instead of last-page's first-currency scan"
```

---

### Task 4: Broaden `BILL_TO_MARKERS` so typo'd Edco invoices are still recognized

**Evidence:** all 4 unrecognized real Edco invoices (`176024OCT25`, `709223OCT25`, `823282AUG25`, `823282SEP25`) have a garbled company name in their printed bill-to block (`NORTHSTART RECYCLING`, `NORTHSTAR RECY`, `NORTHSTRAY RECYCLING` ×2) that misses every literal in `BILL_TO_MARKERS` (`src/docintel/packs/northstar/__init__.py:30-36`). Directly re-read all 4 PDFs: in every one, **`MA 01028` (Northstar's own state+zip) prints correctly**, even in the one case (`176024OCT25`) where the city name is also garbled (`EASTE LONGMEADOWN MA 01028`). This is a stable, low-risk addition: specific enough not to false-positive on an unrelated vendor, and untouched by every typo variant found so far.

**Files:**
- Modify: `src/docintel/packs/northstar/__init__.py:30-36`
- Test: `tests/packs/test_northstar_claims.py` (new, or extend an existing `claims()` test if one exists — check with `grep -rl "\.claims(" tests/` before creating a new file)

**Interfaces:**
- Consumes: `docintel.packs.northstar.normalize_name`, `primary_text` (existing).
- Produces: `NorthstarPack.claims(ctx) -> bool`, unchanged signature.

- [ ] **Step 1: Check for an existing claims() test file**

Run: `grep -rl "\.claims(" tests/`
If a file already tests `NorthstarPack.claims()`, add the new test there instead of creating a new file; otherwise create `tests/packs/test_northstar_claims.py`.

- [ ] **Step 2: Write the failing test**

```python
"""4 of 28 real second-sample Edco invoices print a typo'd bill-to company
name (`NORTHSTART RECYCLING`, `NORTHSTAR RECY`, `NORTHSTRAY RECYCLING`) that
misses every literal in BILL_TO_MARKERS, so NorthstarPack.claims() returns
False and the document is silently tagged `unclaimed_document` - not an
error, just zero fields extracted. Every one of the 4 real documents still
prints its state+zip correctly (`MA 01028`), even the one where the city name
is ALSO garbled. This is the fixture for that: a page with a typo'd company
name and an intact `MA 01028`."""

from __future__ import annotations

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.packs.northstar import NorthstarPack

WIDTH = 612.0
HEIGHT = 792.0


def _page_with(*lines: str) -> PageText:
    words: list[Word] = []
    y = 100.0
    for line in lines:
        x = 50.0
        for token in line.split():
            words.append(Word(text=token, x0=x, y0=y, x1=x + 6.0 * len(token), y1=y + 10.0))
            x += 6.0 * len(token) + 4.0
        y += 12.0
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def _ctx(page: PageText) -> JobContext:
    meta = (
        PageMeta(page_number=1, char_count=sum(len(w.text) for w in page.words),
                 image_count=0, annot_count=0, role="primary"),
    )
    return JobContext(document_id="d1", source_path="x.pdf", pages=(page,), page_meta=meta,
                       doc_type="standard_invoice")


def test_claims_a_typo_d_bill_to_name_via_the_intact_zip() -> None:
    page = _page_with("NORTHSTART RECYCLING", "HUNTER INDUSTRY", "PO BOX 188", "EASTE LONGMEADOWN MA 01028")
    assert NorthstarPack().claims(_ctx(page)) is True


def test_claims_a_transposed_typo_via_the_intact_zip() -> None:
    page = _page_with("NORTHSTRAY RECYCLING", "SYSCO - 40YD", "94 MAPLE ST", "EAST LONGMEADOW MA 01028")
    assert NorthstarPack().claims(_ctx(page)) is True


def test_still_rejects_an_unrelated_vendor() -> None:
    page = _page_with("ACME WIDGETS INC", "100 MAIN ST", "SPRINGFIELD IL 62701")
    assert NorthstarPack().claims(_ctx(page)) is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/packs/test_northstar_claims.py -v`
Expected: the first two tests FAIL (return `False`); the third already PASSes.

- [ ] **Step 4: Add the marker**

In `src/docintel/packs/northstar/__init__.py`, change:
```python
BILL_TO_MARKERS: tuple[str, ...] = (
    "northstar recycling",
    "northstar bimbo",
    "nsrecycle com",
    "po box 188 east longmeadow",
    "94 maple st east longmeadow",
)
```
to:
```python
BILL_TO_MARKERS: tuple[str, ...] = (
    "northstar recycling",
    "northstar bimbo",
    "nsrecycle com",
    "po box 188 east longmeadow",
    "94 maple st east longmeadow",
    # Real Edco second samples print the company name with OCR/print typos
    # (NORTHSTART, NORTHSTAR RECY, NORTHSTRAY) that miss every marker above,
    # but the state+zip prints correctly in all 4 confirmed cases, even the
    # one where the city name is also garbled. Confirmed 2026-08-05 against
    # all-docs/second-samples/edco/{176024OCT25,709223OCT25,823282AUG25,823282SEP25}.
    "ma 01028",
)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/packs/test_northstar_claims.py -v`
Expected: all PASS.

- [ ] **Step 6: Verify against the real 4 documents**

```bash
python3 -m docintel.cli process --json "all-docs/second-samples/edco/_AP Invoice 176024OCT25     Edco Waste & Recycling Services Inc. 348.84000.pdf" --vision cassette
```
Repeat for the other 3. Confirm each now resolves `sender_fingerprint` to `northstar|edco` and extracts a normal field set (no longer `unclaimed_document`). Also re-run all 28 Edco second samples to confirm no false positive appeared elsewhere.

- [ ] **Step 7: Run full verification and commit**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold --json
git add src/docintel/packs/northstar/__init__.py tests/packs/test_northstar_claims.py
git commit -m "fix(packs): recognize typo'd Edco bill-to blocks via the intact state+zip"
```

---

### Task 5: Stop misclassifying genuine 2-page continuation invoices as `invoice_with_attachment`

**Evidence:** `_AP Invoice 823283AUG25 ...pdf` is a genuine single 2-page invoice — both pages repeat the identical identity header (`EDCO WASTE & RECYCLING SERVICE ... 25-5R 823283 08/31/25`) and both carry the matching footer pagination marker `000000-001 MD9-M 1 OF 2` / `2 OF 2`. But its line items overflow page 1, so `CURRENT CHARGES:` (the totals label `_page_signals` checks for) only appears on page 2 — page 1 gets `(has_anchor=True, has_totals=False)`, page 2 gets `(has_anchor=True, has_totals=True)`. `pageroles.assign()` correctly marks exactly one page `primary` (page 2) and one `supporting` (page 1), but `ladder.py:120`'s rule — `if primary == 1 and supporting >= 1: return "invoice_with_attachment"` — can't distinguish that shape from an actual invoice+attachment pair, since it only counts roles, not what produced them. `invoice_with_attachment` doc type has no matching Edco persona, so extraction silently fails to `0` populated fields.

**Files:**
- Modify: `src/docintel/packs/northstar/ladder.py` (add a helper near `_has_table`, gate the `invoice_with_attachment` return at line 120)
- Test: `tests/packs/test_northstar_ladder.py` (extend if it exists — check first — else new)

**Interfaces:**
- Consumes: `ctx.pages` (existing `JobContext` field), `PageText.lines()`.
- Produces: a new module-level helper, `_is_paginated_continuation(ctx: JobContext) -> bool`, consumed only by `doc_type_for()`.

- [ ] **Step 1: Check for an existing ladder test file**

Run: `grep -rl "doc_type_for" tests/`
Add to that file if found; otherwise create `tests/packs/test_northstar_ladder.py`.

- [ ] **Step 2: Write the failing test**

```python
"""823283AUG25/823283SEP25 regression: a genuine 2-page Edco invoice whose
line items overflow onto page 2, pushing the totals label off page 1. Both
pages repeat the same identity header and both print a footer pagination
marker (`1 OF 2` / `2 OF 2`) - real evidence this is one paginated invoice,
not an attachment. Confirmed by reading both pages of the real source PDF:
`pageroles.assign` correctly marks page 2 primary / page 1 supporting (the
totals label only appears on page 2), which is the exact (primary=1,
supporting>=1) shape the ladder's `invoice_with_attachment` rule treats as an
attachment pair - indistinguishable by role count alone."""

from __future__ import annotations

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.packs.northstar.ladder import doc_type_for

WIDTH = 612.0
HEIGHT = 792.0


def _word(text: str, x0: float, y0: float) -> Word:
    return Word(text=text, x0=x0, y0=y0, x1=x0 + 6.0 * len(text), y1=y0 + 10.0)


def _page_1_no_totals(footer: str) -> PageText:
    words = [
        _word("EDCO", 51.0, 33.0), _word("WASTE", 82.0, 33.0),
        _word("25-5R", 362.0, 56.0), _word("823283", 392.0, 56.0),
        _word("HAUL", 77.0, 500.0), _word("225.10", 250.0, 500.0),
        *[_word(t, 50.0 + i * 60.0, 700.0) for i, t in enumerate(footer.split())],
    ]
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def _page_2_with_totals(footer: str) -> PageText:
    words = [
        _word("EDCO", 51.0, 33.0), _word("WASTE", 82.0, 33.0),
        _word("25-5R", 362.0, 56.0), _word("823283", 392.0, 56.0),
        _word("CURRENT", 77.0, 579.0), _word("CHARGES:", 128.0, 579.0),
        _word("3267.54", 377.0, 579.0), _word("2479.01", 540.0, 579.0),
        *[_word(t, 50.0 + i * 60.0, 700.0) for i, t in enumerate(footer.split())],
    ]
    return PageText(page_number=2, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def _ctx(pages: tuple[PageText, ...], roles: tuple[str, ...]) -> JobContext:
    meta = tuple(
        PageMeta(page_number=p.page_number, char_count=sum(len(w.text) for w in p.words),
                 image_count=0, annot_count=0, role=r)
        for p, r in zip(pages, roles, strict=True)
    )
    return JobContext(document_id="d1", source_path="x.pdf", pages=pages, page_meta=meta, doc_type="")


def test_a_paginated_continuation_is_not_invoice_with_attachment() -> None:
    pages = (_page_1_no_totals("000000-001 MD9-M 1 OF 2"), _page_2_with_totals("000000-001 MD9-M 2 OF 2"))
    ctx = _ctx(pages, ("supporting", "primary"))
    doc_type, _signal = doc_type_for(ctx)
    assert doc_type != "invoice_with_attachment"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/packs/test_northstar_ladder.py::test_a_paginated_continuation_is_not_invoice_with_attachment -v`
Expected: FAIL — `doc_type == "invoice_with_attachment"`.

- [ ] **Step 4: Implement the pagination check**

In `src/docintel/packs/northstar/ladder.py`, add near `_has_table`:

```python
import re as _re  # only if `re` isn't already imported under a different alias - check the file's existing imports first

_PAGE_OF_RE = _re.compile(r"\b(\d+)\s+OF\s+(\d+)\b")


def _is_paginated_continuation(ctx: JobContext) -> bool:
    """True if every page carries a `N OF M` footer with M == len(ctx.pages).

    A real attachment (a Bill of Lading stapled behind an invoice) has no
    reason to share the invoice's own pagination sequence. A genuine
    multi-page invoice whose totals label overflowed onto a later page - the
    same (primary=1, supporting>=1) role shape the ladder otherwise reads as
    "invoice plus attachment" - does. Reading the real printed footer, not
    guessing from role counts, is what tells the two apart.
    """
    total_pages = len(ctx.pages)
    if total_pages < 2:
        return False
    seen_numbers: set[int] = set()
    for page in ctx.pages:
        found = False
        for line in page.lines():
            text = " ".join(w.text for w in line).upper()
            match = _PAGE_OF_RE.search(text)
            if match and int(match.group(2)) == total_pages:
                seen_numbers.add(int(match.group(1)))
                found = True
                break
        if not found:
            return False
    return seen_numbers == set(range(1, total_pages + 1))
```

Then change line 120 from:
```python
    if primary == 1 and supporting >= 1:
        return "invoice_with_attachment", "one_primary_plus_supporting"
```
to:
```python
    if primary == 1 and supporting >= 1 and not _is_paginated_continuation(ctx):
        return "invoice_with_attachment", "one_primary_plus_supporting"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/packs/test_northstar_ladder.py -v`
Expected: PASS. Also re-run any existing `invoice_with_attachment` test (search `grep -rl "invoice_with_attachment" tests/`) to confirm a genuine attachment case (no matching `N OF M` sequence across pages) still classifies correctly.

- [ ] **Step 6: Verify against the real 2 documents**

```bash
python3 -m docintel.cli process --json "all-docs/second-samples/edco/_AP Invoice 823283AUG25     Edco Waste & Recycling Services Inc. 3267.54000.pdf" --vision cassette
```
Repeat for `823283SEP25`. Confirm `doc_type` is no longer `invoice_with_attachment` and the Edco persona now extracts a normal field set (not zero).

- [ ] **Step 7: Run full verification and commit**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold --json
git add src/docintel/packs/northstar/ladder.py tests/packs/test_northstar_ladder.py
git commit -m "fix(packs): recognize paginated multi-page invoices via their own N-of-M footer"
```

---

### Task 6: Add U-Pak's `bill_to_name` selector

**Evidence:** the real gold PDF (`docs/CANADIAN WITHOUT NOTES U- PAK 4378107 (1).pdf`) prints `Bill To:` at `(top=135.7, x0=90.0)` and the value `NORTHSTAR RECYCLING COMPANY LLC` at `(top=169.2, x0=90.0)` — 33.5pt below, exactly left-aligned. This is the same label-above-value shape as Lumen's already-shipped, working selector (`{"field": "bill_to_name", "region": "near-anchor", "anchor": "Name", "pattern": "text"}`), and `regions.py:67-70` documents this exact page (`Northstar Recycling Company, LLC` under `Bill To`) as the reason `NEAR_ANCHOR_LEFT` was widened from strict left-alignment to a 12pt tolerance — this geometry has already been measured and tuned against, just never wired into a selector.

**Files:**
- Modify: `src/docintel/packs/northstar/personas/upak.json` (add a new selector to `field_selectors`)
- Test: `tests/packs/test_upak_bill_to_name.py` (new)

**Interfaces:**
- Consumes: `docintel.grammar.regions.RESOLVERS["near-anchor"]` (existing).
- Produces: `derived.bill_to_name` via `resolve_bill_to_alias`'s printed rung (`grammar/ops/infer.py:251-265`), enabling `bill_to_mismatch` to structurally fire for U-Pak for the first time.

- [ ] **Step 1: Write the failing test**

```python
"""U-Pak is one of the 5 personas with no bill_to_name selector at all
(STATUS-SUMMARY.md §4.1), so `bill_to_mismatch` can never fire regardless of
who a document is billed to. The real gold PDF prints `Bill To:` directly
above the customer name, left-aligned - the same shape Lumen's shipped,
working `bill_to_name` selector already handles."""

from __future__ import annotations

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs

WIDTH = 612.0
HEIGHT = 792.0


def _upak_bill_to_name_selector() -> dict:
    for pack in load_packs():
        if pack.name != "northstar":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint") == "northstar|upak":
                for selector in persona["field_selectors"]:
                    if selector.get("field") == "bill_to_name":
                        return selector
    raise AssertionError("northstar|upak persona (or its bill_to_name selector) not found")


def _bill_to_page(company: str) -> PageText:
    words = [
        Word(text="Bill", x0=90.0, y0=135.7, x1=104.6, y1=145.7),
        Word(text="To:", x0=104.6, y0=135.7, x1=118.0, y1=145.7),
        *[
            Word(text=tok, x0=90.0 + i * 60.0, y0=169.2, x1=90.0 + i * 60.0 + 55.0, y1=179.2)
            for i, tok in enumerate(company.split())
        ],
    ]
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def _ctx(page: PageText) -> JobContext:
    meta = (
        PageMeta(page_number=1, char_count=sum(len(w.text) for w in page.words),
                 image_count=0, annot_count=0, role="primary"),
    )
    return JobContext(document_id="d1", source_path="x.pdf", pages=(page,), page_meta=meta,
                       doc_type="standard_invoice")


def _extract_bill_to_name(company: str) -> str | None:
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_upak_bill_to_name_selector()],
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(_bill_to_page(company)))
    return ctx.extracted.get("bill_to_name")


def test_reads_the_printed_bill_to_name() -> None:
    assert _extract_bill_to_name("NORTHSTAR RECYCLING COMPANY LLC") == "NORTHSTAR RECYCLING COMPANY LLC"


def test_reads_a_different_printed_bill_to_name() -> None:
    """The whole point: a name that is NOT on the roster must still be read,
    or bill_to_mismatch can never fire."""
    assert _extract_bill_to_name("SOME OTHER COMPANY LLC") == "SOME OTHER COMPANY LLC"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/packs/test_upak_bill_to_name.py -v`
Expected: FAIL with `AssertionError: northstar|upak persona (or its bill_to_name selector) not found` — no such selector exists yet.

- [ ] **Step 3: Add the selector**

In `src/docintel/packs/northstar/personas/upak.json`, add to `field_selectors`:
```json
{
  "field": "bill_to_name",
  "anchor": "Bill To",
  "region": "near-anchor",
  "pattern": "text",
  "required": false
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/packs/test_upak_bill_to_name.py -v`
Expected: PASS. If `pattern: "text"` returns only the first word (`"NORTHSTAR"`) instead of the full line, check `patterns.py`'s `text` pattern definition and consider `"text_block"` with `"adjust": ["join_lines_comma"]` instead — but verify against the real PDF first (Step 6), since `text_block` is designed for multi-line addresses and may pull in the two address lines below the company name as well, which is wrong for a name field.

- [ ] **Step 5: Verify against the real gold PDF and second samples**

```bash
python3 -m docintel.cli replay-gold --json
```
Confirm `northstar-upak-4378107`'s `fields.bill_to_name` now extracts `"NORTHSTAR RECYCLING COMPANY LLC"`. Then run all 12 real U-Pak second samples and confirm none regress and `bill_to_mismatch` is now structurally capable of firing (even if it doesn't fire on any of these 12, since they're presumably all correctly addressed).

- [ ] **Step 6: Run full verification and commit**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold --json
git add src/docintel/packs/northstar/personas/upak.json tests/packs/test_upak_bill_to_name.py
git commit -m "feat(packs): add U-Pak bill_to_name selector, enabling the wrong-inbox guard"
```

---

### Task 7: Add Comcast's `bill_to_name` selector

**Evidence:** the real sample (`docs/persona-regeneration/08-comcast/document.pdf`) prints the customer name (`CLYDE ADMINISTRATION SERVI[CE]`) at `(top=84.0, x0=35.0)` with **no adjacent label at all** — but also with nothing else competing for the same box: Comcast's own logo/letterhead is graphical (produces no extracted words), and every other page-1 word above row 84 sits in the right column (`x0 >= 317`). Page width is 612pt (confirm at implementation time), so the customer name sits well inside the existing `top-left` region (`x < 204`, `y < 264`), which returns it as the region's only, and therefore first, `text` candidate. `top-left` region-only quality (`QUALITY_REGION_ONLY = 0.90`) exactly meets `bill_to_name`'s own 0.90 threshold (`thresholds.py`), so this does not need an anchor to clear the gate.

**Files:**
- Modify: `src/docintel/packs/digitaldirection/personas/comcast.json`
- Test: `tests/packs/test_comcast_bill_to_name.py` (new)

**Interfaces:**
- Consumes: `docintel.grammar.regions.RESOLVERS["top-left"]` (existing).
- Produces: `derived.bill_to_name` for Comcast.

- [ ] **Step 1: Write the failing test**

```python
"""Comcast is one of the 5 personas with no bill_to_name selector. Unlike
Edco/Veritiv, its own letterhead is graphical (no extracted words compete for
the top-left box), so a region-only match cleanly isolates the customer name
- confirmed by reading the real sample's page-1 word coordinates: nothing
else populates x<204,y<264 before the customer name's own row."""

from __future__ import annotations

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs

WIDTH = 612.0
HEIGHT = 792.0


def _comcast_bill_to_name_selector() -> dict:
    for pack in load_packs():
        if pack.name != "digitaldirection":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint", "").endswith("|comcast"):
                for selector in persona["field_selectors"]:
                    if selector.get("field") == "bill_to_name":
                        return selector
    raise AssertionError("comcast persona (or its bill_to_name selector) not found")


def _comcast_page(customer: str) -> PageText:
    words = [
        Word(text="Bill", x0=318.1, y0=15.9, x1=330.0, y1=25.9),  # right column - must not bleed in
        *[
            Word(text=tok, x0=35.0 + i * 70.0, y0=84.0, x1=35.0 + i * 70.0 + 65.0, y1=94.0)
            for i, tok in enumerate(customer.split())
        ],
        Word(text="Account", x0=35.0, y0=111.6, x1=71.8, y1=121.6),
    ]
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def _ctx(page: PageText) -> JobContext:
    meta = (
        PageMeta(page_number=1, char_count=sum(len(w.text) for w in page.words),
                 image_count=0, annot_count=0, role="primary"),
    )
    return JobContext(document_id="d1", source_path="x.pdf", pages=(page,), page_meta=meta,
                       doc_type="standard_invoice")


def _extract_bill_to_name(customer: str) -> str | None:
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_comcast_bill_to_name_selector()],
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(_comcast_page(customer)))
    return ctx.extracted.get("bill_to_name")


def test_reads_the_customer_name_from_the_top_left_box() -> None:
    assert _extract_bill_to_name("CLYDE ADMINISTRATION") == "CLYDE ADMINISTRATION"


def test_does_not_bleed_in_the_right_column() -> None:
    assert _extract_bill_to_name("CLYDE ADMINISTRATION") != "Bill"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/packs/test_comcast_bill_to_name.py -v`
Expected: FAIL — no `bill_to_name` selector exists.

- [ ] **Step 3: Add the selector**

In `src/docintel/packs/digitaldirection/personas/comcast.json`, add to `field_selectors`:
```json
{
  "field": "bill_to_name",
  "region": "top-left",
  "pattern": "text",
  "required": false
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/packs/test_comcast_bill_to_name.py -v`
Expected: PASS. If `pattern: "text"` against `top-left`'s whole-box span returns something other than the first line (e.g. concatenates all text in the box, or picks a later line), read `_candidates`' actual ordering for a region with no anchor before adjusting — the fix is almost certainly in how the selector's `pattern` is scoped, not in `top-left` itself, since `top-left` is shared by other working selectors.

- [ ] **Step 5: Verify against the real sample**

```bash
python3 -m docintel.cli process --json docs/persona-regeneration/08-comcast/document.pdf --vision cassette
```
Confirm `bill_to_name` extracts `"CLYDE ADMINISTRATION SERVI..."` (whatever the untruncated real text is — read it directly from the PDF, don't guess) with region-only quality (0.90), and that this doesn't regress `bill_to_address`'s existing extraction (they read different, non-overlapping parts of the page). Also run this against the original gold Comcast document and any other real Comcast samples if more exist.

- [ ] **Step 6: Run full verification and commit**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold --json
git add src/docintel/packs/digitaldirection/personas/comcast.json tests/packs/test_comcast_bill_to_name.py
git commit -m "feat(packs): add Comcast bill_to_name selector via the top-left region"
```

---

### Task 8: Investigate `bill_to_name` for Windstream, Edco, and Veritiv — no clean existing anchor found

**This task is a spike, not a guaranteed fix.** Unlike U-Pak (Task 6, real `Bill To:` label) and Comcast (Task 7, isolated top-left box), direct investigation of the real PDFs for these three vendors found **no usable existing region/anchor combination**:

- **Edco** (`all-docs/second-samples/edco/_AP Invoice 27267AUG25 ...pdf`): customer name (`NORTHSTAR RECYCLING`, `x0=62.5, top=164.9`) has no adjacent label, and Edco's own letterhead text (`x0=51.2, top=33.3`) sits in the *same* `top-left` box, so a region-only match would return the wrong (vendor's own) name first.
- **Veritiv** (`.../689-37578305 ...pdf`): same shape — `NORTHSTAR RECYCLING COMPANY LLC` at `x0=90, top=169.2` has no label, and Veritiv's own header (`x0=63.0, top=92.7`) sits in the same box.
- **Windstream** (`docs/persona-regeneration/09-windstream/document.pdf`): customer name (`CHOCTAW TRAVEL MART`, `x0=327.6, top=127.1`) falls in the `top-center` band, but a label row (`Account number / Telephone number / Invoice date`, `top=48.3`, same x-band) sits above it in the same box, so `top-center` would return the wrong line first.

All three share one shape: **the value sits below unrelated competing text in every existing geometric region, and above (not below) the nearest candidate label where one exists at all** (e.g. Windstream's own `ATTN:` at `x0=39.6, top=602.5` is not even in the same column as the customer name). `near-anchor` only searches right-of/below an anchor; there is no "above-anchor" primitive in the current closed region vocabulary (`docs/architecture/selector-grammar.md` §2, `tests/grammar/test_regions.py::test_all_fifteen_regions_exist`).

**Files:**
- Investigate: `all-docs/second-samples/{edco,veritiv,windstream}/*.pdf` (read real word coordinates with `pdfplumber`, the same method used to gather the evidence above)
- Conditionally modify: `src/docintel/grammar/regions.py`, `docs/architecture/selector-grammar.md`, `tests/grammar/test_regions.py::test_all_fifteen_regions_exist`, plus whichever of `edco.json` / `veritiv.json` / `windstream.json` turn out to have a workable layout
- Test: `tests/grammar/test_regions.py` (new resolver tests, if the stretch option is taken) + `tests/packs/test_{edco,veritiv,windstream}_bill_to_name.py` (new)

**Interfaces:**
- Consumes: whatever new or existing region resolver the investigation lands on.
- Produces: `derived.bill_to_name` for the remaining 3 of the original 5 gap vendors.

- [ ] **Step 1: Confirm the investigation's premise before building anything**

For each of the 3 vendors, dump full page-1 word coordinates from a real sample (`pdfplumber`, as used to gather the evidence above) and confirm: (a) no existing region resolver in `regions.py`'s `RESOLVERS` dict cleanly isolates the value, and (b) whether a genuine textual anchor exists ABOVE the value (which `near-anchor` cannot reach) or none exists at all. Do not skip this re-check — the evidence above was gathered against one sample per vendor; a second sample may have a cleaner layout, in which case skip straight to a Task 6/7-style fix for that vendor.

- [ ] **Step 2: If an above-anchor case exists (Windstream, if a same-column label is found on a second sample) — write the failing test for a new `above-anchor` region**

```python
"""No vendor currently needs a region that reaches ABOVE its anchor -
near-anchor only searches right/below. If Step 1 confirms a genuine
same-column label sits below the target value for one of these 3 vendors,
this is the mirror-image primitive: same x-bounds as near-anchor, but the y
range extends UP from the anchor's own line instead of down."""

from docintel.grammar.regions import resolve
# construct a page with a label BELOW a value in the same column, in the same
# style as test_near_anchor_is_300pt_right_and_40pt_below in this file, and
# assert resolve("above-anchor")(...) returns a span containing the value
# above it and NOT the label's own line.
```

Run it, confirm it fails (`above-anchor` is not a known region), before touching `regions.py`.

- [ ] **Step 3: If Step 2 applies, implement `above-anchor` as the mirror of `_near_anchor`**

In `src/docintel/grammar/regions.py`, add near `_near_anchor` (`regions.py:512-524`):
```python
def _above_anchor(
    pages: tuple[PageText, ...], meta: tuple[PageMeta, ...], anchor: Anchor | None
) -> tuple[Span, ...]:
    """Mirror of `_near_anchor`: same x-bounds, but the y range extends UP from
    the anchor's own line rather than down. For a value printed above its own
    label - a customer name repeated in a remittance stub above an `ATTN:`
    line, for instance - where every other anchor-relative region searches the
    wrong direction."""
    a = _require(anchor, "above-anchor")
    page = _page_of(pages, a)
    if page is None:
        return ()
    pitch = _pitch(page)
    bottom = a.word.y0 + page.line_tolerance
    x0 = a.word.x0 - NEAR_ANCHOR_LEFT
    x1 = a.word.x0 + _scaled(NEAR_ANCHOR_RIGHT, NEAR_ANCHOR_RIGHT_PITCHES, pitch)
    top = max(0.0, a.word.y0 - _scaled(NEAR_ANCHOR_BELOW, NEAR_ANCHOR_BELOW_PITCHES, pitch))
    return (_box(page, x0, top, x1, bottom),)
```
Register it in `RESOLVERS` (near `"near-anchor": _near_anchor,`):
```python
    "above-anchor": _above_anchor,
```

- [ ] **Step 4: Update the closed-vocabulary spec and its enforcing test**

This is a spec change — **stop and confirm with the user before this step**, per this plan's Global Constraints. If confirmed:
- Add a row to `docs/architecture/selector-grammar.md`'s §2 table (after `near-anchor`): `| \`above-anchor\` | within 300pt right of / 40pt above the anchor |`
- Update `tests/grammar/test_regions.py::test_all_fifteen_regions_exist` to include `"above-anchor"` in the asserted set.

- [ ] **Step 5: Run the region-level test, then write and run the vendor-level selector test(s)**

Follow the exact structure of Task 6/7's test files for whichever of the 3 vendors Step 1 found a workable anchor for.

- [ ] **Step 6: For any vendor where Step 1 finds NO usable anchor at all (the Edco/Veritiv case measured above — value with no label, competing text in every geometric box)**

Do not force a selector. Document the finding in the commit message and leave `bill_to_name` absent for that vendor, same as the existing, deliberate precedent in this codebase (`upak.json`'s own notes: *"delete the selector rather than ship one that restates its own answer"*). Flag it back to the user as a design question: whether a business-supplied roster of expected customer names per Edco/Veritiv account, matched against a wider unstructured page-text search, is an acceptable lower-rigor guard for these two — that is a scope decision, not an engineering one.

- [ ] **Step 7: Run full verification and commit whatever was actually built**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold --json
git add -A  # only the files actually touched in Steps 3-6
git commit -m "feat(packs): add bill_to_name for <vendors resolved> and document the <vendors not resolved> gap"
```

---

### Task 9: Redact leaked gold answers and rerun all 10 blind persona-regeneration sessions

**Evidence:** confirmed by direct read, not just the earlier sub-agent's report. `src/docintel/grammar/ops/derive.py:1-29`'s module docstring contains a worked table with exact gold totals for Centracom, EDCO, Comcast, Lumen, and Windstream. `src/docintel/grammar/ops/crosscheck.py:52-62` names the exact filenames and values that reveal EDCO's account/payable and Centracom's account number in a code comment. `docs/persona-regeneration/reference/selector-grammar.md:132,138` — the supposedly-redacted reference copy — still contains DTSS's and Veritiv's real invoice dates and postal codes as pattern-table examples. Every one of the 9 vendor instruction sets points at `src/docintel/grammar/` as required reading, so this isn't confined to the `reference/` copies the redaction pass already covered.

**Files:**
- Modify: `src/docintel/grammar/ops/derive.py`, `crosscheck.py`, `base.py`, `patterns.py`, `schema.py`, `regions.py`, `executor.py` (generalize worked examples/docstrings that currently cite real corpus values)
- Modify: `docs/persona-regeneration/reference/selector-grammar.md`, `docs/persona-regeneration/reference/pack-northstar.md`
- No test — this is a documentation/comment redaction task with a manual re-verification step, not code behavior. Do not skip the re-verification step in place of a test.

**Interfaces:** none — no runtime behavior changes. This task must not alter any function signature, regex, or constant value; only prose (docstrings/comments) and the `reference/` markdown files.

- [ ] **Step 1: Enumerate every leak with a fresh grep pass before editing anything**

```bash
grep -rn "20123.80\|13752.60\|33876.40\|298.34\|69.62\|221.11\|248.09\|1230.14" src/docintel/grammar/
grep -rn "77087\|0384043574\|4608.45\|805.54\|QXH7QKM7\|8495444620365242\|4378107\|1177.70\|481.20\|500 North Defiance Trail\|Spencerville" src/docintel/grammar/
grep -rn "9/15/2025\|08/14/2025\|45887\|01028-2744\|2469435\|2469427" docs/persona-regeneration/reference/
```
Confirm this matches (or, if the real files have changed since this plan was written, supersedes) the list in this task's evidence section. Treat any NEW hit this pass finds as in-scope too.

- [ ] **Step 2: Rewrite each leaking docstring/comment to make the same engineering point without a real corpus value**

For `derive.py`'s worked table specifically — replace the real vendor rows with synthetic values that still demonstrate the `gross`/`net_of_payments` distinction the docstring is teaching, e.g.:
```
ExampleVendorA   1000.00 +  200.00 ==  1200.00   (net_of_payments)
ExampleVendorB    100.00 +   50.00 ==   150.00   (gross, no payment)
```
Apply the same principle file-by-file: keep the didactic point (what the rule does and why), replace the specific number/filename/address with a clearly-synthetic placeholder that cannot be mistaken for a real answer. Do not simply delete the examples — they're load-bearing documentation for engineers reading this code, and the task's own evidence found they materially help explain non-obvious rules (F1, F8, F14).

- [ ] **Step 3: Fix the `reference/` markdown files specifically flagged as under-redacted**

In `docs/persona-regeneration/reference/selector-grammar.md`, replace the `date` and `postal_code` pattern-table example values (`9/15/2025`, `08/14/2025`, `45887`, `01028-2744`) with synthetic dates/zips that are not any corpus vendor's real printed value. In `docs/persona-regeneration/reference/pack-northstar.md:173`, replace the literal `reference_list` values (`2469435`, `2469427`) copied from `src/docintel/packs/northstar/references.py:16` with synthetic placeholders, and confirm no other section of this file was copied verbatim from a real pack module without going through the same redaction pass the file's own intent implies.

- [ ] **Step 4: Re-run the grep from Step 1 to confirm zero hits**

```bash
grep -rn "20123.80\|13752.60\|33876.40\|298.34\|69.62\|221.11\|248.09\|1230.14" src/docintel/grammar/
grep -rn "77087\|0384043574\|4608.45\|805.54\|QXH7QKM7\|8495444620365242\|4378107\|1177.70\|481.20\|500 North Defiance Trail\|Spencerville" src/docintel/grammar/
grep -rn "9/15/2025\|08/14/2025\|45887\|01028-2744\|2469435\|2469427" docs/persona-regeneration/reference/
```
Expected: no output from any of the three commands.

- [ ] **Step 5: Run the full test suite to confirm nothing broke**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests
```
Expected: identical pass/fail counts to before this task — a pure-comment change should not move a single test.

- [ ] **Step 6: Commit the redaction on its own**

```bash
git add src/docintel/grammar/ docs/persona-regeneration/reference/
git commit -m "fix(docs): redact leaked gold values from grammar source comments and blind-test reference material"
```

- [ ] **Step 7: Flag the contaminated blind runs to the user before re-running them**

The 10 blind persona-regeneration sessions (`docs/persona-regeneration/{01-dtss,...,10-lumen}/`) — including the already-scored DTSS run (17/19) and the 9 untracked `persona.json` files already sitting in this repo — were all produced against the pre-redaction material. **Confirm with the user whether to discard and re-run all 10** (the correct move if the DTSS 17/19 figure is going to be cited anywhere as evidence about blind-authoring quality) or to leave the historical runs as-is and only trust runs started after this task's commit. This is a scope/cost decision (10 fresh agent sessions), not a mechanical one — do not re-run them without confirmation.

---

### Task 10: Fix 3 concrete address-field failures, and set up the repeatable process for the rest

**Address fields (`remit_address`, `bill_to_address`, `vendor_address`) are 13 of 50 current field-level failures — by far the largest single category (STATUS-SUMMARY §4.4, reconfirmed fresh 2026-08-05).** This task fixes the 3 failures with a concrete, page-verified root cause found during verification, and establishes the process (read the real PDF, don't guess a regex blind — the same discipline every other selector fix in this plan follows) for the remaining 10, which are out of this plan's scope to pre-solve blind.

**Files:**
- Modify: `src/docintel/packs/digitaldirection/personas/comcast.json` (`remit_address`)
- Modify: `src/docintel/packs/northstar/personas/upak.json` (`bill_to_address`)
- Modify: whichever pack owns Federal Recycling (`grep -rl "federal.recycling\|federal_recycling" src/docintel/packs/*/personas/` to confirm the exact file — not yet identified in this plan) (`vendor_address`, `remit_address`, `bill_to_address`)
- Test: `tests/packs/test_comcast_remit_address.py`, `tests/packs/test_upak_bill_to_address.py`, `tests/packs/test_federal_recycling_addresses.py` (new)

**Interfaces:**
- Consumes: existing region resolvers only (this task does not require Task 8's stretch primitive) — confirm this while reading each real PDF; if a genuinely new capability turns out to be needed, stop and fold that specific field into Task 8 instead of improvising a workaround here.

- [ ] **Step 1: Comcast `remit_address` — read the real gap**

Gold: `"PO Box 60533, City of Industry, CA 91716-0533"`, currently extracted: `None`. Verified present verbatim in `docs/Comcast_8495 44 462 0365242_12092025_BILL.pdf` page 1, directly under the `COMCAST` word. Dump word coordinates for that exact region (same method as every prior task) to find what anchor or region should, but currently doesn't, reach it — check whether `comcast.json` already has a `remit_payee` selector (confirmed earlier in this investigation: `anchor: "Make checks payable to"`) whose region could be reused or extended for the address immediately following it.

- [ ] **Step 2: Write the failing test, fix the selector, verify against the real PDF — same TDD structure as Tasks 2/3/6/7**

Follow the exact pattern: synthetic fixture built from the real coordinates found in Step 1, failing test, persona edit, passing test, then `python3 -m docintel.cli replay-gold --json` confirming `digitaldirection-comcast-8495444620365242`'s `fields.remit_address` assertion now passes with no other regression.

- [ ] **Step 3: U-Pak `bill_to_address` — read the real gap**

Gold: `"94 Maple St, East Longmeadow, MA 01028"`, currently extracted: `"LLC, 94 MAPLE ST"` (picked up a trailing "LLC" fragment from the company-name line above, dropped city/state/zip). This is the same `Bill To:` block Task 6 already located (`top=169.2-193.2, x0=90`) — the bug is almost certainly the `bill_to_address` selector's region boundary bleeding into the company-name line and stopping before the city/state/zip line. Read the exact current selector (if one exists — `grep -n "bill_to_address" src/docintel/packs/northstar/personas/upak.json`; earlier investigation in this session found none, meaning this may actually be an add, not a fix — confirm before writing the test).

- [ ] **Step 4: Write the failing test, fix/add the selector, verify against the real PDF**

Same TDD structure as Step 2, targeting `NORTHSTAR RECYCLING COMPANY LLC / 94 MAPLE ST / EAST LONGMEADOW MA 01028` (the two address lines below the company name, joined via `adjust: ["join_lines_comma"]` the way every other multi-line address selector in this codebase already does) while excluding the company name itself.

- [ ] **Step 5: Federal Recycling — read the real gap**

`vendor_address` and `remit_address` both extract `None`; `bill_to_address` truncates mid-string (`"PO Box 188, East Longmeadow, MA 01"`, missing `"028, UNITED STATES"`). First confirm which pack/persona file owns Federal Recycling (`grep -rl "federal" src/docintel/packs/*/personas/`), then read the real source PDF (`docs/*Federal Recycling*.pdf` or `docs/corpus/gold/northstar-federal-recycling-1330123.json`'s referenced source) the same way as every prior task. The truncation on `bill_to_address` specifically suggests a region right-boundary or `LABEL_BLOCK_RIGHT`-style cutoff — check whether this document's line pitch or column width falls outside what the region's constants were tuned against, the same class of issue Task 1 in `docs/STATUS-SUMMARY.md` §4.5 already fixed for other constants.

- [ ] **Step 6: Write the failing tests, fix the 3 selectors, verify against the real PDF**

Same TDD structure. Note Federal Recycling is one of the 3 vendors with **zero second-period samples** (Task 11 below) — verification here is necessarily against the single gold document only; flag in the commit message that this fix is unconfirmed against any second sample and should be re-checked once one arrives.

- [ ] **Step 7: Run full verification and commit**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold --json
git add <files touched in Steps 1-6>
git commit -m "fix(packs): fix remit_address (Comcast), bill_to_address (U-Pak), and 3 address fields (Federal Recycling)"
```

- [ ] **Step 8: Document the process for the remaining 10 address failures as a follow-up, not part of this plan**

The remaining ~10 address-field failures (13 total minus the 3 fixed here) were not individually root-caused during this plan's verification pass — fixing them blind would repeat the exact mistake this codebase's own history explicitly warns against (`docs/superpowers/plans/2026-07-29-...`'s recurring instruction: "read what's actually printed... don't guess a regex blind"). Recommend a follow-up plan, scoped the same way Tasks 1-10 here were: read each real PDF, confirm the root cause, then fix — not a blanket "improve address extraction" task.

---

### Task 11 (non-engineering): Request second-period samples for the 3 vendors with none

**Confirmed:** `centracom`, `comcast`, `federal_recycling` have zero second-period documents anywhere in the repo — every other vendor's fixes in this plan (Tasks 1-10) were verifiable against real second-sample data; these 3 could only be checked against their single original gold document.

- [ ] Communicate to the business stakeholder who supplied `all-docs/second-samples/` for the other 7 vendors: request a second invoice/bill period for `centracom`, `comcast`, and `federal_recycling`, matching the ask already on record in `docs/STATUS-SUMMARY.md` §6. Not a code change — no commit for this item.

---

## Self-Review

**Spec coverage** — mapped against the 7 verified findings from this session's investigation:
1. Edco/Veritiv never auto-approve → Tasks 1, 2 (both root causes: Edco's unreachable threshold, Veritiv's un-anchored field). The `arith_balance_mismatch`-forced review lane is confirmed-correct behavior shared with U-Pak, not a bug — deliberately not "fixed" by this plan.
2. U-Pak $6,621 wrong-amount bug → Task 3.
3. Five vendors can't catch a wrong-inbox invoice → Tasks 6, 7, 8 (2 of 5 solved outright, 3 investigated with one likely solvable and 2 flagged as a genuine open design question).
4. 4 of 28 real Edco invoices invisible → Tasks 4, 5 (turned out to be 6 of 28 across two distinct root causes, both covered).
5. Address fields are the biggest accuracy gap → Task 10 (3 of 13 concrete failures fixed; remaining 10 explicitly scoped out with a stated reason, not silently dropped).
6. 3 vendors with zero second samples → Task 11.
7. Leaked reference material → Task 9.

**Placeholder scan** — every task has real file paths, real line numbers, and real code (test fixtures built from actually-measured PDF coordinates, not invented ones). The two places this plan intentionally does NOT commit to a specific final code change — Task 8's Edco/Veritiv bill_to_name (Step 6, explicitly may end with "no selector, flagged to the user") and Task 10 Step 8 (the remaining 10 address failures) — are stated as genuine open engineering/business questions with a concrete reason and a concrete next step, not vague "handle edge cases" placeholders.

**Type/name consistency** — `_is_paginated_continuation`, `_above_anchor`, `_extract_with_quality` etc. are each defined once and referenced with the same name and signature everywhere they're used within their task.
