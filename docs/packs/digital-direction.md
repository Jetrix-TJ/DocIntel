# Pack: Digital Direction — telecom expense management

**Domain:** carrier bills for managed clients (Clyde Companies et al.), processed for telecom expense
management and chargeback.

**Corpus evidence:** documents 7–10 in [`../corpus-analysis.md`](../corpus-analysis.md) — Centracom,
Comcast, Windstream, Lumen.

**Defining characteristic:** every carrier lays out its bill differently, most print **no invoice
number at all**, and the headline `Total Amount Due` routinely includes a prior balance. The riskiest
document in the entire corpus is in this pack.

---

## 1. What makes this pack different from Northstar

| | Northstar AP | Digital Direction telecom |
|---|---|---|
| Document identity | Invoice number, always present | **Absent on 3 of 4** — account + period |
| Billing rhythm | Per transaction / shipment | Monthly, recurring, same account forever |
| Headline total | Usually the payable | **Routinely includes prior balance** |
| Match key | Buried in free text | The account / circuit number, printed plainly |
| Persona churn | New vendors constantly | Few carriers, but each redesigns its template |
| Page count | 1–5 | 4–10, mostly per-line detail |
| Cost allocation | Per-shipment site | Per **circuit / service location** — the core product |

The consequence: personas here are **long-lived and high-volume**, which is exactly the case the fast
lane was designed for. It also means a rule regression on one carrier persona affects every bill from
that carrier — so champion/challenger regeneration (spec Part 3) matters more here than in AP.

---

## 2. Document types

| # | `doc_type` | Signal | Evidence |
|---|---|---|---|
| 1 | `credit_memo` | `credit memo` / `adjustment notice` title | — |
| 2 | `disconnect_notice` | Suspension/disconnect language **and** no current-charge block | — |
| 3 | `telecom_bill` | **default** — a payable block plus service detail | all four |

> **Ladder-order note — the Centracom trap.** Centracom's page 1 is titled `Account Summary` and the
> word *"statement"* appears twice (`Balance from last statement`). A `statement_of_account` signal
> placed above the default would misclassify it and run the wrong persona's rules — precisely the
> failure the spec's gate-and-classifier eval exists to catch (F9).
>
> **Rule: a document with a payable amount and service line items is a bill, whatever its header
> says.** This pack therefore has *no* `statement_of_account` type at all. If one is ever needed it
> must require the **absence** of a current-charges block.

### Tags

| Tag | Trigger | Evidence |
|---|---|---|
| `prior_balance_present` | `prior_balance != 0` | **Centracom (20,123.80)** |
| `prior_balance_cleared` | Prior present but netted to zero by a payment | Comcast, Windstream, Lumen |
| `past_due` | Dunning block / aging | Centracom |
| `multi_brand_sender` | Alias table collapsed ≥2 printed names | Lumen (3), Windstream (2) |
| `no_invoice_number` | Identity fell back to account+period | Centracom, Comcast, Windstream |
| `promo_content` | Page 1 has a large image/ad block | Windstream |
| `has_scanline` | Remittance OCR-A line present | all four |

Note that `prior_balance_cleared` fires on **three of four** documents. That is the F1 illusion made
explicit as a tag: the pipeline should record that it *checked* and found the prior netted out, rather
than never looking.

---

## 3. Field set

### Identity — the part that differs most from AP

| Field | Notes |
|---|---|
| `account_number` | Required. `strip_internal_whitespace` — Comcast prints `8495 44 462 0365242` |
| `invoice_number` | **Optional.** Present only on Lumen (`752233001`) |
| `bill_date` | Required. `Bill date` · `Invoice date` · `Bill Date:` |
| `service_period` | `Services from Dec 14, 2025 to Jan 13, 2026` (Comcast) |
| `document_identity` | Derived: `invoice_number ?? account_number + "|" + bill_date_iso` (F6) |
| `identity_basis` | `invoice_number` \| `account_period` |
| `telephone_number` | Secondary identity — Windstream `918-653-3103` |
| `circuit_id` | Centracom `Special Circuit: 4351003276` |

### Amounts — the F1 core

All four are **required** on every bill, because the whole point is that they differ:

| Field | Anchors observed |
|---|---|
| `prior_balance` | `Previous Balance` · `Previous balance` · `Previous Bill` · `Previous Statement Balance` · `Balance from last statement` · `Previous Balance Due` |
| `prior_balance_basis` | Derived, required: `gross` \| `net_of_payments` (F1b) |
| `payments_credits` | `Payments Received` · `Payments/Adjustments thru MM/DD` · `Payment Received - Thank You!` · `Credit Card Payment` — **always stored negative** |
| `current_charges` | `Subtotal Current Charges` · `Current Charges` · `Current Charges Due` · `New charges` |
| `total_printed` | `Total Amount Due` · `Amount due` · `Please pay` · `Balance Due Includes Past Due Amount` |
| `amount_payable` | **derived only** (V10) |
| `taxes_and_fees` | `Taxes and fees` · `Internet Taxes, Surcharges, & Fees` |
| `charges[]` | `{label, amount}` — Centracom splits `Internet Charges` / `Special Circuit Charges` |

### Allocation — the product

| Field | Anchors | Why |
|---|---|---|
| `service_location` | `For service at:` · `FOR SERVICE AT:` · service address block | The chargeback key (F13) |
| `bill_to_name` | Header addressee | **Guard** — must resolve to a managed client |
| `remit_payee` | `Make check payable to` · `payable to` | Drives alias resolution (F5) |
| `carrier_canonical` | — | Output of the alias table |

### Dates

`payment_due` / `due_date` — `Payment due` · `Due date` · `Payment Due` · `Due Date:`

