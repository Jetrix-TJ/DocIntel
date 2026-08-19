# Corpus Analysis — the 10 documents in `docs/`

**Purpose:** turn the sample documents into concrete, testable requirements before any code is
written. Every finding below cites the document and value it came from.

Companion to [`architecture/pipeline-v2.md`](architecture/pipeline-v2.md). Where a finding requires a
change to that spec, it is marked **`Δ SPEC`**.

---

## 0. The headline finding

**A naive implementation scores 90% on this corpus and is catastrophically wrong on the largest
invoice in it.**

The obvious approach — find the biggest, boldest currency value near a "Total Amount Due" label — gets
the right payable amount on 7 of 10 documents. It fails on three, and the worst failure is the
highest-dollar document in the set:

| Document | Printed headline total | What is actually payable | Error |
|---|---:|---:|---:|
| `Centracom_0384043574` | **$33,876.40** | **$13,752.60** | **+$20,123.80** |
| `EDCO 77087APR25` | $367.96 | $69.62 | +$298.34 |
| `U-PAK 4378107` | $14,789.77 | $14,740.85 | +$48.92 |

Three of the four telecom bills (Comcast, Windstream, Lumen) *happen* to have a prior balance that
nets to zero, so headline total == payable on those. That is what makes this trap so dangerous: the
naive rule looks like it works, and the corpus rewards it, right up until the month a customer
doesn't pay in full.

**Consequence for the build:** the `afterExtraction` current-charge normalization is not a
nice-to-have pack refinement. It is a launch blocker, and it needs its own eval.

---

## 1. Corpus at a glance

| # | Document | Vendor (letterhead) | Proposed `doc_type` | Pages | Text layer | Payable |
|---|---|---|---|--:|---|--:|
| 1 | `_AP Invoice 6060DTSS … D.T.S.S. Inc.` | D.T.S.S., Inc. | `standard_invoice` | 1 | native (474 ch) | 699.00 |
| 2 | `_AP Invoice 715-33905296 … Veritiv` | Veritiv Operating Company | `standard_invoice` | 1 | native (2,392) | 4,908.00 |
| 3 | `_AP Invoice 32930 Complete Beverage Destruction` | Complete Beverage Destruction, LLC | `invoice_with_attachment` | 4 | **NONE (image)** | 1,177.70 |
| 4 | `CONTRA ONLY … Federal Recycling 1330123` | Federal Recycling & Waste Solutions | `contra_invoice` | 1 | **NONE (image)** | 481.20 |
| 5 | `CANADIAN WITHOUT NOTES U-PAK 4378107` | U-Pak Disposals (1989) Ltd | `standard_invoice` | 5 | native (6,266) | 14,740.85 |
| 6 | `EDCO 77087APR25 …` | EDCO Waste & Recycling Service | `standard_invoice` | 1 | native (1,125) | 69.62 |
| 7 | `Centracom_0384043574_01012026_BILL` | CentraCom | `telecom_bill` | 10 | native (21,411) | 13,752.60 |
| 8 | `Comcast_8495 44 462 0365242_12092025_BILL` | Comcast Business | `telecom_bill` | 6 | native (3,634) | 221.11 |
| 9 | `Windstream_041069076_07222025_BILL` | Kinetic Business by Windstream | `telecom_bill` | 4 | native (10,783) | 1,230.14 |
| 10 | `Lumen - 5-QXH7QKM7` | Lumen / Level 3 Communications | `telecom_bill` | 6 | native (14,034) | 248.09 |

Domain split: **1–6 = Northstar Recycling** (vendor AP), **7–10 = Digital Direction** (telecom
expense). Both packs from Part 5 of the spec are represented.

---

## 2. Measured facts

Measured with `pdftotext`/`pdfplumber`, not estimated:

| Fact | Value | Why it matters |
|---|---|---|
| Documents with **zero** text layer | **2 / 10 (20%)** | OCR is a day-one dependency, not hardening. |
| …and both of those **render crisply** | yes | You cannot infer "needs OCR" from visual quality. A flattened digital invoice looks identical to a native one. |
| Documents with a machine-readable remittance scanline | 5 / 10 | Free ground-truth cross-check (§F7). |
| Documents where headline total ≠ payable | 3 / 10 | §0. |
| Documents with negative line items | 4 / 10 | Never `abs()` (§F4). |
| Documents with **no invoice number at all** | 3 / 10 | Identity must be composite (§F6). |
| Documents whose total is **not on page 1** | 1 / 10 (U-PAK) | `region: last-page` required (§F9). |
| Documents where line items sum exactly to the total | 5 / 5 checkable | Cheapest confidence signal available (§F8). |
| Median pages | 4 | Multi-page is the norm, not the exception. |
| Multi-party documents (bill-to ≠ service-location) | 5 / 10 | `service_location` is a required field (§F13). |

---

## 3. Findings and requirements

### F1 — `Total Amount Due` is a label, not a promise · **launch blocker**

**Evidence.** Centracom page 1 prints, in this order:

```
Subtotal  Current Charges     $13,752.60
Previous Balance             $20,123.80
Total Amount Due            $33,876.40
```

