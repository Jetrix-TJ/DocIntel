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

> **Narrowed to printed values.** Everything below is what the pack extracts
> today, which is a strict subset of what this section originally specified. The
> reason, the full list of what left, and how to bring it back are in
> [`docs/superpowers/specs/2026-07-28-printed-fields-only-design.md`](../superpowers/specs/2026-07-28-printed-fields-only-design.md).
> Anchors are unchanged — they were never the thing that was wrong.

### `REQUIRED` is not a flat set

The Required level says "**any** parseable date" and "**at least one** money
amount", which V13 set-membership cannot express. `fields.py` encodes it as one
unconditional name plus two any-of groups (spec §3):

```python
REQUIRED       = {"bill_to_name"}
REQUIRED_ANY_OF = (
    {"invoice_date", "bill_date"},                                        # any date
    {"total_printed", "balance_due", "please_pay",                        # >= 1 amount
     "current_charges", "subtotal"},
)
```

`bill_to_name` is the only unconditional requirement because it carries the
**guard** that the billed party resolves to Northstar. Requiring `invoice_date`
outright would make EDCO — which prints a billing date and no invoice date —
unwritable; requiring `total_printed` outright would exclude every vendor that
prints no total.

`vendor_name` is deliberately *not* required. It stays in `FIELDS` (a readable
letterhead is still captured) but the sender domain is the primary source; see
`core/senders.py` and spec §4.

### Printed — every `doc_type`

| Field | Notes | Anchors observed |
|---|---|---|
| `vendor_name` | Letterhead; prefer remittance payee. Not required — see above | letterhead block |
| `invoice_number` | | `Invoice #` · `Invoice No.` · `INVOICE #` · `No.` |
| `invoice_date` | | `Date` · `Invoice Date` · `DATE` |
| `bill_date` | EDCO's shape: a billing date and no invoice date | `Billing Date` · `Bill Date` |
| `total_printed` | The headline figure, **as printed** — never adjusted toward a payable | `Total` · `Balance Due` · `Total Amount Due` · `TOTAL` · `Amount Due` · `Total Invoice` |
| `bill_to_name` | **Guard**: must resolve to Northstar | `Bill To` · `FOR` · `SOLD TO` |
| `reference_list[]` | Objects with provenance (F11) | see §3 |

### Printed — commercial terms

| Field | Anchors |
|---|---|
| `due_date` | `Due Date` · `DUE DATE` |
| `payment_terms` | `Terms` · `PAYMENT TERMS` |
| `prior_balance` *(optional)* | `BALANCE FORWARD` · `Balance from last statement` · `Previous Balance` |
| `current_charges` *(optional)* | `CURRENT CHARGES:` · `Current Charges` |
| `payments_credits` *(optional)* | `Payments` · `Payments/Credits` — stored negative |
| `balance_due` `please_pay` | `Balance Due` · `Please Pay` |
| `subtotal` | `Subtotal` · `Sub Total` |
| `tax_amount` | `Total Tax` · `Taxes` · `H.S.T.` · `G.S.T.` |
| `charges[]` | `{label, amount}` pairs for surcharges (F14) |
| `discount_date` `discount_amount` | `Discount Date` · `Discount Amount` |

Every one of these is transcribed. No op reconciles them against each other and
no op composes them into a figure to pay — that is `amount_payable`'s job and
`amount_payable` is deferred, below.

### Printed — allocation and addresses

| Field | Anchors | Why |
|---|---|---|
| `service_location` | `SHIP TO` · `Location:` · `FOR SERVICE AT:` · `Service Address` | The end site the cost belongs to (F13) |
| `vendor_account_number` `account_number` | `Account No.` · `Account Number` | |
| `bill_to_address` `bill_to_attention` `bill_to_email` | header addressee block | |
| `remit_payee` `remit_address` `return_address` `vendor_address` | `Remit To` · `Make check payable to` · envelope block | |
| `customer_po` `seal_number` `bol_number` | see §3 | Match keys |
| `sub_account[]` | `** SUB ACCT:` | U-Pak's 70+-identity nesting (F13); a row group, not a field |

