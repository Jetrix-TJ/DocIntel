# Classification Accuracy Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix ten confirmed classification/tagging defects found by running the real, previously-unlabeled `all-docs/second-samples/` corpus (111 documents, 7 vendors) through the pipeline and diffing pipeline output against manually-verified ground truth, and durably record the audit so it isn't lost.

**Architecture:** No new subsystems. Every fix is a small, targeted change inside the existing two-layer classification design (`s3_classify.py` → pack `claims()` → pack `ladder.py` `doc_type_for`/`tags_for`) or its page-role/derivation support code (`extract/pageroles.py`, `grammar/ops/derive.py`, persona JSON selectors). Each task is independently testable and independently revertable.

**Tech Stack:** Python 3.12, pytest, pdfplumber/pytesseract (local, offline — no Anthropic API calls needed for any of this; classification runs before the vision stage).

## Global Constraints

- Never guess a value that cannot be verified — this codebase's stated design principle (see `grammar/ops/derive.py`, `extract/pageroles.py` module docstrings). Every fix below either recognizes real printed text or falls back to an existing, already-tagged "this was inferred" signal (`page_role_fallback`, `review_flag`). Do not introduce a silent guess.
- Every fix must be verified against `docs/corpus/gold/*.json` (10 hand-labelled documents) with **zero regressions**: `python3 docs/corpus/validate_gold.py` and `python3 -m docintel.cli replay-gold` must both stay green (or improve) after every task.
- All real second-sample files referenced below live under `all-docs/second-samples/<vendor>/` and are checked into the repo already — no fixtures need to be created for manual verification, only for the unit tests (which use the existing synthetic-fixture conventions per test file).
- Run the full offline pipeline via `--vision fake` or `FakeVision()` — OCR is local `pytesseract`, never calls the Anthropic API, and classification (`s3`) runs before the vision stage (`s5b`), so this is free and safe for every task in this plan.
- Money arithmetic is `Decimal`, never `float` — follow existing convention in any touched file.
- Commit after every task (one task = one commit), per repo convention (see recent log: `fix(packs): ...`, `feat(grammar): ...`).

---

## File Structure

| File | Change |
|---|---|
| `src/docintel/packs/northstar/personas/edco.json` | Add `payments_credits` selector (Task 1) |
| `src/docintel/core/pagination.py` | **New.** Shared "N of M" pagination-footer detector, used by both a pack ladder and `extract/pageroles.py` (Tasks 2, 3) |
| `src/docintel/packs/northstar/ladder.py` | Refactor `_is_paginated_continuation` to use the new shared helper (Task 3); scope `_CREDIT_MEMO` to short lines (Task 4); add value-corroboration to `_AGING_HEADER`/`_TAX_LINE` (Task 6) |
| `src/docintel/extract/pageroles.py` | Fix tier-1 fallback preemption by a false-positive `GRAND TOTAL` match (Task 2); tier-2 continuation-aware fallback (Task 3); add `TOTAL CREDIT` to `_TOTALS_RE` (Task 5) |
| `src/docintel/extract/annotations.py` | Recalibrate flattened-annotation pixel thresholds (Task 7) |
| `src/docintel/packs/digitaldirection/ladder.py` | Fix `_has_promo_block` (Task 8); add `previous total` to `PRIOR_BALANCE_ANCHORS` (Task 9) |
| `src/docintel/packs/digitaldirection/aliases.py` | Add missing managed clients to `MANAGED_CLIENTS` (Task 10) |
| `docs/classification-audit-2026-08-06.md` | **New.** Durable record of the 111-document audit, findings, and before/after numbers (Tasks 0, 11) |

---

### Task 0: Save the classification audit as a permanent doc

**Files:**
- Create: `docs/classification-audit-2026-08-06.md`

**Interfaces:** None — documentation only.

- [ ] **Step 1: Write the audit doc**

Create `docs/classification-audit-2026-08-06.md`:

```markdown
# Classification accuracy audit — 2026-08-06

Ran the full pipeline (`--vision fake`, offline, no API cost) over all 111 real,
previously-unlabeled documents in `all-docs/second-samples/` (7 vendor folders,
no gold labels existed for any of them) and manually verified a stratified
sample of ~35 documents against the actual PDF content.

## Corpus inventory (second-samples, no gold labels before this audit)

| Vendor | Pack | Count | doc_type distribution (pipeline, before fixes) |
|---|---|---:|---|
| complete_beverage | northstar | 27 | invoice_with_attachment: 25, credit_memo: 1, unclaimed: 1 |
| dtss | northstar | 30 | standard_invoice: 29, invoice_with_attachment: 1 |
| edco | northstar | 28 | standard_invoice: 28 (17 review_flag) |
| lumen | digitaldirection | 2 | telecom_bill: 2 |
| u_pak | northstar | 12 | standard_invoice: 12 |
| veritiv | northstar | 7 | standard_invoice: 7 |
| windstream | digitaldirection | 5 | telecom_bill: 3, unclaimed: 2 |

## Headline: doc_type/pack assignment is fundamentally sound

Manual spot-check across DTSS, U-Pak, Veritiv, Lumen, and the 3 claimed
Windstream docs: 19/19 correct on doc_type and pack, including hard cases
(hand-annotated U-Pak invoices, invoice+attachment pairs, multi-brand telecom
bills). Complete Beverage's 100% `invoice_with_attachment` rate is also
correct — this vendor's real fulfillment process always ships invoice +
Certificate of Destruction (+ BOL, + sometimes a shipper material report).

## Ten confirmed defects (see plan `docs/superpowers/plans/2026-08-06-classification-accuracy-fixes.md`)

1. EDCO has no `payments_credits` selector, so same-cycle payments can't net
   against the carried balance → false `arith_balance_mismatch` review flags
   on 11/28 EDCO docs, including gold doc `northstar-edco-819387`.
2. `pageroles.assign`'s tier-1 fallback (built to rescue Windstream's
   split-anchor template) is silently preempted by a coincidental
   `GRAND TOTAL` match on an unrelated usage-detail page deep in a large
   document → complete unclaimed_document + zero extracted fields.
3. `pageroles.assign`'s tier-2 blind fallback picks page 1 even when a
   genuinely-continued multi-page invoice's charges line is on a later page →
   2/28 EDCO docs.
4. `_CREDIT_MEMO` in the Northstar ladder scans unrestricted text and fires on
   an invoice that merely *mentions* a credit memo in a note.
5. `_TOTALS_RE` has no `TOTAL CREDIT` pattern → a real credit-memo pair goes
   completely unclaimed.
6. `_AGING_HEADER`/`_TAX_LINE` match column *labels*, not the values beneath
   them → `past_due`/`has_tax` false positives on $0.00 buckets (U-Pak,
   Veritiv).
7. `has_flattened_annotations` (highlighter/annotation detector) cannot
   distinguish a printed zebra-striped table from real human markup → false
   positive on DTSS.
8. `_has_promo_block`'s `image_count>=2` heuristic misses a real full-page
   OCR'd ad (collapses to 1 image) and false-fires on ordinary native-PDF
   logo graphics.
9. `PRIOR_BALANCE_ANCHORS` is missing "previous total" → a real unresolved
   carryover balance on some Windstream templates gets no tag at all (a
   silent-overpayment risk, the same class of bug as F1).
10. `MANAGED_CLIENTS` roster is missing real clients (Golub Corporation, Tops
    Markets LLC) → every `bill_to_mismatch` firing in the sample traces back
    to this one gap.

## After-fix numbers

(Filled in by Task 11, after all fixes land — see that task for the
regenerated distribution table and gold-corpus regression results.)
```

- [ ] **Step 2: Commit**

```bash
git add docs/classification-audit-2026-08-06.md
git commit -m "docs: record the second-samples classification audit and its ten findings"
```

---

### Task 1: EDCO `payments_credits` selector (payment-netting bug)

**Files:**
- Modify: `src/docintel/packs/northstar/personas/edco.json`
- Test: `tests/packs/test_edco_payments_credits.py`

**Interfaces:**
- Consumes: `grammar.ops.derive.normalize_credit_sign`, `resolve_carried_balance`, `derive_amount_payable` (already implemented and already wired on EDCO's `total_printed` selector's `adjust` list — no changes needed there).
- Produces: `ctx.extracted["payments_credits"]` populated for EDCO documents, exactly like DTSS/Windstream/Comcast/Lumen/Centracom personas already do.