EDCO prints `Amount Due 367.96` in the largest box on the page, while the line-item table reads
`BALANCE FORWARD 298.34` / `CURRENT CHARGES: 69.62`. The filename — written by a human — says
*"current charges can be misleading, paying $69.62."*

**What breaks.** Paying the headline total double-pays a prior balance. On Centracom that is
$20,123.80 on one document.

**Requirement.**
- Capture `total_printed` **and** `current_charges` **and** `prior_balance` as three separate fields,
  always. Never one blended "total".
- `amount_payable` is **derived**, never read: `prior_balance` present and non-zero →
  `amount_payable = current_charges`.
- If the three do not reconcile (`prior + current == printed`, ±0.01), **review flag** — do not guess.
- Anchors observed in the wild for current charges, in priority order:
  `Subtotal Current Charges` · `CURRENT CHARGES:` · `Current Charges` · `Current Charges Due` ·
  `New charges`.

**Lands at:** `afterExtraction` hook, `adjust` op `derive_amount_payable`. Both packs register it.
Needs a dedicated eval — see §5.

#### F1b — the printed prior balance is not always the carried prior balance

Found while validating the gold set, and it is the same bug one level down.

Comcast, Windstream and Lumen print a **gross** prior balance plus a separate signed payment line:

```
Previous balance                      212.87
Credit Card Payment Dec 09, 2025    -212.87 cr     ← Comcast
```

CentraCom prints `Previous Balance Due` **already net** of payments:

```
Balance from last statement         44,244.00
Payments Received                   24,120.20
Previous Balance Due               $20,123.80      ← already net
```

A single formula `prior + current == total` therefore cannot be right for both. Applied to Comcast it
computes `212.87 + 221.11 = 433.98` against a printed `221.11` and reports a false mismatch; applied
to CentraCom with payments subtracted again it double-counts $24,120.20.

**Requirement.** Every document with a prior balance carries an explicit
`prior_balance_basis: "gross" | "net_of_payments"`, and the **carried** balance is:

```
gross            →  prior_balance + payments_credits   (payments stored negative)
net_of_payments  →  prior_balance                      (as printed)
```

`derive_amount_payable` keys off the **carried** balance. If `prior_balance_basis` cannot be
determined, that is a review flag — not a default. Double-subtracting a payment yields a payable that
is too *low*, which is exactly as wrong as F1's too-high one and considerably harder to spot.

Store `payments_credits` with a consistent negative sign at extraction time, so `cr` suffixes
(Comcast), `CR` suffixes (Windstream), parentheses (Lumen) and unsigned columns (CentraCom) all
normalize to one convention before any arithmetic runs.

---

### F2 — 20% of the corpus is image-only, and it doesn't look like it

**Evidence.** `pdfplumber` reports `chars=0, images=1` for Federal Recycling and `chars=0, images=4`
for Complete Beverage Destruction. Both render as clean, sharp, digitally-typeset invoices. Neither
yields a single character to a text-layer parser.

**What breaks.** Any Level 1.5 keyword gate that treats "no keywords found" as "not a document" drops
20% of this corpus silently — including the mixed-sign contra invoice, the hardest document in it.

**Requirement.** Confirms spec Stage 2 exactly as written: *"no keywords ≠ skip"*, and OCR runs **once**
at Level 1.5 with its output carried in the job context. Add a measurable gate:
`chars_per_page < 50 → route to OCR`, recorded on the record as `text_source: native | ocr`.

**`Δ SPEC`** — `text_source` is not in the Stage 8 contract. Add it. Every downstream confidence
question ("why is this field weak?") starts with "was this OCR?".

---

### F3 — Human annotations get flattened into pixels and become indistinguishable from printed data

**Evidence.** Federal Recycling `1330123` carries at least six human annotations: purple highlights
over amounts, and green/blue text boxes containing *different reference numbers* than the ones printed
beside them. Row 1 prints `REFERENCE 2436687`; a green box next to it reads `2436818`. Two more boxes
carry conversational text: *"Hi Chloe, appears you need for your b/s updates. TY DDarling 6/6"* and
*"Yes and I added a few to update what you had, thanks! - CGS 6/9"*.

`pdfplumber` reports **`annots=0`** for this file. The annotations are not PDF annotation objects —
they were flattened into the page image. There is no annotation layer to strip.

**What breaks.** OCR will read `2436687` and `2436818` with equal authority and no provenance. A
`capture: all_matches` reference rule will happily emit both into `reference_list[]`, and the
downstream matcher will try to match an invoice against a reference number a human hand-wrote as a
*correction* to a different row. Worse, the conversational text contains a date (`6/6`, `6/9`) that a
date pattern may capture as an invoice date.

**Requirement.**
- Detect flattened annotation overlays as a **tag**, not a value: colored-fill regions overlapping the
  table body, or text whose bounding box overlaps another text run.
- Tag `has_flattened_annotations` → **force review flag**, regardless of extraction confidence. Never
  fast-lane an annotated document.
- Never fast-lane *this persona* on the strength of an annotated sample: annotated documents are
  **excluded from the gold set** and from draft→stable promotion evidence.

**`Δ SPEC`** — The spec's annotation story assumes PDF annotation objects that can be stripped at
`beforeIntake`. Flattened annotations defeat that. This is a new, distinct requirement.

