# Pack: Northstar Recycling — vendor AP invoices

**Domain:** waste & recycling vendor invoices billed to Northstar Recycling Company, LLC
(94 Maple St / PO Box 188, East Longmeadow, MA 01028).

**Corpus evidence:** documents 1–6 in [`../corpus-analysis.md`](../corpus-analysis.md) —
D.T.S.S., Veritiv, Complete Beverage Destruction, Federal Recycling, U-Pak, EDCO.

**Defining characteristic:** commodity credits and service fees appear on the same invoice with
opposite signs, and the match key back to Northstar's system of record is buried in free text under at
least five different labels.

---

## 1. Document types

Priority-ordered signal ladder for `classifySignals`. **First signal that fires wins**, then the ladder
stops (spec Stage 3).

| # | `doc_type` | Signal | Evidence |
|---|---|---|---|
| 1 | `credit_memo` | Title matches `credit memo` / `credit note` / `adjustment note` | — (not in corpus; keep above contra) |
| 2 | `contra_invoice` | **All** commodity lines negative, **and** a contra/credit marker or a negative-priced commodity column | Federal Recycling `1330123` |
| 3 | `invoice_with_attachment` | Exactly one `primary` page + ≥1 `supporting` page (see `page_role`) | Complete Beverage `32930` |
| 4 | `statement_of_account` | No line-item table **and** title `statement of account` | — |
| 5 | `own_paperwork` | Letterhead is Northstar itself | — |
| 6 | `standard_invoice` | **default** | D.T.S.S., Veritiv, U-Pak, EDCO |

> **Ladder-order note.** `contra_invoice` must sit **above** `invoice_with_attachment`, because
> Federal Recycling is a single-page contra and Complete Beverage is a multi-page invoice that also
> contains negative lines. Testing "has negatives" before "has attachments" would let a multi-page
> invoice with a rebate line be misclassified as contra.

### Tags (layered on, never change the type)

| Tag | Trigger | Evidence |
|---|---|---|
| `mixed_sign` | Line-item signs differ | Federal Recycling, Complete Beverage, U-Pak |
| `past_due` | `PAST DUE` · aging buckets · dunning block | EDCO, U-Pak |
| `foreign_currency` | `currency != USD` | U-Pak (CAD) |
| `has_tax` | Tax line present | Veritiv, U-Pak |
| `has_flattened_annotations` | Colored fills / overlapping text runs, `annots == 0` | Federal Recycling |
| `handwritten_supporting` | Handwriting on a `supporting` page | Complete Beverage p2 |
| `ocr_only` | `text_source == ocr` | Federal Recycling, Complete Beverage |
| `sub_accounts` | `SUB ACCT` markers present | U-Pak |
| `early_pay_discount` | Discount date + amount present | Veritiv |

---

## 2. Field set

### Required — every `doc_type`

| Field | Notes | Anchors observed |
|---|---|---|
| `vendor_name` | Letterhead; prefer remittance payee | letterhead block |
| `invoice_number` | | `Invoice #` · `Invoice No.` · `INVOICE #` · `No.` |
| `invoice_date` | | `Date` · `Invoice Date` · `DATE` |
| `total_printed` | The headline figure, as printed | `Total` · `Balance Due` · `Total Amount Due` · `TOTAL` · `Amount Due` · `Total Invoice` |
| `amount_payable` | **derived only** (`derived_only`, V10) | — |
| `currency` | Inference ladder per F14 | — |
| `bill_to_name` | **Guard**: must resolve to Northstar | `Bill To` · `FOR` · `SOLD TO` |
| `reference_list[]` | Objects with provenance (F11) | see §3 |

### Required — commercial terms

| Field | Anchors |
|---|---|
| `due_date` | `Due Date` · `DUE DATE` |
| `payment_terms` | `Terms` · `PAYMENT TERMS` |
| `prior_balance` *(optional)* | `BALANCE FORWARD` · `Balance from last statement` · `Previous Balance` |
| `current_charges` *(optional)* | `CURRENT CHARGES:` · `Current Charges` |
| `subtotal` | `Subtotal` · `Sub Total` |
| `tax_amount` | `Total Tax` · `Taxes` · `H.S.T.` · `G.S.T.` |
| `charges[]` | `{label, amount}` pairs for surcharges (F14) |
| `discount_date` `discount_amount` | `Discount Date` · `Discount Amount` |

### Required — allocation

| Field | Anchors | Why |
|---|---|---|
| `service_location` | `SHIP TO` · `Location:` · `FOR SERVICE AT:` · `Service Address` | The end site the cost belongs to (F13) |
| `vendor_account_number` | `Account No.` · `Account Number` | |
| `sub_account[]` | `** SUB ACCT:` | U-Pak's 70+-identity nesting (F13) |

### Line items — `row_group`

Columns matched by **header text** (F19). Union of headers seen across the corpus:

```
Date · Service Date · Mo/Day · Item · Product No. · Trans No. · Reference
Description · Description/References · Qty · Quantity · Qty Ordered · Qty Shipped
Weight · Unit Meas. · Rate · Price · Unit Price · Amount · Extended Price
Charges · Payments · Balance · Total · GP
```

Per-row capture: `description` · `quantity` · `unit_price` · `amount` · `reference?` ·
`service_date?` · `item_code?` · `unit_of_measure?`

`allow_empty_cells: true` — U-Pak leaves `AMOUNT` blank while `TOTAL` is populated (F15).

---

## 3. Reference patterns

Ordered alternatives, all captured, all with provenance (F11):