This is a precedented, low-risk fix: 5 of 6 shipped personas already have a
`payments_credits` selector (`dtss.json`, `windstream.json`, `comcast.json`,
`lumen.json`, `centracom.json`). EDCO is the only one missing it. The gold
doc `docs/corpus/gold/northstar-edco-819387.json` **already encodes the
expected value** (`"payments_credits": -3380.67`,
`"prior_balance_basis_note": "...offset by a same-statement PAYMENT --
THANK YOU of 3380.67..."`, `expected_routing.review_flag: false`) — this
selector is a documented gap, not new scope invented here. Confirmed on the
real PDF for `_AP Invoice 174921AUG25...pdf`: `BALANCE FORWARD 160.41`,
`PAYMENT -- THANK YOU 357.24`, `CURRENT CHARGES: 357.24`, printed total
`160.41` (`160.41 - 357.24 + 357.24 == 160.41`).

- [ ] **Step 1: Write the failing test**

Create `tests/packs/test_edco_payments_credits.py`, following the exact
fixture conventions already used in
`tests/packs/test_edco_total_printed_arithmetic.py` (read that file first —
it defines `_edco_selectors`, `_row`, `_ctx` helpers you should reuse):

```python
"""EDCO has no `payments_credits` selector, so `derive_amount_payable` can
never net a same-cycle payment against the carried balance and refuses with
a false `arith_balance_mismatch` on every EDCO account where one intervened
(measured: 11/28 real second-sample documents, including gold doc
`northstar-edco-819387`, whose gold label already records the expected
`payments_credits: -3380.67`).

Real account 174921AUG25: `BALANCE FORWARD 160.41`, `PAYMENT -- THANK YOU
357.24`, `CURRENT CHARGES: 357.24`, printed total `160.41`. Netting:
160.41 - 357.24 + 357.24 == 160.41.
"""

from __future__ import annotations

from decimal import Decimal

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs

WIDTH = 612.0
HEIGHT = 792.0


def _edco_selectors(*fields: str) -> list[dict]:
    for pack in load_packs():
        if pack.name != "northstar":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint") == "northstar|edco":
                by_field = {s.get("field"): s for s in persona["field_selectors"]}
                return [by_field[f] for f in fields if f in by_field]
    raise AssertionError("northstar|edco persona not found")


def _row(y: float, *cells: tuple[str, float]) -> list[Word]:
    return [
        Word(text=text, x0=x0, y0=y, x1=x0 + 7.0 * len(text), y1=y + 10.0)
        for text, x0 in cells
    ]


def _page(total_printed: str, prior_balance: str, payment: str, current_charges: str) -> PageText:
    words: list[Word] = []
    words += _row(100.0, (total_printed, 380.0))
    words += _row(519.0, ("BALANCE", 77.0), ("FORWARD", 126.0), (prior_balance, 540.0))
    words += _row(
        560.0,
        ("PAYMENT", 77.0), ("--", 140.0), ("THANK", 160.0), ("YOU", 210.0), (payment, 540.0),
    )
    words += _row(603.0, ("CURRENT", 77.0), ("CHARGES:", 129.0), (current_charges, 377.0))
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def _ctx(page: PageText) -> JobContext:
    meta = (
        PageMeta(page_number=1, char_count=sum(len(w.text) for w in page.words),
                 image_count=0, annot_count=0, role="primary"),
    )
    return JobContext(document_id="d1", source_path="x.pdf", pages=(page,), page_meta=meta,
                       doc_type="standard_invoice")


def test_edco_persona_has_a_payments_credits_selector() -> None:
    """The gap: before this fix, `_edco_selectors('payments_credits')` returns []."""
    selectors = _edco_selectors("payments_credits")
    assert len(selectors) == 1
    assert selectors[0]["pattern"] == "currency"
    assert "normalize_credit_sign" in selectors[0].get("adjust", [])


def test_edco_payment_is_extracted_and_sign_normalized() -> None:
    """Real account 174921AUG25 shape: a same-cycle payment that must come out
    negative (`normalize_credit_sign`) so `resolve_carried_balance`'s `gross`
    formula (`prior_balance + payments_credits`) nets it rather than doubling it."""
    persona = parse_persona({
        "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
        "rule_version": "v1", "status": "draft",
        "field_selectors": _edco_selectors(
            "total_printed", "prior_balance", "payments_credits", "current_charges"
        ),
        "layout_fingerprint": {},
    })
    page = _page(total_printed="160.41", prior_balance="160.41",
                 payment="357.24", current_charges="357.24")
    ctx = Executor(persona).apply(_ctx(page))
    assert ctx.extracted.get("payments_credits") == Decimal("-357.24")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/packs/test_edco_payments_credits.py -v`
Expected: FAIL on `test_edco_persona_has_a_payments_credits_selector` — `selectors == []`.

- [ ] **Step 3: Add the selector**

Edit `src/docintel/packs/northstar/personas/edco.json` — insert after the
existing `current_charges` selector (before `total_printed`), matching
`dtss.json`'s already-shipped shape:

```json
    {
      "field": "payments_credits",
      "anchor": "PAYMENT -- THANK YOU",
      "region": "near-anchor",
      "pattern": "currency",
      "required": false,
      "adjust": [
        "normalize_credit_sign"
      ]
    },
```

Also append one sentence to the persona's `"notes"` field recording that
`payments_credits` is now wired (this file's notes field is where every prior
EDCO decision is documented — follow that convention, do not remove any
existing note text).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/packs/test_edco_payments_credits.py -v`
Expected: PASS, both tests.

- [ ] **Step 5: Verify against the real gold doc and real second-samples**

Run: `python3 -m docintel.cli replay-gold --json | python3 -c "import json,sys; d=json.load(sys.stdin); print([doc for doc in d['documents'] if 'edco' in doc['gold_id']])"`
Expected: `northstar-edco-819387`'s `passed` is now `true` (was previously
failing on `payments_credits`/`review_flag`, per the F1-trap notes in
`docs/corpus/README.md`).

Then re-run the second-sample batch (see Task 11's script) filtered to EDCO
and confirm `174921AUG25`, `978979AUG25`, `835003MAR25`, `15570AUG25`,
`15570SEPT25`, `819387AUG25`, `819387SEP25`, `27267AUG25`, `66162AUG25`,
`704363AUG25`, `968397OCT25` no longer carry `arith_balance_mismatch`. (Note:
`968397OCT25` has an `INCREASE` line instead of a `PAYMENT` line in the same
column — if the `PAYMENT -- THANK YOU` anchor alone doesn't resolve it, that
is acceptable to leave as a remaining review flag; do not widen the anchor to
match `INCREASE` without reading that specific document's page first, since
"payments" and "increases" may have different arithmetic sign conventions.)

- [ ] **Step 6: Run full test suite for regressions**

Run: `pytest tests/ -q`
Expected: no new failures anywhere (in particular `tests/packs/test_edco_total_printed_arithmetic.py`, which locks in that `total_printed` itself must NOT change — this fix only adds `payments_credits`, it never touches the `total_printed` selector).

- [ ] **Step 7: Commit**

```bash
git add src/docintel/packs/northstar/personas/edco.json tests/packs/test_edco_payments_credits.py
git commit -m "fix(packs): EDCO nets same-cycle payments against the carried balance"
```

---

### Task 2: `pageroles` tier-1 fallback wrongly preempted by a coincidental `GRAND TOTAL` match

**Files:**
- Modify: `src/docintel/extract/pageroles.py:202-225`
- Test: `tests/extract/test_pageroles.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `assign()`'s return contract is unchanged (`(meta, used_last_resort)`).

Root cause (confirmed by direct reproduction against
`Windstream_2389882_08272025_BILL.pdf`, 472 pages): page 1 has a totals-only
line (`TOTAL INVOICE AMOUNT $116,258.78 remains unchanged.`, matches
`_TOTALS_RE`) but its identity label is split across two visual lines
(`Account Invoice Total` / `Number Date Amount Due`), so it never
independently qualifies as `primary` and depends on the tier-1 fallback
(`totals_only[0]`) to be picked. Page 145, a per-location usage-detail table,
coincidentally satisfies **both** signals on its own: `INVOICE NUMBER
77178223` (a routine running-header, matches `_ANCHOR_RE`) and `GRAND TOTAL
113 72.6 $2.6400` (a per-section call-usage subtotal row — three numbers, not
a label/value pair — matches `_TOTALS_RE`). Because `primary_idx` is
therefore non-empty (`{144}`), the `if not primary_idx:` branch that would
run the tier-1 fallback never executes, and page 1 loses primary status
entirely. `primary_text(ctx)` then reads only page 145's ~1KB of call-detail
rows, which contains zero occurrences of "windstream" — `DigitalDirectionPack.claims()` fails, and the document is completely unclaimed with zero fields extracted.

The fix: a `GRAND TOTAL` (or `TOTAL AMT`) match should not count as a
totals-block signal when the same short line also carries **other** numeric
tokens beyond the one money amount — a genuine totals cell is a label plus
exactly one money value; a per-section usage subtotal row is a label
followed by several plain numbers (call count, minutes) plus a money value.
This does not touch the seven unambiguous totals phrases
(`TOTAL AMOUNT DUE`, `PLEASE PAY`, `BALANCE DUE`, `BALANCE PAYABLE`,
`TOTAL DUE`, `NOW DUE`, `TOTAL INVOICE AMOUNT`), which never appear on
per-section subtotal rows in any corpus or second-sample document.