> The filename of document 5 is `CANADIAN WITHOUT NOTES U-PAK …` — implying a companion copy *with*
> notes exists. Annotated-vs-clean pairs of the same invoice are apparently routine in this workflow.
> Treat annotation as an expected input condition, not an anomaly.

---

### F4 — Mixed-sign invoices are normal, and the sign is the business meaning

**Evidence.** Federal Recycling `1330123` — a *contra* invoice, per its filename *"CONTRA ONLY
Everything already on AR"*:

| Description | Qty | Price | Amount |
|---|--:|--:|--:|
| OCC | 2.495 ST | −40.00/ST | −99.80 |
| HAUL FEE | | 200.00 | 200.00 |
| OCC | 2.015 ST | −40.00/ST | −80.60 |
| HAUL FEE | | 200.00 | 200.00 |
| OCC | 3.425 ST | −40.00/ST | −137.00 |
| Baling Wire Sales | | 75.00 | 75.00 |
| Baling Wire Sales | | 75.00 | 75.00 |
| HAUL FEE | | 200.00 | 200.00 |
| OCC | 3.785 ST | −40.00/ST | −151.40 |
| HAUL FEE | | 200.00 | 200.00 |
| **TOTAL** | | | **481.20 USD** |

Also: Complete Beverage Destruction has `−65.00`, `−22.00`, `−9.60` rebate lines inside a positive
invoice; U-PAK has `CARDBOARD WEIGHTS … −40.500 … −57.51`.

The negative lines are **commodity credits** (recycled material Northstar is owed for); the positive
lines are **service fees**. Netting them is the whole point of the document.

**Requirement.**
- Currency patterns must accept leading `−`, parenthesised `(249.84)` (Lumen uses this form for
  payments received), and trailing `cr` (Comcast: `-212.87 cr`).
- **Never** `abs()`. Never "correct" a negative total.
- Tag `mixed_sign` when line-item signs differ. This is a *handling hint*, never a type change — per
  spec Stage 3.
- `contra_invoice` is a distinct `doc_type` in the Northstar pack, detected by *"all commodity lines
  negative"* + a contra/credit label, **not** by a negative grand total (Federal Recycling's total is
  positive: +481.20).

---

### F5 — One carrier, up to three printed names

**Evidence.** Lumen `5-QXH7QKM7` page 1 carries all of:
- logo: **LUMEN**
- body text: *"Invoice of Level 3 Communications, LLC, a CenturyLink company"*
- remittance: *"Make check payable to Level 3 Communications, LLC"*

Windstream: letterhead **kinetic business by windstream**, remittance *"payable to OKLAHOMA
WINDSTREAM, LLC"*, footer *"Windstream"*. Filename says `Windstream`.

**What breaks.** A fingerprint built from the printed vendor name creates three personas for one
carrier — and each starts cold, pays the agent again, and holds its own drifting rules.

**Requirement.** The pack ships a **carrier alias table** consumed at `beforePersonaLookup`:

```
level 3 communications | centurylink | lumen   → lumen
kinetic business | oklahoma windstream         → windstream
```

Normalize before the key is built. Confirms the spec's `beforePersonaLookup` socket and Part 5's
*"one carrier arrives under two brand names"* — the real count is three.

**Where the name comes from** matters: prefer the **remittance payee** ("make check payable to") over
the letterhead logo. The payee is the legal entity and is far more stable than marketing branding.

---

### F6 — Three of ten documents have no invoice number

**Evidence.** Comcast, Windstream and Centracom print no invoice/document number anywhere. Their
identity is `account_number + bill_date`:

| Document | Invoice number | Account number | Bill date |
|---|---|---|---|
| Comcast | — | `8495 44 462 0365242` | Dec 09, 2025 |
| Windstream | — | `041069076` (+ tel `918-653-3103`) | July 22, 2025 |
| Centracom | — | `0384043574` | January 01, 2026 |
| Lumen | `752233001` | `5-QXH7QKM7` | September 01, 2025 |

**What breaks.** Downstream dedup is specified to key on "invoice number + vendor" (spec Stage 1).
For 3 of 10 documents that key is null, so every monthly bill from those carriers looks like the same
document — or like no document.

**Requirement.** Emit a composite `document_identity` on the record:

```
invoice_number  ?? (account_number + "|" + bill_date_iso)
```

with `identity_basis: "invoice_number" | "account_period"` so downstream knows which rule produced it.

**`Δ SPEC`** — Stage 8 has no `document_identity` / `identity_basis`. Add both. Without them the
duplicate decision the spec pushes downstream cannot be made for a third of the corpus.

Also: Comcast's account number contains **internal spaces** (`8495 44 462 0365242`) and appears
space-free in the scanline (`8495444620365242`). Normalization op `strip_internal_whitespace` required
before any comparison.

---

### F7 — The remittance scanline is free ground truth · **highest-leverage cheap win**

**Evidence.** The OCR-A line at the bottom of the remittance stub encodes the key fields. Verified on
5 documents:

| Document | Scanline (page 1 footer) | Decodes to |
|---|---|---|
| Lumen | `251001 000000752233001 … 00000024809 2` | due `2025-10-01`, invoice `752233001`, **248.09** ✓ |
| Comcast | `849544462036524200221119` | account `8495444620365242`, **221.11** ✓ |
| Centracom | `03840384043574000033876408` | account `0384043574`, **33,876.40** ✓ |
| Windstream | `7000444000000004106907622507190000012301446` | account `041069076`, **1,230.14** ✓ |
| EDCO | `25600770871000367962` | account `077087`, **367.96** ✓ |

**Requirement.** Add `scanline` as a selector type: locate the last long digit run on the remittance
page, then assert that the already-extracted amount and account appear within it.

- Match → **confidence boost** on `total_printed` and `account_number`. Two independent renderings of
  the same value agreed.
- Mismatch → **confidence penalty**, because OCR or the anchor picked up the wrong number.
- Absent → no effect. Never a requirement.

**Critical caveat.** Centracom's scanline encodes **33,876.40** — the trap value from §F1, not the
payable. The scanline validates **transcription fidelity, not business correctness.** It may only ever
score `total_printed`. Wiring it to `amount_payable` would actively cement the bug.

**`Δ SPEC`** — new selector type; not in the Part 2 grammar.

---

### F8 — Arithmetic closure is the cheapest confidence signal in the system

**Evidence.** Every document with a visible line-item table closes exactly:

| Document | Check | Result |
|---|---|---|
| D.T.S.S. `6060` | 550.00 + 50.00 + 99.00 | = 699.00 ✓ |
| Veritiv | 4,608.45 + 299.55 tax | = 4,908.00 ✓ |
| Veritiv line | 55 RL × 83.7900 | = 4,608.45 ✓ |
| Veritiv discount | 1% × 4,608.45 | = 46.08 ✓ |
| Federal Recycling | all 10 signed lines | = 481.20 ✓ |
| Federal Recycling lines | e.g. 2.495 ST × −40.00 | = −99.80 ✓ (4 / 4) |
| Complete Beverage | all 12 signed lines | = 1,177.70 ✓ |
| Complete Beverage lines | all 12 qty × price | ✓ (12 / 12) |
| EDCO | 298.34 + 69.62 | = 367.96 ✓ |
| Centracom | 140.90 + 0.20 + 13,611.50 | = 13,752.60 ✓ |
| Centracom | 13,752.60 + 20,123.80 | = 33,876.40 ✓ |
| Centracom prior | 44,244.00 − 24,120.20 | = 20,123.80 ✓ |
| Comcast | 212.87 − 212.87 + 217.89 + 3.22 | = 221.11 ✓ |
| Windstream | 1,231.74 − 1,231.74 + 1,230.14 | = 1,230.14 ✓ |
| Lumen | 249.84 − 249.84 + 0.00 + 248.09 | = 248.09 ✓ |
| U-PAK | 8,119.44 + 1,218.04 + 2,342.42 + 784.18 + 2,325.69 | = 14,789.77 ✓ |

**And the one that does not close is the one that needs a human.** U-PAK: `Total Invoice 14,789.77`
but `Please Pay $14,740.85`, with aging showing `CURRENT 14,740.85` and `30/60/90 = 0.00`. A
**−48.92** discrepancy with no prior balance to explain it. The filename (*"WITHOUT NOTES"*) implies
the explanation lived in a human note on another copy.

**Requirement.** Run three cross-checks at Stage 6 and feed them into confidence as named modifiers:

| Check | On mismatch |
|---|---|
| `Σ line_items == subtotal` | `×0.85` `arith_lines_mismatch` |
| `subtotal + tax + surcharges == total_printed` | `×0.85` `arith_total_mismatch` |
| `prior + current == total_printed` | `×0.80` `arith_balance_mismatch` → **review flag** |

This is pure arithmetic on already-extracted values: no AI, no extra parse, near-zero cost. It is the
single best-value signal the corpus offers, and it correctly isolates U-PAK — the one document a human
genuinely must look at — from the nine that are safe.

**`Δ SPEC`** — the spec's confidence scoring is per-field match quality only (Part 2, step 4).
Cross-field arithmetic consistency is a second, independent scoring input. Add it.

---

### F9 — The total may not be on page 1, and page 1 may be an advertisement

**Evidence.** U-PAK's `Please Pay $14,740.85` is on **page 5 of 5**; page 1's `Please Pay` cell is
blank. Windstream devotes the entire left half of page 1 to a *"Do More with Go Kinetic Business"*
advertisement with app-store badges and a QR code. Centracom page 1 is an `Account Summary` — the word
*"statement"* appears twice (`Balance from last statement`).

**What breaks.**
- Region vocabulary implied by the spec (`top-right`, `last-table-row`) is page-1-centric. It cannot
  address "the totals block on the final page."
- The Stage 3 signal ladder lists *"statement pattern"* **above** the invoice default. Centracom would
  match a naive statement signal and be misclassified — running the wrong persona's rules, exactly
  the failure the spec's gate-and-classifier eval is meant to catch.
- Marketing copy on page 1 pollutes keyword gating and wastes vision-model tokens.

**Requirement.**
- Add `last-page` and `page:N` to the region vocabulary; make `totals-block` a named region resolved
  by anchor search across the **last two** pages, not page 1.