### Not in scope — deferred, not deleted

Nothing here was removed from the gold files, and every module and unit test that
produced it is still on disk. Re-enabling is a wiring change.

| Field | Why it left |
|---|---|
| `amount_payable` `payable_basis` `carried_balance` | Derived. `DERIVED_ONLY` by construction (V10); guardrails 2 and 6 are `skip`ped with the reason as the message |
| `currency` `currency_basis` | Produced by the F14 inference ladder, not printed. Lumen is the only document that prints a literal `(USD)` |
| `vendor_account_number_normalized` `account_number_normalized` | Computed forms of a printed value |
| `vendor_legal_name` `vendor_phone` `vendor_email` `vendor_website` `billing_group` | Printed, and had working selectors. These left for deliverability, so this is the group that shrinks first when scope widens |
| `tax_id` | **Extraction debt, not a deferral.** U-Pak's H.S.T. number is literal page text and no persona has ever had a selector for it. It stays asserted, and stays failing, in `tests/test_scorecard_coverage.py:EXTRACTION_DEBT` |

`document_identity` and `identity_basis` are derived and **retained**:
`core/contract.py` requires their presence, so dropping them would break
`count(intaken) == count(emitted)`. See spec §5.

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
| `afterExtraction` | ~~`deriveAmountPayable`~~ | **Deferred** — `derive_amount_payable` (F1), EDCO. No persona's `adjust` list calls it |
| `afterExtraction` | ~~`runArithmeticCrosschecks`~~ | **Deferred** — the three F8 checks |
| `afterExtraction` | ~~`inferCurrency`~~ | **Deferred** — CAD from `H.S.T.` + ON postal code (F14). `currency` was never ink on the page |
| `afterExtraction` | `collectReferences` | Ordered alternatives, provenance, dedupe |
| `beforeConfidenceGate` | `northstarThresholds` | §6 |
| `beforeEmit` | `attachAllocationMetadata` | `service_location`, `sub_account[]` |
| `onRegenTrigger` | `excludeAnnotatedFromGold` | Annotated docs never enter the gold set (F3) |
| — | ~~`applyBillingConventions`~~ | **Deferred** — supplies `prior_balance_basis`, a derived classification. `conventions.py` stays in the tree |

Several rows in this table describe where the *spec* put a hook rather than where
the implementation put it: `detectFlattenedAnnotations` and `assignPageRoles` are
generic and live in `s2_filter`, `northstarThresholds` is `ConfidenceGate`
reading `ctx.pack.thresholds`, and `attachAllocationMetadata` is already on the
record. **`src/docintel/packs/northstar/hooks.py`'s module docstring is the
authority** — it maps every spec row to where it actually lives, and it is
maintained with the code.

The four struck-through rows are deferred by the printed-fields-only narrowing
(spec `docs/superpowers/specs/2026-07-28-printed-fields-only-design.md` §5). The
implementations are all still in the tree; nothing calls them.

---

## 6. Confidence thresholds

**Provisional — parked with the business per the spec's open questions.** Set here so the gate is
testable from day one; expect these numbers to move.

| Field | Threshold | Rationale |
|---|--:|---|
| `total_printed` `please_pay` | 0.95 | A wrong total is a wrong payment |
| `current_charges` `prior_balance` | 0.95 | Both feed the payable a downstream consumer computes |
| `invoice_number` | 0.92 | Dedup key |
| `payments_credits` | 0.92 | |
| `vendor_name` `remit_payee` `bill_to_name` | 0.90 | Downstream resolution can recover from near-misses |
| `vendor_account_number` `account_number` | 0.90 | |
| `invoice_date` `bill_date` `due_date` | 0.88 | |
| `reference_list[]` | 0.85 | A list; downstream matching tolerates extras |
| `subtotal` `tax_amount` `discount_amount` `payment_terms` | 0.85 | |
| match keys (`customer_po` `seal_number` `bol_number`) | 0.85 | |
| `service_location` `remit_address` `bill_to_address` | 0.80 | Allocation hint, human-correctable |
| `vendor_address` | 0.75 | Lowest — the most layout-dependent block on the page |
| line-item rows | 0.85 | |
| ~~`amount_payable`~~ | ~~0.95~~ | **Deferred.** Nothing prices a value nothing produces; the row is out of `thresholds.py` |