- [ ] **Step 1: Write the failing test**

Add to `tests/extract/test_pageroles.py`, using the file's existing `_page`/`_meta`
synthetic-fixture helpers (read the top of that file first for the exact
signatures — `_page(number, lines, source)` where `lines` is a list of
token-lists, one inner list per visual line):

```python
def test_totals_only_page_1_wins_over_a_usage_detail_page_with_a_coincidental_grand_total() -> None:
    """Reproduces the real Windstream_2389882 bug: page 1 has a totals-only
    line (split-anchor template, tier-1 candidate) but a later page has BOTH
    an anchor (routine running-header) and a `GRAND TOTAL` match that is
    really a per-section usage subtotal row (extra bare numeric tokens beside
    the money value, not a label/value pair). Before the fix, the later
    page's coincidental both-signal match makes `primary_idx` non-empty and
    tier-1 never runs, so page 1 loses primary status."""
    page1 = _page(1, [["TOTAL", "INVOICE", "AMOUNT", "$116,258.78"]])
    page2 = _page(2, [
        ["INVOICE", "NUMBER", "77178223"],
        ["GRAND", "TOTAL", "113", "72.6", "$2.6400"],
    ])
    meta, used_last_resort = pageroles.assign((page1, page2), _meta([page1, page2]))
    assert meta[0].role == "primary"
    assert used_last_resort is False


def test_grand_total_with_exactly_one_money_token_still_qualifies_as_primary() -> None:
    """Guard against over-correcting: a genuine `GRAND TOTAL $500.00` label/value
    line, alone with its own anchor, must still qualify a page as primary on
    its own (no fallback needed) — this is the ordinary case the regex exists
    to catch."""
    page = _page(1, [ANCHOR_LINE, ["GRAND", "TOTAL", "$500.00"]])
    meta, used_last_resort = pageroles.assign((page,), _meta([page]))
    assert meta[0].role == "primary"
    assert used_last_resort is False
```