- Statement signals must require a *statement-specific* marker (no line items + "statement of
  account" title), and must rank **below** "has a current-charges/amount-due block". A document with
  a payable amount and service line items is a bill, whatever its header says.
- Region-limit the Level 1.5 keyword scan to the top ~40% of page 1 and exclude regions dominated by
  images, so advertising copy cannot fire a signal.

---

### F10 — One PDF is one invoice plus three pages of scanned, handwritten backup

**Evidence.** `_AP Invoice 32930 Complete Beverage Destruction`, 4 pages, 0 chars:
- p1 — the invoice (12 line items, Balance Due $1,177.70), digitally typeset but flattened
- p2 — a **handwritten, skewed, photocopied Bill of Lading** (`BOL 10-21-25-01`, `Seal 5951119`,
  carrier `R&L`, trailer `35243`, `20000` lbs, signed)
- p3–4 — further backup

The invoice's own reference keys `SEAL# 5951119` and `BOL# 10-21-25-01` appear on p1 **and** are
corroborated on the handwritten p2.

**What breaks.** Spec Stage 1 has exactly one multi-page concept: *batch PDFs* — several **invoices**
concatenated, flagged for review, not split. This is the opposite shape: **one** invoice with
supporting attachments. Flagging it as a batch sends a perfectly extractable document to a human for
no reason. Conversely, treating all 4 pages as one document body means the handwritten BOL's noise
competes with the invoice's clean values.

**Requirement.**
- Classify a `page_role` per page: `primary | supporting | unknown`. Heuristics: a page carrying the
  invoice-number anchor and a totals block is `primary`; pages with high skew, handwriting, or
  photocopy noise and no totals block are `supporting`.
- `doc_type: invoice_with_attachment` when exactly one `primary` page is found alongside `supporting`
  pages — **process it normally**, extracting from the primary page.
- Two or more `primary` pages with **different** invoice numbers → *that* is a batch. Flag per spec.
- Run reference patterns across **all** pages including supporting ones — the BOL is where match keys
  are corroborated — but never take field *values* from a supporting page.
- Handwriting or skew detected on the primary page → never fast-lane; force the vision path.

**`Δ SPEC`** — this is a new `doc_type` and a new per-page concept. The spec's batch heuristic as
written would misroute this document.

---

### F11 — Reference keys hide in five different places, with five different shapes

**Evidence.**

| Document | Where the match key lives | Shape |
|---|---|---|
| D.T.S.S. `6060` | inside every line-item description | `NS # 2561194` (same value, 3 rows) |
| Veritiv | the **`Customer P.O.`** column | `Northstar# 2542693` |
| Federal Recycling | a dedicated `REFERENCE` column | `2436687`, `2436820`, `2436821`, `2436823` — bare 7-digit |
| Federal Recycling | *flattened annotations* | `2436818`, `2436820`, `2436821`, `2469435`, `2469427` |
| U-PAK | `WORK ORDER#:` sub-rows, repeated per service group | `4342903`, `4342904`, `4348255`, `4348256`, `4355256` |
| Complete Beverage | `SEAL#` / `BOL#` header fields + handwritten p2 | `5951119`, `10-21-25-01` |
| Centracom | `Special Circuit:` on the remittance stub | `4351003276` |

**Requirement.** Confirms `capture: all_matches` → `reference_list[]` emphatically. Additionally:
- A pack registers an **ordered list of alternative reference patterns**, not one. Northstar needs at
  least: `NS\s?#\s?(\d{7})`, `Northstar#\s*(\d{7})`, `WORK ORDER#:\s*(\d{7})`, bare `\d{7}` in a
  column headed `REFERENCE`, `SEAL#`, `BOL#`.
- Emit each hit as `{value, source_field, page, pattern_id}` — not a bare string. Downstream matching
  needs to know a key came from a `Customer P.O.` field versus free text versus a flattened
  annotation.
- Deduplicate preserving first-seen order.
- A bare `\d{7}` pattern is only safe when scoped to a column — unscoped it will match phone numbers,
  zip+4, and account fragments.

**`Δ SPEC`** — `reference_list` is specified as a list of strings. Make it a list of objects. The
provenance is what makes F3's annotation values safely ignorable downstream.

---

### F12 — Duplicate anchors on the same page — a hazard and a free check

**Evidence.** Nearly every document prints its key fields **twice**: once in the body, once on the
detachable remittance stub.

- Veritiv: `Invoice No.` + `Invoice Date` appear in the top block **and** the body table
- Lumen: `Billing Account Number`, `Invoice Number`, `Payment Due`, `Total Amount Due` — all twice
- Comcast / Windstream / Centracom: account number and amount due appear in header and stub

**Requirement.**
- **Region is mandatory** on any selector whose anchor is not provably unique. A bare anchor match
  where the anchor occurs more than once is ambiguous → confidence penalty
  `ambiguous_anchor ×0.9`.
- When both occurrences are found and **agree**, that is a second free self-consistency check —
  confidence boost, same mechanism as F7.
- When they **disagree**, review flag. On a remittance document that is a genuine anomaly.

---

### F13 — Three parties per document, and the one you need is not the obvious one

**Evidence.**

| Document | Bill-to (our company) | Service location / end site |
|---|---|---|
| Veritiv | `NORTHSTAR RECYCLING COMPANY LLC` (SOLD TO) | `SHEARER'S BREWSTER, 692 N Wabash Ave, Brewster OH` (SHIP TO) |
| U-PAK | `NORTHSTAR RECYCLING COMPANY LLC` | `SHEARER'S FOOD CANADA INC N.S, Guelph ON` (Location) |
| Complete Beverage | `NorthStar Recycling Company, LLC` + `Refresco, Acline` | `R&L / Plant City FL` (from BOL) |
| EDCO | `NORTHSTAR RECYCLING` | `HUNTER INDUSTRIES, 260 S Pacific St, San Marcos CA` |
| Comcast | `Clyde Administration Servi` | `387 S 520 W STE 210, LINDON UT` |
| Centracom | `CLYDE COMPANIES` | (per-circuit, later pages) |

**What breaks.** The letterhead is the vendor; `Bill To` is *us*; the third party is the site the cost
must be allocated to. For telecom expense management, the service location **is** the product — it is
how a bill becomes a chargeback. Extracting only vendor + total produces a record nobody can allocate.

**Requirement.**
- Required fields: `vendor_name` (letterhead / remittance payee), `bill_to_name`, `service_location`.
- `bill_to_name` is a **guard, not data**: if it does not match the operating company, the document was
  misrouted — flag it. Cheap, and catches a whole class of mailbox errors.
- Anchors for service location vary widely: `SHIP TO`, `Location:`, `FOR SERVICE AT:`, `For service
  at:`, `Service Address`. Pack-supplied list.
- Northstar's *"one vendor group → 70+ account identities"* (spec Part 5) shows up concretely as
  U-PAK's nesting: master `Account No. 1 -24136 1` containing
  `** SUB ACCT: 1 - 22335 SHEARER'S FOODS CANADA R/O`. Capture `sub_account[]` as a repeating group.

---

### F14 — Currency is a field, and it is sometimes stated nowhere

**Evidence.** U-PAK is Canadian: `ETOBICOKE, ON`, `GUELPH ON N1G 4N4`, `H.S.T. # 123142812RT0001`,
cheques *"payable to U-Pak Disposals (1989) Ltd"*. The string `CAD` appears **nowhere** in the
document. Federal Recycling, by contrast, suffixes every amount with `USD` explicitly.

**Requirement.**
- `currency` is a required field with an explicit inference ladder: explicit ISO code → currency
  symbol → **tax-regime marker** (`H.S.T.`/`G.S.T.`/`Q.S.T.` → CAD; `VAT` → GBP/EUR) → vendor address
  country → pack default.
- Confidence must reflect which rung fired. Inferred-from-address currency is low confidence by
  construction and should carry a modifier.
- Tag `foreign_currency` when it differs from the pack default. Per spec Stage 3, a tag — never a type
  change.
- Tax capture is not a single field: U-PAK stacks `Subtotal` + `FUEL SURCHARGE 1,218.04` +
  `ENVIRONMENTAL SURCHARGE 2,342.42` + `EFW COMPLIANCE CHRG 784.18` + `H.S.T. 2,325.69`. Capture
  `charges[]` as `{label, amount}` pairs rather than trying to name every surcharge in a schema.
- **Anchor hazard:** the H.S.T. line reads `H.S.T. # 123142812RT0001    2,325.69`. A rule that takes
  "the first number after the anchor" gets the registration number. Require a currency-shaped token.

---

### F15 — Zero-value and no-market-value lines are data, not parse failures

**Evidence.** Complete Beverage, item `8009 - Carrier Stock Bales/Loose`, qty `4,670`, unit price
`0.00`, amount `0.00`, description `NO MARKET VALUE`. U-PAK's `40 YD PACKER - TO EMERALD` rows have an
**empty** `AMOUNT` cell with a populated `TOTAL` of `519.93`.

**Requirement.** Distinguish three states explicitly — `0.00`, empty, and *failed to parse* — and never
collapse them. Dropping the zero-value row breaks the F8 line-sum check; treating the empty `AMOUNT`
cell as a parse failure fires a false low-confidence signal on a perfectly good U-PAK row.

---

### F16 — Dunning furniture is loud, and it is not a document type

**Evidence.** EDCO renders **`PAST DUE`** in ~60pt type across a third of the page, plus a script
watermark *"We'll Take Care Of It"* drawn **inside** the line-item table area (`curves=432`, no
images). Centracom has a `DUE DATE REMINDER` block in caps. U-PAK has `AGE / CURRENT / 30 / 60 / 90`
aging buckets.

**Requirement.**
- Tag `past_due` from these markers. Never a `doc_type` — EDCO is a standard invoice that happens to
  be overdue.
- The overlapping watermark is an OCR contamination hazard specifically in the table region. On
  OCR'd documents, a token that fails all column patterns inside a table cell should be dropped as
  furniture rather than lowering row confidence.
- Aging buckets are a **useful signal for F1**: `30/60/90 = 0.00` with a `Total ≠ Please Pay` gap (U-PAK)
  proves the gap is *not* a prior balance — which is exactly why that document needs a human.

---

### F17 — The filenames are a labelled test set; use them for tests, never for extraction

**Evidence.** The telecom files are systematically named
`{Carrier}_{Account}_{MMDDYYYY}_BILL.pdf` — `Comcast_8495 44 462 0365242_12092025_BILL.pdf` encodes
carrier, account and bill date correctly. The AP files encode invoice number **and** amount:
`_AP Invoice 715-33905296 Veritiv Operating Company 4908.00000.pdf` → invoice `715-33905296`, total
`4908.00`. Verified correct against document content on all four `_AP Invoice` files.

And three filenames encode the trap itself: *"current charges can be misleading, paying $69.62"*,
*"CONTRA ONLY Everything already on AR"*, *"CANADIAN WITHOUT NOTES"*.

**Requirement.**
- Spec Stage 3's *"content only — never the filename"* stands. Filenames are inconsistent across
  senders and trivially wrong when someone re-saves a forwarded copy.
- **But** filename-derived values are excellent as a **cross-check**: agreement → confidence boost,
  disagreement → penalty. Same mechanism as F7 and F12. Record it as
  `filename_crosscheck: agree | disagree | absent`, never as a value source.
- For the gold set (§4), the filenames are free labels. Use them to author expected values, then
  verify by reading the document.

---

### F18 — Early-payment discounts mean "the amount payable" is a function of *when*

**Evidence.** Veritiv: `Terms: 1 % 30 DAYS, NET 31 DAYS`, `Discount Date 09/13/2025`,
`Discount Amount 46.08`, `Total Amount Due 4,908.00`. Pay by 09/13 → 4,861.92. After → 4,908.00.
U-PAK: `PAYMENT TERMS: EOM plus 15`. D.T.S.S.: `Due on receipt`. Complete Beverage: `Net 30`.

**Requirement.** Capture `payment_terms`, `due_date`, `discount_date`, `discount_amount` as separate
fields. Do **not** attempt to compute a date-dependent payable in extraction — that is a business
decision and belongs downstream per the spec's scope boundary. Extraction's job is to surface all four
inputs.

---

### F19 — Every document is a different table, and rows repeat with sub-structure

**Evidence.** Column sets across the corpus share almost nothing:

| Document | Table columns |
|---|---|
| D.T.S.S. | Description · Qty · Rate · Amount |
| Veritiv | Product No. · Description/References · Weight · Qty Ordered · Qty Shipped · Unit Meas · Unit Price · Unit Meas · Extended Price · GP |
| Complete Beverage | Service Date · Item · Description · Qty · Unit Price · Amount |
| Federal Recycling | Date · Trans No. · Reference · Description · Quantity · Price · Amount |
| U-PAK | Date · Description · Quantity · Amount · Total |
| EDCO | Mo · Day · Description · Charges · Payments · Balance |

U-PAK additionally nests: each service group is `WORK ORDER#: nnnnnnn` followed by 2–4 charge rows,
and one row carries its own inline `Sub Total / Taxes / Total` block.

**Requirement.** Confirms the v2 `row_group` selector. Extend it:
- Columns are matched **by header text**, not by index — Veritiv has two identically-labelled
  `Unit Meas.` columns, so index-based extraction is unsafe.
- Support one level of `sub_group` nesting keyed by a repeating anchor (`WORK ORDER#:`).
- A row-group selector must tolerate a variable row count; row count is part of the layout
  fingerprint only as a range, never an equality.

---

### F20 — A contract is a different document family, not an invoice missing its total

**Evidence.** Of 18 real Windstream-carrier documents that processed cleanly during an earlier
corpus sample, 16 were contracts, amendments, or Customer Service Records — none of them bills —
matched to a carrier's billing persona purely because the carrier's name appears on the page, then
run through billing-shaped extraction (total-due, prior-balance logic) that has nothing to
reconcile against. The real Golub Corporation/Windstream relationship (`docs/corpus/contracts/`)
confirms the shape directly: a base Service Agreement (`contract_number`, `effective_date`,
`term_length_months`, a Minimum Monthly Fee) plus a chain of amendments and renewals layered on top
of it over 2020–2025, none of which print a `total_printed`, a line-item charges table, or a prior
balance.

**Requirement.** A `contract` doc_type, with its own field set (identity: account/circuit/contract
number; terms: contracted rate, term start/end, signatory, effective date, a reference back to
whatever contract it supersedes) — distinct from, not a subset of, the billing field set. See
`digitaldirection/fields.py`'s doc_type-aware `fields_for`/etc.

### F21 — One customer relationship carries several contracts at once, layered, not superseding

**Evidence.** The Golub/Windstream relationship's own documents: a 2020 base agreement
(`contract_number 2110613`), a 2022 renewal amendment (`2494434`, explicitly amending 2110613), and
further location-specific amendments (e.g. `2714300`) that reference "the Agreement" collectively
rather than one single prior contract_number. "Latest contract wins" is the wrong model — an
amendment modifies specific terms or specific service locations while everything else in the base
agreement (and any earlier amendment) remains in force.

**Requirement.** Reconciliation (the invoice↔contract matching layer) must resolve which contract
governs a given invoice by effective-date bracketing against the invoice's billing period, not by
picking the most recently dated document — and must escalate rather than guess when precedence is
genuinely ambiguous (`contract_precedence_ambiguous`), the same posture `prior_balance_basis`
already established for a different ambiguity.

### F22 — A contract amendment's own arithmetic is a real, checkable closure too

**Evidence.** Golub's 4G service-addition amendment (2021-02-18) states a per-location rate
($60.00), a location count (137), and a total additional Minimum Recurring Charge ($8,220.00) on
the same page — `60.00 × 137 = 8,220.00` closes exactly, the contract-document analogue of an
invoice's line-item-sum-equals-subtotal check (F8).

**Requirement.** A contract persona's `adjust` ops (or a gold assertion, at minimum, ahead of any
op existing) should be able to state this closure explicitly, the same way `crosscheck_line_sum`
does for a billing table — not because a contract needs to derive a payable, but because a stated
rate that doesn't match its own stated inputs is exactly the kind of authoring/OCR error the
existing crosscheck ops already exist to catch elsewhere.