Centracom's due date is **`25TH OF THE MONTH`** — not a date at all. Use `date_loose`; pass it through
unparsed with a confidence penalty rather than inventing a day.

---

## 4. Carrier alias table

`beforePersonaLookup`. **Prefer the remittance payee over the letterhead logo** (F5) — the payee is the
legal entity and survives rebrands.

```
lumen | level 3 communications | level 3 communications, llc
  | centurylink                                  → lumen
windstream | kinetic business | kinetic business by windstream
  | oklahoma windstream, llc                     → windstream
comcast | comcast business                       → comcast
centracom                                        → centracom
```

Lumen is the strongest case in the corpus: **three** printed names on one page — the `LUMEN` logo,
*"Invoice of Level 3 Communications, LLC, a CenturyLink company"*, and *"Make check payable to Level 3
Communications, LLC"*. Without the alias table that is three personas, three cold starts, three
independently drifting rule sets for one carrier.

Windstream compounds it with a **state-specific operating entity** (`OKLAHOMA WINDSTREAM, LLC`). Expect
`{STATE} WINDSTREAM, LLC` and match it as a pattern, not just a literal — otherwise every state is a
new persona.

---

## 5. Hooks

| Socket | Function | Purpose |
|---|---|---|
| `afterFilter` | `skipPromoPages` | Region-limit keyword scan away from ad blocks (F9) — Windstream |
| `classifySignals` | `telecomLadder` | §2; deliberately has no statement type |
| `beforePersonaLookup` | `resolveCarrierAlias` | §4, payee-preferred, state-entity pattern |
| `afterExtraction` | **`deriveAmountPayable`** | **The pack's most important function** (F1) |
| `afterExtraction` | `runArithmeticCrosschecks` | `prior − payments + current == total_printed` |
| `afterExtraction` | `crosscheckScanline` | All four bills have one (F7) |
| `beforeConfidenceGate` | `telecomThresholds` | §6 |
| `beforeEmit` | `attachChargebackMetadata` | `service_location`, `circuit_id`, `service_period` |
| `onRegenTrigger` | `requireTwoBillingCycles` | See below |

**`requireTwoBillingCycles`.** Telecom bills are monthly and their content varies (usage, one-off
charges) while their layout does not. A single low-confidence bill is weak evidence of rule drift; two
consecutive months is strong evidence. Gating regeneration on two cycles avoids paying the agent to
regenerate healthy rules because one month had an unusual charge — the AP-oriented "pile-up" trigger
(spec Part 3) is too twitchy for a monthly rhythm.

---

## 6. Confidence thresholds

**Provisional**, parked with the business.

| Field | Threshold | Rationale |
|---|--:|---|
| `amount_payable` | 0.97 | Highest in either pack. Centracom is a $20k error waiting to happen |
| `current_charges` | 0.95 | `amount_payable` is derived from it |
| `prior_balance` | 0.95 | A missed prior balance silently reintroduces the F1 bug |
| `total_printed` | 0.93 | Scanline-corroborated on all four |
| `account_number` | 0.95 | The identity key when there is no invoice number |
| `bill_date` | 0.93 | Also part of the identity key |
| `service_location` | 0.85 | The chargeback key; human-correctable |
| `circuit_id` | 0.85 | |
| `taxes_and_fees` | 0.85 | |

**Overrides**
- `prior_balance` missing **and** any prior-balance anchor text present on the page → **review**. This
  is the asymmetry that matters: *failing to find* a prior balance is far more dangerous than finding a
  wrong one, because the failure mode is a silent overpayment.
- `arith_balance_mismatch` → review, `amount_payable = null`, never a guess.
- `identity_basis == account_period` **and** `bill_date` confidence < 0.93 → review. A weak date makes
  the identity key weak, and downstream dedup depends entirely on it.

---

## 7. Per-document expectations

| Document | `total_printed` | `prior_balance` | basis | carried | `current_charges` | `amount_payable` | Routing |
|---|--:|--:|---|--:|--:|--:|---|
| **Centracom** `0384043574` | 33,876.40 | **20,123.80** | `net_of_payments` | **20,123.80** | 13,752.60 | **13,752.60** | **High** — trap correctly derived |
| Comcast `8495 44 462 0365242` | 221.11 | 212.87 | `gross` | 0.00 | 221.11 | 221.11 | High |
| Windstream `041069076` | 1,230.14 | 1,231.74 | `gross` | 0.00 | 1,230.14 | 1,230.14 | High |
| Lumen `5-QXH7QKM7` | 248.09 | 249.84 | `gross` | 0.00 | 248.09 | 248.09 | High |

The `basis` column is load-bearing. CentraCom's printed prior is already net of a $24,120.20 payment;
the other three print a gross prior alongside a signed credit that zeroes it. One formula cannot serve
both — see F1b.

All four should route **High** — but only because `derive_amount_payable` works. Without it, three
still route High with correct values and Centracom routes High with a value that is **$20,123.80
wrong**. It would look like a 100%-passing pack.

**This is the single most important test in the repository.** It is also the one most likely to be
"simplified" away by someone who notices that `total_printed == current_charges` on three of the four
sample bills.

### The regression test that must never be deleted

```
GIVEN Centracom_0384043574_01012026_BILL.pdf
WHEN  processed by the digital-direction pack
THEN  total_printed   == 33876.40
AND   prior_balance   == 20123.80
AND   current_charges == 13752.60
AND   amount_payable  == 13752.60     # NOT 33876.40
AND   payable_basis   == "current_charges"
AND   review_flag     == false        # closure verified: 13752.60 + 20123.80 == 33876.40
```