(`ANCHOR_LINE` is already defined near the top of the file as
`["Account", "Number:", "12345"]` — reuse it, don't redefine it.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/extract/test_pageroles.py -v -k "grand_total"`
Expected: FAIL on `test_totals_only_page_1_wins...` — `meta[0].role` is `"supporting"`, not `"primary"`.

- [ ] **Step 3: Implement the fix**

In `src/docintel/extract/pageroles.py`, change `_page_signals` to reject a
`GRAND TOTAL`/`TOTAL AMT` match on a line carrying more than one numeric
token (the money amount plus anything else numeric), while leaving every
other phrase in `_TOTALS_RE` untouched:

```python
# Matched separately from the rest of _TOTALS_RE: "GRAND TOTAL" and "TOTAL
# AMT" are the only two phrases in the enumeration that also appear, in the
# wild, as a per-section usage/call-detail subtotal row rather than the
# document's own payable total (Windstream_2389882's page 145: "GRAND TOTAL
# 113 72.6 $2.6400" — a call count, a minute count, and a money value, not a
# label/value pair). The other seven phrases never appear in that shape in
# the corpus or second-samples, so they are matched unconditionally.
_AMBIGUOUS_TOTALS_RE = re.compile(r"\b(GRAND TOTAL|TOTAL AMT)\b")
_UNAMBIGUOUS_TOTALS_RE = re.compile(
    r"\b(TOTAL AMOUNT DUE|PLEASE PAY|BALANCE DUE|BALANCE PAYABLE|TOTAL DUE|"
    r"NOW DUE|TOTAL INVOICE AMOUNT|TOTAL CREDIT)\b"
)
_MONEY_TOKEN_RE = re.compile(r"^\$?\d[\d,]*\.\d{2}$")


def _line_is_totals_block(text: str, tokens: list[str]) -> bool:
    if _UNAMBIGUOUS_TOTALS_RE.search(text):
        return True
    if not _AMBIGUOUS_TOTALS_RE.search(text):
        return False
    # A genuine totals cell is a label plus exactly one money value. A
    # per-section usage subtotal row (Windstream's "GRAND TOTAL 113 72.6
    # $2.6400") carries extra bare numeric tokens beside the money amount.
    numeric_tokens = [t for t in tokens if re.fullmatch(r"[\d,.]+", t.strip("$"))]
    money_tokens = [t for t in numeric_tokens if _MONEY_TOKEN_RE.match(t)]
    return len(numeric_tokens) == len(money_tokens) == 1
```

Then update `_page_signals` to pass tokens through and call
`_line_is_totals_block` instead of `_TOTALS_RE.search(text)` directly:

```python
def _page_signals(page: PageText) -> tuple[bool, bool]:
    has_anchor = False
    has_totals = False
    for line in page.lines():
        n_words = len(line)
        tokens = [w.text for w in line]
        text: str | None = None
        if not has_anchor and n_words <= _MAX_ANCHOR_LINE_WORDS:
            text = " ".join(tokens).upper()
            if _ANCHOR_RE.search(text):
                has_anchor = True
        if not has_totals and n_words <= _MAX_TOTALS_LINE_WORDS:
            text = text or " ".join(tokens).upper()
            if _line_is_totals_block(text, tokens):
                has_totals = True
        if has_anchor and has_totals:
            break
    return has_anchor, has_totals
```

Remove the old combined `_TOTALS_RE` definition (superseded by
`_AMBIGUOUS_TOTALS_RE` + `_UNAMBIGUOUS_TOTALS_RE`) but keep every phrase from
it — `TOTAL CREDIT` is added here too (folds in Task 5; if Task 5 is done
first, don't duplicate the entry).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/extract/test_pageroles.py -v`
Expected: PASS, all tests in the file (including every pre-existing test — this
change must not alter behavior for any of the 10 gold documents' page-role
assignments).

- [ ] **Step 5: Verify against the real 472-page document**

```python
from docintel.extract.normalize import load_document
from docintel.extract import pageroles
pages, meta, text_source = load_document("all-docs/second-samples/windstream/Windstream_2389882_08272025_BILL.pdf")
new_meta, used_last_resort = pageroles.assign(pages, meta)
assert new_meta[0].role == "primary"
```
Then re-run this file through the full pipeline (`docintel.cli process ... --vision fake --json`) and confirm `sender_fingerprint` is no longer `unknown|unknown` and `confidence` is no longer `{}`.

- [ ] **Step 6: Full regression**

Run: `pytest tests/ -q && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold`
Expected: all green, no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/docintel/extract/pageroles.py tests/extract/test_pageroles.py
git commit -m "fix(extract): a per-section usage subtotal can no longer masquerade as a document's totals block"
```

---

### Task 3: Shared pagination-footer helper + `pageroles` tier-2 continuation-aware fallback

**Files:**
- Create: `src/docintel/core/pagination.py`
- Test: `tests/core/test_pagination.py`
- Modify: `src/docintel/packs/northstar/ladder.py:150-165` (refactor `_is_paginated_continuation` to use the shared helper — no behavior change)
- Modify: `src/docintel/extract/pageroles.py` (use the shared helper in the tier-2 fallback)
- Test: `tests/extract/test_pageroles.py`

**Interfaces:**
- Produces: `core.pagination.shared_footer_pages(pages: tuple[PageText, ...]) -> frozenset[int] | None` — the full 1-indexed page-number set if every page carries a matching `N OF M` footer with `M == len(pages)`, else `None`. Pure function, no `JobContext` dependency (unlike the existing pack-local version), so both `extract/` and `packs/` can depend on it without an import-direction problem (`core` is the layer both already depend on — see `packs/registry.py`'s own comment on this).
- Consumes (in `ladder.py`): the same function, called with `ctx.pages`.

Root cause (confirmed by reading real PDFs `_AP Invoice 823283AUG25...pdf`
and `...823283SEP25...pdf`): both are genuinely one continued invoice across
2 pages (footer `000000-001 MD9-M 1 OF 2` / `2 OF 2` on each page). EDCO's
totals-box labels render as non-text graphics, so **neither** page matches
`_ANCHOR_RE` or `_TOTALS_RE` at all (confirmed — no such label tokens
anywhere in the extracted word stream), so `assign` hits true tier-2
(`primary_idx = {0}`, blind page-1 pick). But `CURRENT CHARGES: 3267.54` is
only on page 2 — the `current_charges` selector, scoped to primary pages
only, never finds it, and `derive_amount_payable` refuses with "a balance is
carried forward but no current charges were found."

Widening `_TOTALS_RE`/`_ANCHOR_RE` won't help — there is no text to match
(confirmed: the labels are graphics, not text). And widening the enumeration
to include `CURRENT CHARGES` would reintroduce the exact false-positive this
file already deliberately guards against on Lumen/Windstream continuation
pages (see the `_TOTALS_RE` docstring: "Lumen page 3's 'Total Current
Charges'... Windstream page 3's 'Windstream Current Charges' section
header" — both must stay `supporting`).

The fix: when tier-2 fires (`used_last_resort` would be `True`) **and** every
page of the document carries a matching, self-consistent `N OF M` pagination
footer — proof, not a guess, that this is one continuous invoice rather than
an invoice-plus-attachment — mark **every** page in that footer sequence as
`primary`, not just page 1. This mirrors U-PAK's already-accepted pattern
(every page of a single coherent invoice can legitimately be primary) and
does not touch the anchor/totals regexes, so it carries zero risk to any
document that doesn't have a matching footer sequence.

- [ ] **Step 1: Write the failing test for the new shared helper**

Create `tests/core/test_pagination.py`:

```python
"""`shared_footer_pages`: a page-number set only when every page of the
document carries a matching, self-consistent `N OF M` footer — real evidence
that the pages are one continuous document, not a guess."""

from __future__ import annotations

from docintel.core.models import PageText, Word
from docintel.core.pagination import shared_footer_pages


def _page(number: int, footer: str | None) -> PageText:
    words: list[Word] = []
    if footer:
        for i, tok in enumerate(footer.split()):
            words.append(Word(text=tok, x0=10.0 + 40.0 * i, y0=700.0,
                               x1=45.0 + 40.0 * i, y1=710.0))
    return PageText(page_number=number, words=tuple(words), width=612.0, height=792.0, source="native")


def test_two_pages_with_matching_1_of_2_and_2_of_2_footers() -> None:
    pages = (_page(1, "000000-001 MD9-M 1 OF 2"), _page(2, "000000-001 MD9-M 2 OF 2"))
    assert shared_footer_pages(pages) == frozenset({1, 2})


def test_single_page_document_has_no_footer_sequence() -> None:
    assert shared_footer_pages((_page(1, "1 OF 1"),)) is None


def test_missing_footer_on_one_page_yields_none() -> None:
    pages = (_page(1, "1 OF 2"), _page(2, None))
    assert shared_footer_pages(pages) is None


def test_footer_total_not_matching_page_count_yields_none() -> None:
    """A stapled attachment prints its own, unrelated pagination — must not
    be mistaken for the invoice's own continuation sequence."""
    pages = (_page(1, "1 OF 3"), _page(2, "2 OF 3"))
    assert shared_footer_pages(pages) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_pagination.py -v`
Expected: FAIL — `docintel.core.pagination` does not exist yet.

- [ ] **Step 3: Implement the shared helper**

Create `src/docintel/core/pagination.py`:

```python
"""Shared "N OF M" pagination-footer detection.

Extracted from `packs/northstar/ladder.py`'s `_is_paginated_continuation`
(pack-local, `JobContext`-shaped) so `extract/pageroles.py` can use the same
proof of "these pages are one continuous document" without a `packs ->
extract` dependency inversion. `core` is the layer both `extract/` and
`packs/` already depend on (see `packs/registry.py`'s own note on this), so
this is the direction that cannot cycle.
"""

from __future__ import annotations

import re

from docintel.core.models import PageText

_PAGE_OF_RE = re.compile(r"\b(\d+)\s+OF\s+(\d+)\b")


def shared_footer_pages(pages: tuple[PageText, ...]) -> frozenset[int] | None:
    """The full 1-indexed page-number set if every page carries a footer
    matching `N OF M` with `M == len(pages)`, and the N's cover 1..len(pages)
    exactly once between them. `None` otherwise — including for a single-page
    document, where "continuation" is not a meaningful claim.
    """
    total_pages = len(pages)
    if total_pages < 2:
        return None
    seen_numbers: set[int] = set()
    for page in pages:
        found = False
        for line in page.lines():
            text = " ".join(w.text for w in line).upper()
            match = _PAGE_OF_RE.search(text)
            if match and int(match.group(2)) == total_pages:
                seen_numbers.add(int(match.group(1)))
                found = True
                break
        if not found:
            return None
    if seen_numbers != set(range(1, total_pages + 1)):
        return None
    return frozenset(seen_numbers)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_pagination.py -v`
Expected: PASS, all four tests.

- [ ] **Step 5: Refactor `ladder.py` to use the shared helper (no behavior change)**

In `src/docintel/packs/northstar/ladder.py`, replace the body of
`_is_paginated_continuation` (keep the function and its docstring/signature —
`doc_type_for` calls it as `not _is_paginated_continuation(ctx)`, do not
change that call site):

```python
def _is_paginated_continuation(ctx: JobContext) -> bool:
    """True if every page carries a `N OF M` footer with M == len(ctx.pages).
    ... (keep existing docstring)
    """
    return pagination.shared_footer_pages(ctx.pages) is not None
```

Add `from docintel.core import pagination` to the imports at the top of the
file. Delete the now-unused local `_PAGE_OF_RE` definition.

Run: `pytest tests/packs/test_northstar_ladder.py -v`
Expected: PASS — this is a pure refactor, every existing test for
`invoice_with_attachment`/`_is_paginated_continuation` must still pass
unchanged.

- [ ] **Step 6: Write the failing test for the `pageroles` tier-2 fix**

Add to `tests/extract/test_pageroles.py`:

```python
def test_tier_2_fallback_marks_every_page_of_a_proven_continuation_sequence_primary() -> None:
    """Reproduces the real EDCO 823283 bug: neither page carries any anchor
    or totals signal at all (true tier-2), but both pages share a matching
    `N OF 2` footer — real proof this is one continuous invoice, not a
    page-1-only guess. `CURRENT CHARGES:` (page 2 only) must become readable
    by primary-scoped selectors."""
    page1 = _page(1, [["BALANCE", "FORWARD", "3593.91"], ["MD9-M", "1", "OF", "2"]])
    page2 = _page(2, [["CURRENT", "CHARGES:", "3267.54"], ["MD9-M", "2", "OF", "2"]])
    meta, used_last_resort = pageroles.assign((page1, page2), _meta([page1, page2]))
    assert meta[0].role == "primary"
    assert meta[1].role == "primary"
    assert used_last_resort is True  # still a guess, still tagged — just a better-informed one


def test_tier_2_fallback_still_picks_page_1_alone_without_a_footer_sequence() -> None:
    """No regression: when there is no proven continuation sequence, tier-2
    behaves exactly as before — page 1 only."""
    page1 = _page(1, [["BALANCE", "FORWARD", "3593.91"]])
    page2 = _page(2, [["CURRENT", "CHARGES:", "3267.54"]])
    meta, used_last_resort = pageroles.assign((page1, page2), _meta([page1, page2]))
    assert meta[0].role == "primary"
    assert meta[1].role == "supporting"
    assert used_last_resort is True
```

- [ ] **Step 7: Run test to verify it fails**

Run: `pytest tests/extract/test_pageroles.py -v -k "tier_2_fallback"`
Expected: FAIL on the first test — `meta[1].role` is `"supporting"`, not `"primary"`.

- [ ] **Step 8: Implement the fix**

In `src/docintel/extract/pageroles.py`, add the import
`from docintel.core.pagination import shared_footer_pages` and change the
`else` branch of the tier-2 fallback in `assign`:

```python
        else:
            footer_pages = shared_footer_pages(pages)
            if footer_pages is not None:
                primary_idx = {i for i in range(len(pages)) if (i + 1) in footer_pages}
                used_last_resort = True
                logger.warning(
                    "pageroles: no page carried an identity anchor, a totals label, "
                    "or both; falling back to all %d pages, which share a proven "
                    "N-of-M pagination footer sequence",
                    len(footer_pages),
                )
            else:
                primary_idx = {0}
                used_last_resort = True
                logger.warning(
                    "pageroles: no page carried an identity anchor, a totals label, "
                    "or both; falling back to page 1 as a last resort so the "
                    "document still has a primary page"
                )
```

- [ ] **Step 9: Run test to verify it passes**

Run: `pytest tests/extract/test_pageroles.py -v`
Expected: PASS, all tests in the file.

- [ ] **Step 10: Verify against the real EDCO documents**

```python
from docintel.extract.normalize import load_document
from docintel.extract import pageroles
for f in ["_AP Invoice 823283AUG25     Edco Waste & Recycling Services Inc. 3267.54000.pdf",
          "_AP Invoice 823283SEP25     Edco Waste & Recycling Services Inc. 3619.00000.pdf"]:
    pages, meta, _ = load_document(f"all-docs/second-samples/edco/{f}")
    new_meta, _ = pageroles.assign(pages, meta)
    assert all(m.role == "primary" for m in new_meta)
```
Then re-run both through the full pipeline and confirm `current_charges` is
now extracted and `arith_balance_mismatch` no longer fires.

- [ ] **Step 11: Full regression**

Run: `pytest tests/ -q && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold`
Expected: all green.

- [ ] **Step 12: Commit**

```bash
git add src/docintel/core/pagination.py tests/core/test_pagination.py \
        src/docintel/packs/northstar/ladder.py \
        src/docintel/extract/pageroles.py tests/extract/test_pageroles.py
git commit -m "fix(extract): tier-2 page-role fallback trusts a proven N-of-M continuation sequence over a blind page-1 guess"
```

---

### Task 4: Scope `_CREDIT_MEMO` to short lines only (Northstar ladder)

**Files:**
- Modify: `src/docintel/packs/northstar/ladder.py:23-29, 118-120`
- Test: `tests/packs/test_northstar_ladder.py`

**Interfaces:** None — internal to `doc_type_for`.

Root cause: `doc_type_for` calls `_CREDIT_MEMO.search(text)` against the
**entire** `primary_text(ctx)` blob, unlike `_PAST_DUE`
(`_short_line_has(ctx, _PAST_DUE, _MAX_PAST_DUE_LINE_WORDS)`), which is
correctly scoped to short lines. Confirmed on real file `_AP Invoice 32593
Complete Beverage Destruction 556.20000.pdf`: page 1 plainly is an invoice
("BALANCE DUE $556.20", a "Pay invoice" button), but a line-item note reads
"For remaining credited items refer to Credit memo 32684." — a full
sentence, and `_CREDIT_MEMO` matches "credit memo" inside it, misclassifying
a real invoice as `credit_memo`.

- [ ] **Step 1: Write the failing test**

Add to `tests/packs/test_northstar_ladder.py`, using the file's existing
`_page`/`_ctx` helpers (`|` starts a new visual line):

```python
def test_credit_memo_mentioned_in_a_line_item_note_does_not_reclassify_a_real_invoice() -> None:
    """Real Complete Beverage bug: an invoice's line-item note reads 'For
    remaining credited items refer to Credit memo 32684.' — a full sentence,
    not a document title. Must not fire _CREDIT_MEMO."""
    ctx = _ctx(_page(
        "COMPLETE BEVERAGE DESTRUCTION|BALANCE DUE $556.20|"
        "For remaining credited items refer to Credit memo 32684."
    ))
    doc_type, signal = doc_type_for(ctx)
    assert doc_type != "credit_memo"


def test_credit_memo_title_on_its_own_short_line_still_fires() -> None:
    """No regression: a genuine credit-memo document title, alone on a short
    line, must still classify as credit_memo."""
    ctx = _ctx(_page("Credit Memo|CREDIT TO CREDIT # 32473|TOTAL CREDIT $2,899.00"))
    doc_type, signal = doc_type_for(ctx)
    assert doc_type == "credit_memo"
    assert signal == "credit_memo_title"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/packs/test_northstar_ladder.py -v -k "credit_memo_mentioned"`
Expected: FAIL — `doc_type == "credit_memo"`.

- [ ] **Step 3: Implement the fix**

In `src/docintel/packs/northstar/ladder.py`, add a max-words constant next to
`_MAX_PAST_DUE_LINE_WORDS`:

```python
_MAX_CREDIT_MEMO_LINE_WORDS = 6
```

Change `doc_type_for`'s first check from:

```python
    if _CREDIT_MEMO.search(text):
        return "credit_memo", "credit_memo_title"
```

to:

```python
    if _short_line_has(ctx, _CREDIT_MEMO, _MAX_CREDIT_MEMO_LINE_WORDS):
        return "credit_memo", "credit_memo_title"
```

(`_short_line_has` is already defined lower in the same file and used by
`tags_for` for `_PAST_DUE` — no new helper needed. `doc_type_for` currently
computes `text = primary_text(ctx)` at its top for other checks; keep that
line, it's still used by `_STATEMENT`/`_UNIT_RATE` below.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/packs/test_northstar_ladder.py -v`
Expected: PASS, all tests in the file (including every existing credit-memo test — check there are no other credit-memo fixtures relying on a long line, e.g. a multi-word title with more than 6 tokens; if one exists, widen the constant slightly rather than breaking it, but do not remove the line-scoping).

- [ ] **Step 5: Full regression**

Run: `pytest tests/ -q && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/docintel/packs/northstar/ladder.py tests/packs/test_northstar_ladder.py
git commit -m "fix(packs): credit-memo detection only looks at short title lines, not prose mentions"
```

---

### Task 5: Add `TOTAL CREDIT` to `pageroles`'s totals enumeration

**Files:**
- Modify: `src/docintel/extract/pageroles.py` (folds into Task 2's `_UNAMBIGUOUS_TOTALS_RE` if Task 2 is done first — see note below)
- Test: `tests/extract/test_pageroles.py`

**Interfaces:** None.

Root cause, confirmed on the real file `_AP Invoice 32473 Complete Beverage
Destruction -2249.00000.pdf` (6-page, OCR-only, two batched credit memos):
page 1 reads `Credit Memo / CREDIT TO CREDIT # 32473 / For destruction date,
refer to Certificate of Destruction. TOTAL CREDIT $2,899.00` — no
`_ANCHOR_RE` match (no "INVOICE NUMBER"/"ACCOUNT NUMBER" phrase) and, before
this fix, no `_TOTALS_RE` match either (`TOTAL CREDIT` isn't in the
enumeration). Page 2 (a BOL/certificate page) happens to contain a bare
`GRAND TOTAL` — which, after Task 2's fix, no longer qualifies since it's a
per-section subtotal — but even before Task 2, page 2 was the ONLY page with
any totals signal, so tier-1 fallback picked page 2 over page 1, and
`primary_text(ctx)` (page 2 only — a certificate/BOL page) contains no
"Northstar" bill-to text, so `NorthstarPack.claims()` fails and the document
is completely unclaimed.

**If Task 2 has already landed**, this fix is a one-line addition to
`_UNAMBIGUOUS_TOTALS_RE`'s alternation (it's already in the code sample
shown there — just confirm it's present rather than re-adding it). **If Task
2 has not landed yet**, add `TOTAL CREDIT` to the original `_TOTALS_RE`
alternation the same way.

- [ ] **Step 1: Write the failing test**

Add to `tests/extract/test_pageroles.py`:

```python
def test_total_credit_line_qualifies_as_a_totals_signal() -> None:
    """Real Complete Beverage bug: a batched credit-memo page prints 'TOTAL
    CREDIT $2,899.00' rather than any of the other enumerated totals
    phrases. Without recognizing it, the page with the real credit-memo
    header never gets primary status and the whole document goes unclaimed."""
    page1 = _page(1, [["Credit", "Memo"], ["TOTAL", "CREDIT", "$2,899.00"]])
    page2 = _page(2, [["GRAND", "TOTAL"]])  # certificate/BOL page, no real anchor either
    meta, _ = pageroles.assign((page1, page2), _meta([page1, page2]))
    assert meta[0].role == "primary"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/extract/test_pageroles.py -v -k "total_credit"`
Expected: FAIL (before the fix, page 2's bare `GRAND TOTAL` wins tier-1 since it's earlier-or-only totals-only page in the pre-Task-2 code, or — if Task 2 already landed — neither page qualifies, and tier-2/pagination fallback picks page 1 anyway only by coincidence; write the test regardless, since it must pass for the *right* reason once `TOTAL CREDIT` is recognized).

- [ ] **Step 3: Implement the fix**

Add `TOTAL CREDIT` to the totals-phrase enumeration (in
`_UNAMBIGUOUS_TOTALS_RE` if Task 2 landed first, else in `_TOTALS_RE`):

```python
    r"NOW DUE|GRAND TOTAL|TOTAL AMT|TOTAL INVOICE AMOUNT|TOTAL CREDIT)\b"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/extract/test_pageroles.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Verify against the real document, and confirm it composes with Task 4**

```python
from docintel.pipeline.stages import build_pipeline
from docintel.adapters.vision.fake import FakeVision
from docintel.adapters.intake.filesystem import FilesystemIntake
runner = build_pipeline(vision=FakeVision())
item = next(iter(FilesystemIntake(["all-docs/second-samples/complete_beverage/_AP Invoice 32473 Complete Beverage Destruction -2249.00000.pdf"]).items()))
rec = runner.process(document_id=item.document_id, source_path=item.source_path, sender_email=item.sender_email, email_id=item.email_id)
assert rec["doc_type"] == "credit_memo"  # requires Task 4 to also be done
assert "unclaimed_document" not in rec["tags"]
```

- [ ] **Step 6: Full regression**

Run: `pytest tests/ -q && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/docintel/extract/pageroles.py tests/extract/test_pageroles.py
git commit -m "fix(extract): recognize TOTAL CREDIT as a totals-block signal"
```

---

### Task 6: `_AGING_HEADER`/`_TAX_LINE` require a corroborating nonzero value

**Files:**
- Modify: `src/docintel/packs/northstar/ladder.py:31-47, 209-231` (`tags_for`)
- Test: `tests/packs/test_northstar_ladder.py`

**Interfaces:** None.

Root cause, confirmed on real files: U-Pak's `CANADIAN 4406226`, `4421470`,
`4489784`, `4489932` all print the aging table **header** row `AGE CURRENT
30 DAYS 60 DAYS 90 DAYS Please Pay` (matches `_AGING_HEADER`, which only
tests `r"\b30\s*DAYS\b.*\b60\s*DAYS\b"` against that header text) with every
bucket printing `$0.00` in the data row beneath it — `past_due` fires
regardless. Veritiv's `37584900`, `33921625`, `33927565` print `Total Tax` as
a column-header label (`...Subtotal Total Tax`) with `Total Tax = $0.00` /
items marked non-taxable — `_TAX_LINE.search(text)` matches the label
anywhere in the unrestricted `primary_text(ctx)` regardless of the actual
amount.

The fix, for both tags: require a nonzero money token on the same line as
the match, or (for the header-row case, where the header and its data live
on separate table rows) on the immediately following line.

- [ ] **Step 1: Write the failing tests**

Add to `tests/packs/test_northstar_ladder.py`:

```python
def test_aging_header_with_all_zero_buckets_does_not_tag_past_due() -> None:
    """Real U-Pak bug: 'AGE CURRENT 30 DAYS 60 DAYS 90 DAYS Please Pay' is a
    column-header row; the data row beneath it is all $0.00. Must not fire."""
    ctx = _ctx(_page(
        "U-PAK DISPOSALS|AGE CURRENT 30 DAYS 60 DAYS 90 DAYS Please Pay|"
        "0.00 0.00 0.00 0.00 4915.80"
    ))
    assert "past_due" not in tags_for(ctx)


def test_aging_header_with_a_real_60_day_balance_still_tags_past_due() -> None:
    """No regression: a genuinely nonzero aging bucket must still tag."""
    ctx = _ctx(_page(
        "U-PAK DISPOSALS|AGE CURRENT 30 DAYS 60 DAYS 90 DAYS Please Pay|"
        "0.00 0.00 4476.34 0.00 4476.34"
    ))
    assert "past_due" in tags_for(ctx)


def test_zero_total_tax_does_not_tag_has_tax() -> None:
    """Real Veritiv bug: 'Total Tax' is a column-header label; the actual
    tax charged is $0.00 (items marked non-taxable). Must not fire."""
    ctx = _ctx(_page("VERITIV OPERATING COMPANY|Subtotal Total Tax|625.00 0.00"))
    assert "has_tax" not in tags_for(ctx)


def test_nonzero_total_tax_still_tags_has_tax() -> None:
    """No regression: a genuinely nonzero tax line must still tag."""
    ctx = _ctx(_page("VERITIV OPERATING COMPANY|Subtotal Total Tax|625.00 42.50"))
    assert "has_tax" in tags_for(ctx)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/packs/test_northstar_ladder.py -v -k "zero"`
Expected: FAIL on the two "does_not_tag" tests.

- [ ] **Step 3: Implement the fix**

In `src/docintel/packs/northstar/ladder.py`, add a helper next to
`_short_line_has`:

```python
_MONEY_RE = re.compile(r"\d[\d,]*\.\d{2}")


def _line_has_nonzero_money(text: str) -> bool:
    """Whether `text` carries at least one money token that isn't 0.00 (or
    a purely-zero variant like 0,00.00). Used to corroborate a label match
    against the value it labels, rather than trusting the label alone."""
    for token in _MONEY_RE.findall(text):
        cleaned = token.replace(",", "")
        try:
            if float(cleaned) != 0.0:
                return True
        except ValueError:
            continue
    return False
```

Change the `_AGING_HEADER` check in `tags_for` (currently
`_short_line_has(ctx, _PAST_DUE, _MAX_PAST_DUE_LINE_WORDS) or
_AGING_HEADER.search(everything)`) to also require a nonzero value on the
header line itself or the line immediately following it:

```python
    if _short_line_has(ctx, _PAST_DUE, _MAX_PAST_DUE_LINE_WORDS) or _aging_table_has_balance(ctx):
        tags.append("past_due")
```

with a new helper:

```python
def _aging_table_has_balance(ctx: JobContext) -> bool:
    """`_AGING_HEADER` finds the column-header row; this corroborates it
    against the value row, which in every corpus/second-sample document is
    either the same visual line (rare) or the next one."""
    everything = "\n".join(p.text for p in ctx.pages)
    if not _AGING_HEADER.search(everything):
        return False
    for page in ctx.pages:
        lines = page.lines()
        for i, line in enumerate(lines):
            text = " ".join(w.text for w in line)
            if not _AGING_HEADER.search(text):
                continue
            if _line_has_nonzero_money(text):
                return True
            if i + 1 < len(lines):
                next_text = " ".join(w.text for w in lines[i + 1])
                if _line_has_nonzero_money(next_text):
                    return True
    return False
```

Change the `_TAX_LINE` check from `_TAX_LINE.search(text)` to require a
nonzero value on the matching short line:

```python
    if _short_line_has_nonzero_tax(ctx):
        tags.append("has_tax")
```

```python
def _short_line_has_nonzero_tax(ctx: JobContext) -> bool:
    for page in ctx.pages:
        for line in page.lines():
            text = " ".join(w.text for w in line)
            if _TAX_LINE.search(text) and _line_has_nonzero_money(text):
                return True
    return False
```

(This changes `_TAX_LINE` from an unrestricted whole-document search to a
per-line search — check no existing gold document relies on the tax label
and its value being on visually different lines; if one does, extend
`_short_line_has_nonzero_tax` to also check the next line, the same pattern
used for aging.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/packs/test_northstar_ladder.py -v`
Expected: PASS, all tests in the file.

- [ ] **Step 5: Full regression, including a check against ALL 10 gold docs' `has_tax`/`past_due` tags**

Run: `pytest tests/ -q && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold`
Expected: all green — every gold document's `tags` assertion (a superset
check per `docs/corpus/README.md`) must still include `has_tax`/`past_due`
wherever it did before, for documents where the value is genuinely nonzero.

Then re-run the second-sample batch filtered to U-Pak and Veritiv and confirm
`CANADIAN 4406226`, `4421470`, `4489784`, `4489932` no longer carry
`past_due`, and `37584900`, `33921625`, `33927565` no longer carry `has_tax`.

- [ ] **Step 6: Commit**

```bash
git add src/docintel/packs/northstar/ladder.py tests/packs/test_northstar_ladder.py
git commit -m "fix(packs): past_due/has_tax require a corroborating nonzero value, not just the column label"
```

---

### Task 7: Recalibrate `has_flattened_annotations` against a real zebra-striped table false positive

**Files:**
- Modify: `src/docintel/extract/annotations.py`
- Test: `tests/extract/test_annotations.py`

**Interfaces:** None — `detect_flattened`'s signature is unchanged.

Root cause: `_image_is_annotated` classifies a page as annotated purely from
pastel-saturation pixel coverage + scatter (see module docstring: measured
against the 10-doc corpus only). DTSS's real second-sample document
`_AP Invoice 6081...pdf` page 2 is a **computer-generated, alternating-color
delivery table** (zebra striping), not human markup, and false-fires.

Per the module's own stated methodology ("rendering every page of the
corpus... measuring the pastel-band pixel fraction and grid hit-count for
each, and choosing a cut"), the fix must be measured the same way, not
guessed. This task requires actually rendering the real page and comparing
its metrics against the existing 39-page-corpus calibration set — do not
skip this measurement step.

- [ ] **Step 1: Measure the false-positive page's actual metrics**

Run this once, interactively, before writing any test:

```python
import pdfplumber
from docintel.extract.annotations import _image_is_annotated, SAT_MIN, SAT_MAX, VALUE_MIN, FRAC_THRESHOLD, GRID_COLS, GRID_ROWS, CELL_HIT_THRESHOLD, MIN_HIT_CELLS, RESOLUTION
from PIL import ImageChops

path = "all-docs/second-samples/dtss/_AP Invoice 6081...pdf"  # use the real filename found by `ls all-docs/second-samples/dtss/ | grep 6081`
with pdfplumber.open(path) as doc:
    page = doc.pages[1]  # page 2, 0-indexed
    img = page.to_image(resolution=RESOLUTION).original.convert("RGB")
hsv = img.convert("HSV")
_, s_band, v_band = hsv.split()
mask = ImageChops.multiply(
    s_band.point([255 if SAT_MIN <= i <= SAT_MAX else 0 for i in range(256)]),
    v_band.point([255 if i >= VALUE_MIN else 0 for i in range(256)]),
)
total_px = img.size[0] * img.size[1]
hit_frac = mask.histogram()[-1] / total_px
grid = mask.resize((GRID_COLS, GRID_ROWS))
hit_cells = sum(1 for px in grid.getdata() if px >= CELL_HIT_THRESHOLD)
print(f"hit_frac={hit_frac:.4f} (threshold {FRAC_THRESHOLD}), hit_cells={hit_cells} (threshold {MIN_HIT_CELLS})")
```

Record the printed numbers — you'll need them to decide the fix in Step 3.
The two structurally distinct possibilities, decide between them from the
actual numbers:

- **If `hit_cells` is high but the hits form one dense, contiguous
  full-width band** (a stripe pattern) rather than scattered discrete
  blobs the way Federal Recycling's six separate highlighter marks do:
  add a contiguity check — reject if the hit cells occupy nearly every
  column in a small number of contiguous rows (a table's zebra rows) rather
  than being scattered across many rows and columns.
- **If `hit_frac`/`hit_cells` are simply below Federal Recycling's margin
  but above the current threshold**: tighten `FRAC_THRESHOLD`/
  `MIN_HIT_CELLS` slightly, and re-verify Federal Recycling's page (`docs/`
  — find the actual filename via `docs/corpus/gold/northstar-federal-recycling-1330123.json`'s `source_file`) still clears the new threshold with margin.

- [ ] **Step 2: Write the failing test**

Add to `tests/extract/test_annotations.py` (check the existing file first for
its synthetic-image-fixture helper — reuse it rather than building raw `PIL.Image` objects from scratch):

```python
def test_zebra_striped_delivery_table_is_not_flagged_as_annotated() -> None:
    """Real DTSS bug: a computer-generated alternating-row delivery table
    (regular, full-width color bands) must not be mistaken for scattered
    human highlighter/comment-box markup."""
    # Build a synthetic image matching the measured shape from Step 1 (full-
    # width horizontal bands, not scattered blobs) using this file's existing
    # fixture helper, and assert `_image_is_annotated(img)` is False.
    ...
```

(This step's `...` must be filled in with the actual synthetic image whose
measurements you captured in Step 1, using whatever helper the existing test
file already provides for building a `PIL.Image` with a controlled
saturation/value pattern — do not invent a different image-construction
approach than what the file already uses for the existing greyscale-blind-spot test.)

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/extract/test_annotations.py -v -k "zebra"`
Expected: FAIL — `_image_is_annotated` returns `True`.

- [ ] **Step 4: Implement the chosen fix from Step 1**

Apply whichever of the two approaches Step 1's measurement pointed to.
Update the module docstring's calibration paragraph to mention the new
DTSS data point (following the existing convention of naming exactly which
real documents were used to pick the cut).

- [ ] **Step 5: Run test to verify it passes, and confirm no regression on Federal Recycling**

Run: `pytest tests/extract/test_annotations.py -v`
Expected: PASS, all tests — **especially** the existing Federal Recycling
true-positive test and the existing greyscale-blind-spot test, neither of
which may regress.

- [ ] **Step 6: Full regression**

Run: `pytest tests/ -q && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/docintel/extract/annotations.py tests/extract/test_annotations.py
git commit -m "fix(extract): a printed zebra-striped table no longer trips the flattened-annotation detector"
```

---

### Task 8: `_has_promo_block` — catch real full-page OCR'd ads, stop false-firing on logo graphics

**Files:**
- Modify: `src/docintel/packs/digitaldirection/ladder.py:120-130`
- Test: `tests/packs/test_digitaldirection_ladder.py`

**Interfaces:**
- Consumes: `PageMeta.char_count` (already exists — no new `PageMeta` field needed).

Root cause, confirmed on two real files: `Windstream_021942648_09022025_BILL.pdf`
page 1 is a genuine full-page "Go Kinetic Business" advertisement with a QR
code and app-store badges, rendered as ONE raster image after OCR
(`image_count == 1`) — `_has_promo_block`'s `image_count >= 2` test misses
it entirely. `Windstream_216713099_08272025_BILL.pdf` page 1 is a native PDF
with 5 small incidental logo/header-bar images and ordinary invoice
content — `image_count >= 2` false-fires.

The fix: combine `image_count` with `char_count` density. A genuine
full-page ad, even OCR'd into one image, still has very little actual invoice
text on it (a slogan, a URL, maybe a phone number) compared to the bulk of a
real billing page (dozens of line items, labels, numbers). An ordinary
letterhead-plus-content page, even with several small incidental logo
images, has substantial normal invoice text.

- [ ] **Step 1: Measure both real pages' actual `char_count` and `image_count`**

```python
from docintel.extract.normalize import load_document
for f in ["Windstream_021942648_09022025_BILL.pdf", "Windstream_216713099_08272025_BILL.pdf"]:
    pages, meta, text_source = load_document(f"all-docs/second-samples/windstream/{f}")
    print(f, "page1 image_count=", meta[0].image_count, "char_count=", meta[0].char_count, "text_source=", text_source)
```

Record both pairs of numbers — pick the `char_count` cutoff from what you
observe (a real ad page's char_count should be visibly lower than the false
positive's), following the same "measure the real documents, then set the
cut" methodology used everywhere else in this codebase, rather than guessing
a round number.

- [ ] **Step 2: Write the failing tests**

Add to `tests/packs/test_digitaldirection_ladder.py` (check its existing
`_page`/`_ctx` helpers first — this file's `_ctx` builds `page_meta` too;
read the full helper before writing new fixtures):

```python
def test_full_page_ocr_ad_with_one_collapsed_image_still_tags_promo_content() -> None:
    """Real Windstream bug: a genuine full-page ad, OCR'd, collapses to
    image_count=1 — the old image_count>=2 test misses it. Use the measured
    char_count from the real page (a short slogan/URL, not real bill content)."""
    ...  # build ctx with page_meta[0].image_count == 1 and a low char_count matching Step 1's measurement


def test_ordinary_page_with_several_small_logo_images_does_not_tag_promo_content() -> None:
    """Real Windstream bug: 5 incidental small header/logo images plus normal
    invoice content must not false-fire."""
    ...  # build ctx with page_meta[0].image_count >= 2 and a normal (high) char_count matching Step 1's measurement
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/packs/test_digitaldirection_ladder.py -v -k "promo"`
Expected: FAIL on both new tests.

- [ ] **Step 4: Implement the fix**

```python
# Char-count cutoff picked from the real corpus (see task plan for the
# measured values): a genuine full-page ad has almost no real invoice text
# even after OCR reads its slogan/URL/phone number; an ordinary billing page
# with incidental logo graphics has substantial normal content.
_PROMO_PAGE_MAX_CHARS = <fill in from Step 1's measurement>


def _has_promo_block(ctx: JobContext) -> bool:
    """A dominant advertising block on page 1 (F9, Windstream) — either
    several small images (a native-PDF ad collage) or a single image with
    very little real text on it (an OCR'd full-page ad collapsed to one
    raster)."""
    for meta in ctx.page_meta:
        if meta.page_number != 1:
            continue
        if meta.image_count >= 2:
            return True
        if meta.image_count == 1 and meta.char_count <= _PROMO_PAGE_MAX_CHARS:
            return True
    return False
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/packs/test_digitaldirection_ladder.py -v`
Expected: PASS, all tests.

- [ ] **Step 6: Full regression, including the real files from Step 1**

Run: `pytest tests/ -q && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold`
Expected: all green. Then re-run both real Windstream files through the full
pipeline and confirm the tag now matches expectation (present on
`021942648`, absent on `216713099`).

- [ ] **Step 7: Commit**

```bash
git add src/docintel/packs/digitaldirection/ladder.py tests/packs/test_digitaldirection_ladder.py
git commit -m "fix(packs): promo_content detection catches OCR'd full-page ads and stops false-firing on incidental logo images"
```

---

### Task 9: Add "previous total" to `PRIOR_BALANCE_ANCHORS`

**Files:**
- Modify: `src/docintel/packs/digitaldirection/ladder.py:49-52`
- Test: `tests/packs/test_digitaldirection_ladder.py`

**Interfaces:** None.

Root cause, confirmed on real file `Windstream_205577168_08222025_BILL.pdf`:
prints `Previous Total` (not any of the five phrases currently in
`PRIOR_BALANCE_ANCHORS`) with a genuine unresolved $2.99 carryover. This
means `prior_balance_present` never gets tagged at all for this Windstream
Enterprise template — exactly the "silent overpayment" risk the module's own
docstring calls out as the most dangerous failure mode for this tag (see
`s3` and `PRIOR_BALANCE_ANCHORS`'s own comment: "failing to find a prior
balance is far more dangerous than finding a wrong one").

- [ ] **Step 1: Write the failing test**

Add to `tests/packs/test_digitaldirection_ladder.py`:

```python
def test_previous_total_phrase_tags_prior_balance_present() -> None:
    """Real Windstream Enterprise template bug: prints 'Previous Total' (not
    any of the five phrases already covered), with a genuine unresolved
    carryover. Missing this tag is a silent-overpayment risk (same class as
    F1) — the printed prior balance would never be checked."""
    ctx = _ctx("WINDSTREAM ENTERPRISE|Previous Total $2.99|New Charges $116.00")
    assert "prior_balance_present" in tags_for(ctx)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/packs/test_digitaldirection_ladder.py -v -k "previous_total"`
Expected: FAIL.

- [ ] **Step 3: Implement the fix**

```python
PRIOR_BALANCE_ANCHORS = re.compile(
    r"\b(previous balance|previous bill|previous statement balance|"
    r"balance from last statement|previous balance due|previous total)\b", re.I
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/packs/test_digitaldirection_ladder.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Full regression**

Run: `pytest tests/ -q && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/docintel/packs/digitaldirection/ladder.py tests/packs/test_digitaldirection_ladder.py
git commit -m "fix(packs): recognize 'Previous Total' as a prior-balance anchor (Windstream Enterprise template)"
```

---

### Task 10: Add missing managed clients to `MANAGED_CLIENTS`

**Files:**
- Modify: `src/docintel/packs/digitaldirection/aliases.py:139-166`
- Test: `tests/packs/test_aliases.py`

**Interfaces:** None.

Root cause: every `bill_to_mismatch` firing found in the second-sample audit
(Lumen `2N8BFFLC`/`DK176HGT`, Windstream `216713099`) traces to the same
gap — Golub Corporation and Tops Markets LLC are real Digital Direction
clients not present in `MANAGED_CLIENTS`. Per the roster's own documented
design ("A client not listed here yields an empty bill_to_name... escalated
to review... rather than guessed"), this is meant to be a routine
config/roster update, not a code-logic fix — exactly the workflow the
roster's docstring describes ("onboarding a client is a one-line config
change, reviewed as business data").

- [ ] **Step 1: Confirm the exact printed client names from the real documents**

```python
from docintel.extract.normalize import load_document
for f in ["all-docs/second-samples/lumen/...pdf", "all-docs/second-samples/windstream/Windstream_216713099_08272025_BILL.pdf"]:  # fill in the real lumen filenames via `ls all-docs/second-samples/lumen/`
    pages, meta, _ = load_document(f)
    for page in pages[:1]:
        for line in page.lines():
            text = " ".join(w.text for w in line)
            if "golub" in text.lower() or "tops" in text.lower():
                print(f, "|", text)
```

Record the exact printed casing/spacing — `MANAGED_CLIENTS` entries must
match how each carrier actually prints the name (see the existing comment
about Comcast truncating "Clyde Administration Servi" in a fixed-width
field — a client may need more than one rendering).

- [ ] **Step 2: Write the failing test**

Add to `tests/packs/test_aliases.py` (check its existing conventions for
`resolve_bill_to_alias` tests first):

```python
def test_golub_corporation_is_a_recognized_managed_client() -> None:
    resolved = resolve_bill_to_alias("<exact printed text from Step 1>")
    assert resolved is not None


def test_tops_markets_is_a_recognized_managed_client() -> None:
    resolved = resolve_bill_to_alias("<exact printed text from Step 1>")
    assert resolved is not None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/packs/test_aliases.py -v -k "golub or tops"`
Expected: FAIL.

- [ ] **Step 4: Implement the fix**

Add both entries to `MANAGED_CLIENTS` in
`src/docintel/packs/digitaldirection/aliases.py`, using the exact printed
text captured in Step 1:

```python
MANAGED_CLIENTS: tuple[str, ...] = (
    "Clyde Administration Servi",
    "Clyde Companies",
    "City of Dublin",
    "Choctaw Travel Mart",
    "<exact printed Golub text>",
    "<exact printed Tops Markets text>",
)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/packs/test_aliases.py -v`
Expected: PASS, all tests.

- [ ] **Step 6: Full regression**

Run: `pytest tests/ -q && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold`
Expected: all green. Then re-run the three real files and confirm
`bill_to_mismatch` no longer fires on them.

- [ ] **Step 7: Commit**

```bash
git add src/docintel/packs/digitaldirection/aliases.py tests/packs/test_aliases.py
git commit -m "fix(packs): add Golub Corporation and Tops Markets to the Digital Direction managed-client roster"
```

---

### Task 11: Full regression sweep + re-run the second-sample batch + update the audit doc

**Files:**
- Modify: `docs/classification-audit-2026-08-06.md`

**Interfaces:** None — verification and documentation only.

- [ ] **Step 1: Full test suite**

Run: `pytest tests/ -q`
Expected: 100% pass, zero regressions from the pre-fix baseline.

- [ ] **Step 2: Gold-corpus regression**

Run: `python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold`
Expected: `validate_gold.py`'s 95 checks all pass (unchanged — these fixes
don't touch gold labels); `replay-gold` shows **improvement** over the
pre-fix baseline (in particular `northstar-edco-819387` should now pass,
per Task 1).

- [ ] **Step 3: Re-run the full second-sample batch**

```python
import json, glob
from docintel.adapters.intake.filesystem import FilesystemIntake
from docintel.adapters.vision.fake import FakeVision
from docintel.pipeline.stages import build_pipeline

paths = sorted(glob.glob("all-docs/second-samples/*/*.pdf"))
runner = build_pipeline(vision=FakeVision())
rows = []
for item in FilesystemIntake(paths).items():
    rec = runner.process(document_id=item.document_id, source_path=item.source_path,
                          sender_email=item.sender_email, email_id=item.email_id)
    rows.append({"path": item.source_path, "doc_type": rec["doc_type"],
                 "pack": (rec.get("sender_fingerprint") or "|").split("|")[0],
                 "review_flag": rec.get("review_flag"), "tags": rec.get("tags")})
```

Compare against the pre-fix baseline captured in Task 0's audit doc. Expect:
- Zero `unclaimed_document` (was 3).
- EDCO review_flag count down from 17/28 to ≤4/28 (3 genuine bill-to typos + `709223OCT25`'s pre-existing, out-of-scope defect).
- Zero `invoice_with_attachment`-related unclaimed docs.
- `past_due`/`has_tax` counts reduced (exact numbers depend on the real corpus — report what you actually measure, do not assume the exact pre-fix counts from Task 0's table still apply verbatim after Tasks 1-3 change other tags incidentally).

- [ ] **Step 4: Update the audit doc with after-fix numbers**

Fill in the "After-fix numbers" section of
`docs/classification-audit-2026-08-06.md` with the actual before/after
distribution table and gold-corpus results from Steps 2-3. Do not
approximate — paste the real measured numbers.

- [ ] **Step 5: Commit**

```bash
git add docs/classification-audit-2026-08-06.md
git commit -m "docs: record post-fix classification accuracy numbers"
```

---

## Self-Review Notes

**Spec coverage:** All 10 confirmed defects from the investigation have a
task (1↔Task1, 2↔Task2, 3↔Task3, 4↔Task4, 5↔Task5, 6↔Task6 covers both
`_AGING_HEADER` and `_TAX_LINE`, 7↔Task7, 8↔Task8, 9↔Task9, 10↔Task10). The
"understand, categorize, save it somewhere" part of the original request is
covered by Tasks 0 and 11. The one pre-existing, already-documented defect
(EDCO `709223OCT25` swapped header rows) is explicitly left out of scope —
it was already known before this audit and the persona's own notes record it
as deferred to a human product decision, not something this investigation
newly found.

**Placeholder scan:** Task 7 (annotation recalibration) and Task 8 (promo
block) and Task 10 (managed clients) each have one step that asks the
implementer to measure real data and fill in a number/string from that
measurement rather than a pre-baked constant — this is intentional, matches
the codebase's own stated calibration methodology (see `annotations.py`'s
and `edco.json`'s docstrings: "measured against all N real samples", never
guessed), and every such step gives the exact file(s) to measure and the
exact code to run. This is not the same as a vague "add validation"
placeholder — it is empirical-fix-by-design, consistent with how this
codebase was built.

**Type/interface consistency:** `shared_footer_pages` (Task 3) is defined
once in `core/pagination.py` and consumed identically by both
`packs/northstar/ladder.py` (via `ctx.pages`) and `extract/pageroles.py` (via
its own `pages` parameter) — same function, same signature, no drift.