---

### F20 — Layout variants within one sender are already present

**Evidence.** U-PAK page 1 and page 5 are the *same template* with different content: p1 has a
populated table and a blank `Please Pay`; p5 has an empty table and a populated totals block. Comcast
p1 has a summary box; later pages carry per-service detail. A fingerprint built from "page 1 looks
like X" will diverge on the pages that actually hold the totals.

**Requirement.** Confirms the v2 "persona holds a set of layout variants keyed by fingerprint."
Additionally the layout fingerprint must be **document-level, not page-level**: `page_count` as a
range, `has_table`, header signature from the **first** page, totals-block location as a page role
rather than a page number.

---

## 4. What to build first

Ordered by evidence weight from this corpus.

1. **Gold set for all 10 documents** — the corpus is pre-labelled by its own filenames. This is the
   cheapest possible head start on the spec's *"20–30 hand-labelled documents per domain"*, and it is
   the harness every later step is measured against. See `corpus/gold/`.
2. **The `derive_amount_payable` op + its eval (F1).** Highest-dollar risk in the set. Must exist
   before anything ships.
3. **OCR at Level 1.5 with `text_source` on the record (F2).** 20% of the corpus is unreadable
   without it — including the two hardest documents.
4. **The three arithmetic cross-checks (F8).** Near-zero cost, and they correctly isolate the one
   document that genuinely needs a human.