**Overrides**
- `tags` contains `has_flattened_annotations` → **review flag regardless of confidence**.
  Live, and the only forced-review tag: `s7_gate.DEFAULT_FORCED_REVIEW_TAGS`.
- ~~`tags` contains `mixed_sign` → require the line-sum check to pass, or review.~~
  **Deferred.** The `mixed_sign` tag is still emitted (`ladder.py`), but
  `crosscheck_line_sum` is not in any persona's `adjust` list, so there is no
  line-sum verdict to gate on. Re-enabling the crosschecks restores this.
- `text_source == ocr` → apply `ocr_source ×0.90`; do not raise thresholds (that would double-count).

`arith_balance_mismatch` is in `s7_gate.FORCING_MODIFIERS` and the gate machinery
for it is intact and tested — but the only two ops that emit it
(`grammar/ops/crosscheck.py`, `grammar/ops/derive.py`) are deferred, so **no
corpus document can currently reach it.** That is why U-Pak no longer routes to
review; see §7.

---

## 7. Per-document expectations

What each corpus document must produce. Full values in [`../corpus/gold/`](../corpus/gold/).

**The `amount_payable` column below is the gold expectation, not current output.**
No Northstar document emits a payable today — the derivation is deferred (§2).
The `total_printed` column is what the pipeline actually transcribes, and on EDCO
those two numbers differ by $298.34.

| Document | `doc_type` | `total_printed` (emitted) | `amount_payable` (gold; **deferred**) | Gold routing | Measured lane |
|---|---|--:|--:|---|---|
| D.T.S.S. `6060` | `standard_invoice` | 699.00 | 699.00 | **High** — clean, native text | **high** ✓ |
| Veritiv `715-33905296` | `standard_invoice` | 4,908.00 | 4,908.00 | **High** — `early_pay_discount` tag | medium |
| Complete Beverage `32930` | `invoice_with_attachment` | 1,177.70 | 1,177.70 | **Medium** — OCR-only + handwritten support page | **medium** ✓ |
| Federal Recycling `1330123` | `contra_invoice` | 481.20 | 481.20 | **Review, forced** — flattened annotations | **review** ✓ |
| U-Pak `4378107` | `standard_invoice` | 14,740.85 | **null** | **Review** — `arith_balance_mismatch`, −48.92 unexplained | medium |
| EDCO `077087` | `standard_invoice` | **367.96** | **69.62** | **High** — closure verified | medium |

**EDCO is the F1 trap and it is currently unguarded by this pack.** The record
carries the printed 367.96; the 69.62 that is actually payable is nowhere on it.
The derivation that produced 69.62 is intact and its unit tests still pass — it
is simply not registered, and GUARDRAIL 2 (`tests/test_f1_antiregression.py`) is
`skip`ped with that as the reason. Extraction transcribes; interpreting the
$298.34 gap is downstream's job under this design.

**U-Pak no longer routes to review.** Its gold routing depends on
`arith_balance_mismatch`, and nothing emits that modifier while the crosschecks
are deferred (§6). The forced-review machinery is intact — Federal Recycling
still routes correctly, because flattened-annotation detection is generic and
was never part of the narrowing.

So of the two documents that *should* route to review for the right reason — a
document a human has already annotated, and a document whose arithmetic genuinely
does not close — **only the first still does.** The second is a known consequence
of the narrowing rather than a gate bug, and it comes back with the crosschecks.
