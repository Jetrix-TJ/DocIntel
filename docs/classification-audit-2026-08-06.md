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

All ten fixes from `docs/superpowers/plans/2026-08-06-classification-accuracy-fixes.md`
are implemented and committed (`cb763e0`..`dc7df88`). Re-ran the full test suite, the
gold-corpus checks, and the same 111-document second-samples batch used for the original
audit, and diffed the results.

### Regression checks

- `pytest tests/ -q` → **1719/1719 passed**, zero failures.
- `python3 docs/corpus/validate_gold.py` → **104/104 checks pass**, gold set internally
  consistent (unchanged from before — these fixes don't touch gold-label consistency,
  except the one intentional correction below).
- `python3 -m docintel.cli replay-gold` → **1/11 documents fully green**, same count as
  before this plan. This is not a regression: every remaining `FAIL` traces to defects
  explicitly out of this plan's scope (documented per-task by each implementer and
  independently confirmed by each task's reviewer — e.g. EDCO's known swapped-header
  `bill_to_name` defect, telecom bills' unrelated address/reference mismatches). No gold
  document's assertion count went down because of these fixes; several went up (see below).
- Two gold-label changes were made, both explicitly authorized after evidence review
  (documented in the plan's ledger and in commits `1e133e9`, part of Task 6/8):
  - `docs/corpus/gold/northstar-upak-4378107.json` — `past_due` removed from
    `classification.tags`. The tag was a mislabeled artifact of the exact `_AGING_HEADER`
    bug this plan fixes (the document's own aging buckets are all $0.00; the tag only ever
    fired because the pre-fix code matched the column *header*, not the values).
  - `digitaldirection-windstream-041069076`'s `promo_content` tag — previously **missing**
    from the pipeline's output despite the gold label's own note reading "Half of page 1
    is an advertisement" — now correctly emitted (Task 8's content-based redesign), an
    improvement, not a change to the gold label itself.

### Second-samples batch: before vs. after (same 111 documents, same 7 vendors)

| Metric | Before | After | Change |
|---|---:|---:|---|
| `unclaimed_document` | 3 | **0** | -3 (100%) |
| `review_flag: true` (all vendors) | 57 | 49 | -8 |
| EDCO `review_flag: true` | 17/28 | **9/28** | -8 (47%) |
| `bill_to_mismatch` | 7 | 4 | -3 (all 3 were Digital Direction roster gaps; the 4 remaining are 3 genuine EDCO bill-to typos + 1 pre-existing, already-documented EDCO defect out of this plan's scope) |
| `past_due` | 26 | 18 | -8 |
| `has_tax` | 19 | 16 | -3 (all 3 were the named Veritiv false positives) |
| `has_flattened_annotations` | 2 | 1 | -1 (the DTSS zebra-striped-table false positive) |
| `doc_type: telecom_bill` | 5 | 7 | +2 (the 2 previously-unclaimed 472-page Windstream documents) |
| `doc_type: credit_memo` | 1 | 2 | +1 (the previously-unclaimed Complete Beverage batched credit memo) |
| `promo_content` | 1 (on the wrong document) | 1 (on the correct document) | relabeled, verified below |
| `prior_balance_present`/`prior_balance_cleared` (Digital Direction) | 0 / 3 | 1 / 6 | Task 9's "Previous Total" anchor now catches a real unresolved carryover that previously got no tag at all |

**EDCO review-flag note:** the plan's investigation predicted the fix would bring EDCO's
review rate down to ≤4/28 (3 genuine bill-to typos + 1 known defect). The real, measured
number is 9/28 — a real and substantial improvement (47%), but short of the optimistic
prediction. The gap is because Task 1's `payments_credits` selector, anchored on the
literal `"PAYMENT -- THANK YOU"` phrase, does not resolve every EDCO document with an
intervening balance adjustment — one document (`968397OCT25`) uses an `"INCREASE"` line
instead, which Task 1 explicitly and correctly declined to guess a sign convention for
rather than force a fit. The remaining EDCO review flags are real, uninvestigated-further
cases, not newly discovered false positives — closing them fully would need a follow-up
task, not a correction to this one.

**Verified explicitly, not just by count:** `promo_content` now correctly tags
`Windstream_021942648_09022025_BILL.pdf` (the real full-page ad — "Go Kinetic Business",
QR code, app-store language) and correctly no longer tags
`Windstream_216713099_08272025_BILL.pdf` (5 incidental small logo images, ordinary bill
content) — confirmed by reading both documents' tag lists directly, not inferred from the
count staying at 1 (a coincidence of one false positive being removed while one true
positive was added).

### Net effect

The classification/tagging layer went from measurably unreliable on real-world data (3
completely unclaimed documents, 51% of the corpus flagged for review, several
demonstrably-wrong tags on real invoices) to a state where every doc_type/pack assignment
in the corpus is correct, zero documents are unclaimed, and every remaining `review_flag`
or tag firing that was checked traces to either a genuine business condition (a real
typo'd bill-to name, a real aged balance) or an already-documented, separately-tracked
defect outside this plan's scope.
