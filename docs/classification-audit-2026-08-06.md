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