5. **`reference_list[]` as objects with provenance (F11) + flattened-annotation tagging (F3).** These
   two interlock: provenance is what makes an annotation-sourced reference safely ignorable.
6. **Page roles / `invoice_with_attachment` (F10).** Without it, a clean 4-page document is misrouted
   to a human as a "batch".
7. **The scanline check (F7)** and **filename cross-check (F17)** — both cheap, both scoring-only,
   both easy to get subtly wrong by wiring them to the payable instead of the printed total.

---

## 5. Evals this corpus demands

Beyond the spec's three suites:

| Eval | Assertion | Why this corpus proves it necessary |
|---|---|---|
| **Payable-derivation eval** | `amount_payable` correct on all 10 | 3 / 10 differ from the headline total; a naive rule scores 70% and is wrong by $20k on the largest document |
| **OCR-path parity** | Field accuracy on Federal Recycling + Complete Beverage within tolerance of native-text documents | These two are image-only; if the OCR path is weaker, 20% of volume is silently degraded |
| **Arithmetic-closure eval** | 9 documents close; U-PAK does **not** and must be flagged | Guards against a "fix" that makes the check always pass |
| **Annotation isolation** | No annotation-sourced reference reaches `reference_list` unmarked | Federal Recycling's flattened boxes contradict printed values |
| **Alias collapse** | Lumen/Level 3/CenturyLink → one persona; Kinetic/Windstream → one persona | 3 names and 2 names respectively for one carrier each |
| **Identity fallback** | `document_identity` non-null on all 10 | 3 / 10 have no invoice number |