| `pattern_id` | Pattern | Scope | Evidence |
|---|---|---|---|
| `ns_hash` | `NS\s?#\s?(\d{7})` | any-page | D.T.S.S. `NS # 2561194` |
| `northstar_hash` | `Northstar#\s*(\d{7})` | any-page | Veritiv `Northstar# 2542693` |
| `work_order` | `WORK ORDER#:\s*(\d{7})` | any-page | U-Pak `4342903`, `4348255`, … |
| `ref_column` | `(\d{7})` | **column** `Reference` only | Federal Recycling `2436687`, … |
| `seal` | `SEAL#\s*(\d{7})` | any-page | Complete Beverage `5951119` |
| `bol` | `BOL#\s*([\d-]{8,12})` | any-page | Complete Beverage `10-21-25-01` |
| `sales_order` | `SALES ORDER NO\.?\s*(\d{8})` | line_items | Veritiv `33905296` |

`ref_column` is a bare 7-digit pattern and is therefore **only** legal scoped to a column
(grammar V6) — unscoped it matches zip+4, phone fragments and account numbers.

Every hit emits:

```jsonc
{ "value": "2436687", "source_field": "Reference", "page": 1, "pattern_id": "ref_column" }
```

**Annotation hazard.** Federal Recycling's flattened boxes carry `2436818`, `2436820`, `2436821`,
`2469435`, `2469427` — human corrections that OCR cannot distinguish from print (F3). Those hits are
tagged `source_field: "annotation_overlay"` when the overlay detector fires, and the document is
force-flagged for review. They are **never** silently merged with printed references.

---

## 4. Vendor alias table

`beforePersonaLookup`. Small today; this is the file that grows.

```
d.t.s.s. | dtss | d t s s inc          → dtss
veritiv operating company | veritiv     → veritiv
complete beverage destruction | cbd-usa → complete_beverage_destruction
federal recycling & waste solutions
  | federal international recycling
  and waste solutions                   → federal_recycling
u-pak disposals | u-pak disposals (1989) ltd | u pak → upak
edco waste & recycling service | edco disposal → edco
```

Federal Recycling is the live case: the letterhead says *"Federal Recycling & Waste Solutions"* and
the check remittance says *"Federal International Recycling and Waste Solutions, LLC"*. Prefer the
payee (F5).

---

## 5. Hooks

| Socket | Function | Purpose |
|---|---|---|
| `afterFilter` | `detectFlattenedAnnotations` | Colored-fill / overlapping-text detection → tag + force review (F3) |
| `afterFilter` | `assignPageRoles` | `primary` / `supporting` classification (F10) |
| `classifySignals` | `northstarLadder` | The §1 ladder |
| `beforePersonaLookup` | `resolveVendorAlias` | §4 table, payee-preferred |
| `afterExtraction` | `deriveAmountPayable` | `derive_amount_payable` (F1) — EDCO |
| `afterExtraction` | `runArithmeticCrosschecks` | The three F8 checks |
| `afterExtraction` | `inferCurrency` | CAD from `H.S.T.` + ON postal code (F14) |
| `afterExtraction` | `collectReferences` | Ordered alternatives, provenance, dedupe |
| `beforeConfidenceGate` | `northstarThresholds` | §6 |
| `beforeEmit` | `attachAllocationMetadata` | `service_location`, `sub_account[]` |
| `onRegenTrigger` | `excludeAnnotatedFromGold` | Annotated docs never enter the gold set (F3) |

---

## 6. Confidence thresholds

**Provisional — parked with the business per the spec's open questions.** Set here so the gate is
testable from day one; expect these numbers to move.

| Field | Threshold | Rationale |
|---|--:|---|
| `total_printed` | 0.95 | A wrong total is a wrong payment |
| `amount_payable` | 0.95 | Same, and it is derived — no closure means no confidence |
| `invoice_number` | 0.92 | Dedup key |
| `vendor_name` | 0.90 | Downstream resolution can recover from near-misses |
| `invoice_date` `due_date` | 0.88 | |
| `reference_list[]` | 0.85 | A list; downstream matching tolerates extras |
| `service_location` | 0.80 | Allocation hint, human-correctable |
| line-item rows | 0.85 | Guarded independently by the line-sum check |

**Overrides**
- `tags` contains `has_flattened_annotations` → **review flag regardless of confidence**.
- `tags` contains `mixed_sign` → require the line-sum check to pass, or review.
- `text_source == ocr` → apply `ocr_source ×0.90`; do not raise thresholds (that would double-count).

---

## 7. Per-document expectations

What each corpus document must produce. Full values in [`../corpus/gold/`](../corpus/gold/).

| Document | `doc_type` | `amount_payable` | Expected routing |
|---|---|--:|---|
| D.T.S.S. `6060` | `standard_invoice` | 699.00 | **High** — clean, closes, native text |
| Veritiv `715-33905296` | `standard_invoice` | 4,908.00 | **High** — closes; `early_pay_discount` tag |
| Complete Beverage `32930` | `invoice_with_attachment` | 1,177.70 | **Medium** — OCR-only + handwritten support page |
| Federal Recycling `1330123` | `contra_invoice` | 481.20 | **Review, forced** — flattened annotations |
| U-Pak `4378107` | `standard_invoice` | **null** | **Review** — `arith_balance_mismatch`, −48.92 unexplained |
| EDCO `077087` | `standard_invoice` | 69.62 | **High** — trap correctly derived, closure verified |

Two of six route to review, and **both for the right reason**: a document a human has already
annotated, and a document whose arithmetic genuinely does not close. Neither is a confidence failure —
they are correct refusals to guess.