---

## 6. Summary of spec deltas

| # | Δ to `pipeline-v2.md` | Source |
|---|---|---|
| 1 | Add `text_source: native \| ocr` to the Stage 8 contract | F2 |
| 2 | Add `document_identity` + `identity_basis` to Stage 8 | F6 |
| 3 | `reference_list[]` becomes objects (`value`, `source_field`, `page`, `pattern_id`) | F11 |
| 4 | New `doc_type: invoice_with_attachment` + per-page `page_role` | F10 |
| 5 | Flattened (non-object) annotations as a detected tag → forced review; excluded from gold set | F3 |
| 6 | New selector type `scanline`; scoring-only, bound to `total_printed` never `amount_payable` | F7 |
| 7 | Arithmetic cross-checks as a second, independent confidence input alongside match quality | F8 |
| 8 | Region vocabulary gains `last-page`, `page:N`, `totals-block` | F9 |
| 9 | Statement signals must rank below "has a payable block"; keyword scan region-limited | F9 |
| 10 | `row_group` columns matched by header text; one level of `sub_group` nesting | F19 |
| 11 | Required fields: `current_charges`, `prior_balance`, `total_printed`, `amount_payable` (derived), `currency`, `service_location`, `bill_to_name`, `sub_account[]`, `charges[]` | F1, F13, F14 |
| 12 | `filename_crosscheck` as a scoring signal — explicitly not a value source | F17 |
| 13 | `prior_balance_basis` (`gross` \| `net_of_payments`) required wherever a prior balance exists; `payments_credits` normalized to a negative sign at extraction | F1b |
