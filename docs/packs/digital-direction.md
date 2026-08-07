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
| `prior_balance_present` | Any prior-balance anchor. The conservative default | **Centracom (20,123.80)** |
| `prior_balance_cleared` | Upgraded from `present` when `prior_balance + payments_credits == 0` | Comcast, Windstream, Lumen |
| `past_due` | Dunning block / aging | Centracom |
| `multi_brand_sender` | Alias table collapsed ≥2 printed names | Lumen (3), Windstream (2) |
| `no_invoice_number` | Identity fell back to account+period | Centracom, Comcast, Windstream |
| `promo_content` | Page 1 matches a closed enumeration of Windstream/Kinetic marketing phrases (`go kinetic business`, `gokineticbusiness.com`, `scan the qr code`, `mybusiness.gokinetic.com`, `google play or the app store`) — content-based, no image/char-count heuristic. **Comcast/Lumen/Centracom promotional content cannot be tagged at all, by design**, per the code's own docstring | Windstream |
| `has_scanline` | Remittance OCR-A line present | all four |

Note that `prior_balance_cleared` fires on **three of four** documents. That is the F1 illusion made
explicit as a tag: the pipeline should record that it *checked* and found the prior netted out, rather
than never looking.

**The order of the two rows is load-bearing, and getting it wrong shipped a false
claim.** Classification (`ladder.tags_for`) sees only page text, and page text
cannot tell the two apart: Centracom prints `Payments Received` and still carries
20,123.80. So classification emits `prior_balance_present` on any anchor and
`ladder.retag_prior_balance` upgrades it — never the reverse. A version of this
pack guessed `cleared` from the payment anchor while its refinement hook was
unregistered, and emitted `prior_balance_cleared` on Centracom.

Centracom is also why the upgrade test is `prior + payments == 0` rather than "a
payment was printed": its `prior_balance` is **already net** of the 24,120.20
payment (44,244.00 last statement less the payment), so the payment must not be
subtracted a second time. The other three print a gross prior that the payment
exactly offsets. Same split as §7's `basis` column, decided on printed amounts
instead of a convention table.

---

## 3. Field set

> **Narrowed to printed values.** Everything below is what the pack extracts
> today, which is a strict subset of what this section originally specified. The
> reason, the full list of what left, and how to bring it back are in
> [`docs/superpowers/specs/2026-07-28-printed-fields-only-design.md`](../superpowers/specs/2026-07-28-printed-fields-only-design.md).
> Anchors are unchanged — they were never the thing that was wrong.
>
> A finding from that spec belongs here specifically: **four of this section's
> eight original "Required" fields were not printed values at all.** Three are
> closed-list classifications (`service_type`, `charge_type`, the row-type flag)
> and one is envelope metadata (`invoice_file_name`). They were derivations
> wearing field names, so they left with `amount_payable` rather than with a
> selector.

### `REQUIRED` is not a flat set

```python
REQUIRED       = {"account_number"}
REQUIRED_ANY_OF = (
    {"bill_date", "invoice_date", "service_period"},                      # any date
    {"total_printed", "balance_due", "please_pay",                        # >= 1 amount
     "current_charges", "amount_previously_due"},
)
```

`account_number` is a stronger unconditional requirement than anything Northstar
can make: it is present on 100% of readable invoices and it is this pack's
identity key, because three of the four carriers print no invoice number at all
(F6). `vendor_name` is excluded for the same reason as Northstar's — the sender
domain is its primary source (spec §4).

### Printed identity — the part that differs most from AP

| Field | Notes |
|---|---|
| `account_number` | Required. Printed form is kept on the record; only the **reference hit** is whitespace-stripped, because Comcast prints `8495 44 462 0365242` and joins on `8495444620365242` (F6). See `packs/digitaldirection/references.py` |
| `account_name` | Header account holder — Centracom `CLYDE COMPANIES` |
| `invoice_number` | **Optional.** Present only on Lumen (`752233001`) |
| `bill_date` | `Bill date` · `Invoice date` · `Bill Date:` |
| `service_period` | `Services from Dec 14, 2025 to Jan 13, 2026` (Comcast) |
| `telephone_number` | Secondary identity — Windstream `918-653-3103` |
| `circuit_id` | Centracom `Special Circuit: 4351003276` |

`document_identity` (`invoice_number ?? account_number + "|" + bill_date_iso`, F6)
and `identity_basis` (`invoice_number` \| `account_period`) are **derived and
retained** — `core/contract.py` requires their presence, so dropping them would
break `count(intaken) == count(emitted)`. They are the one exception to the
narrowing (spec §5).

### Printed amounts — the F1 core

Each is transcribed exactly as printed. The whole point is still that they
differ; what changed is that **nothing in this pack reconciles them any more.**

| Field | Anchors observed |
|---|---|
| `prior_balance` | `Previous Balance` · `Previous balance` · `Previous Bill` · `Previous Statement Balance` · `Balance from last statement` · `Previous Balance Due` |
| `balance_from_last_statement` | `Balance from last statement` — Centracom prints both this and a net prior |
| `payments_credits` | `Payments Received` · `Payments/Adjustments thru MM/DD` · `Payment Received - Thank You!` · `Credit Card Payment` — **always stored negative** |
| `credits_adjustments` | `Credits` · `Adjustments` |
| `current_charges` | `Subtotal Current Charges` · `Current Charges` · `Current Charges Due` · `New charges` |
| `amount_previously_due` | `Amount previously due` · `Past Due` |
| `total_printed` | `Total Amount Due` · `Amount due` · `Please pay` · `Balance Due Includes Past Due Amount` |
| `taxes_and_fees` | `Taxes and fees` · `Internet Taxes, Surcharges, & Fees` |
| `charges[]` | `{label, amount}` — Centracom splits `Internet Charges` / `Special Circuit Charges` |

**Read §7's regression note before touching this table.** Centracom prints
`33,876.40` and is payable `13,752.60`; under printed-fields-only the record
carries `33,876.40` and says nothing whatever about the payable. That is the
consequence this design accepts — extraction transcribes, downstream interprets —
and it is pinned by `tests/test_printed_fields_only_path.py`.

### Printed allocation and addresses

| Field | Anchors | Why |
|---|---|---|
| `service_location` | `For service at:` · `FOR SERVICE AT:` · service address block | The chargeback key (F13) |
| `bill_to_name` `bill_to_address` `bill_to_attention` `bill_to_email` | Header addressee | **Guard** — `bill_to_name` must resolve to a managed client |
| `remit_payee` `remit_address` | `Make check payable to` · `payable to` | Drives alias resolution (F5) |
| `vendor_name` `vendor_address` `return_address` | Letterhead, envelope block | |

**Claim note (2026-08-07).** This pack claims by CARRIER, with the managed-client
roster as a documented secondary signal. That secondary half used to be a bare
substring test over the whole primary text, so an unrelated vendor's invoice
claimed the pack merely by naming a client in a line-item description
(`1x SIGNAGE FOR CITY OF DUBLIN PROJECT`). It now requires the client name on a
short line, i.e. in a bill-to block rather than in prose.

Measured across all 111 second-samples: every one of the 7 Digital Direction
documents is claimed by its carrier alias and **zero** reach this fallback, so
its word cutoff is fitted to the over-claim it rejects rather than to a real
document — the one constant in this pack without real-document backing. It is
kept rather than deleted because the pack's growth path is a bill from a carrier
not yet in the alias table addressed to a client who is; the first real document
to arrive through it should be used to re-derive the cutoff.

### Dates

`due_date` — `Payment due` · `Due date` · `Payment Due` · `Due Date:`.
`payments_included_through` — `Payments/Adjustments thru MM/DD`.

Centracom's due date is **`25TH OF THE MONTH`** — not a date at all. Use `date_loose`; pass it through
unparsed with a confidence penalty rather than inventing a day.

### Not in scope — deferred, not deleted

Nothing here was removed from the gold files, and every module and unit test that
produced it is still on disk. Re-enabling is a wiring change.

| Field | Why it left |
|---|---|
| `amount_payable` `payable_basis` `carried_balance` | Derived. Guardrails 2 (`test_f1_antiregression.py`) and 6 (`test_f1_centracom_trap.py`) are `skip`ped with the reason as the message — un-skip them in the same change that re-registers the op |
| `prior_balance_basis` | A derived classification of which label supplied the balance (F1b), not a printed value |
| `carrier_canonical` | Output of the §4 alias table — derived from the printed name, not printed |
| `currency` `currency_basis` | F14 inference ladder. Lumen is the only carrier that prints a literal `(USD)` |
| `account_number_normalized` | Computed form of a printed value |
| `service_type` `charge_type`, the row-type flag | Closed-list classifications of a row |
| `invoice_file_name` | Envelope metadata; already on the record as the attachment ID |
| `vendor_legal_name` `vendor_phone` `vendor_email` `vendor_website` `billing_group` | Printed, and had working selectors. These left for deliverability, so this is the group that shrinks first when scope widens |
| `vendor_parent_reference` | **Extraction debt, not a deferral.** Lumen's `a CenturyLink company` clause is literal page text on page 1 and no persona has ever had a selector for it. It stays asserted, and stays failing, in `tests/test_scorecard_coverage.py:EXTRACTION_DEBT` |

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
| `afterExtraction` | ~~**`deriveAmountPayable`**~~ | **Deferred.** Was the pack's most important function (F1) — see §7 |
| `afterExtraction` | ~~`runArithmeticCrosschecks`~~ | **Deferred** — `prior − payments + current == total_printed` |
| `afterExtraction` | ~~`crosscheckScanline`~~ | **Deferred** — all four bills have one (F7) |
| `beforeConfidenceGate` | `telecomThresholds` | §6 |
| `beforeEmit` | `attachChargebackMetadata` | `service_location`, `circuit_id`, `service_period` |
| `onRegenTrigger` | `requireTwoBillingCycles` | See below |
| — | ~~`applyBillingConventions`~~ | **Deferred** — supplies `prior_balance_basis`, a derived classification |
| `beforeConfidenceGate` | `refineProseBalanceTags` | §2 — upgrades `prior_balance_present` to `cleared` on the printed amounts |

`refineProseBalanceTags` was briefly deferred alongside the rest, on the grounds
that it retagged on `carried_balance`. That was a mistake with a $20,123.80
label on it: unregistering it left classification's anchor-text guess as the
pipeline's final answer. It is re-wired against `prior_balance` and
`payments_credits`, both printed, and re-registered — see §2.

The four struck-through rows are deferred by the printed-fields-only narrowing
(spec `docs/superpowers/specs/2026-07-28-printed-fields-only-design.md` §5).
Every implementation is still in the tree; nothing calls them. Note also that the
three `afterExtraction` derivations were never hook registrations in the first
place — they are persona `adjust` declarations run by Stage 6, and registering
them here as well would double-count every confidence boost.
**`src/docintel/packs/digitaldirection/hooks.py`'s module docstring is the
authority** on where each spec row actually lives.

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
| `current_charges` | 0.95 | The payable a downstream consumer computes comes from here |
| `prior_balance` | 0.95 | A missed prior balance is what makes F1 dangerous |
| `account_number` | 0.95 | The identity key when there is no invoice number |
| `total_printed` | 0.93 | Scanline-corroborated on all four |
| `bill_date` | 0.93 | Also part of the identity key |
| `invoice_number` `payments_credits` | 0.92 | |
| `bill_to_name` `vendor_name` `remit_payee` | 0.90 | |
| `due_date` | 0.88 | Payment timing, not payment amount |
| `service_location` | 0.85 | The chargeback key; human-correctable |
| `circuit_id` `telephone_number` `service_period` | 0.85 | |
| `taxes_and_fees` `subtotal` `tax_amount` `payment_terms` | 0.85 | |
| line-item rows | 0.85 | `LINE_ITEM_THRESHOLD`, applied to all 9 columns: `label` `amount` `description` `quantity` `unit_price` `charges` `payments` `date` `reference` |
| `bill_to_address` `remit_address` | 0.80 | |
| `vendor_address` | 0.75 | |
| ~~`amount_payable`~~ | ~~0.97~~ | **Deferred.** Was the highest threshold in either pack; the row is out of `thresholds.py`, because nothing prices a value nothing produces |

**31 of 31 keys in `thresholds.py`.** The `line-item rows` and `due_date` rows
close a gap: this table listed 21 while claiming to be regenerated from the
module, missing `due_date` and all nine `LINE_ITEM_THRESHOLD` columns. Northstar's
equivalent table verifies as an exact 43/43.

### `(0.90, 0.99)` is currently a dead band

**Every number above was calibrated for a world with corroboration boosts, and
that world is switched off.** The cross-check ops (`crosscheck_filename`,
`crosscheck_scanline`, `crosscheck_balance_composition`) supplied per-field
`ctx.boosts`, which is what used to lift a well-extracted field to the
intermediate values these thresholds sit at. With those ops out of every
persona's `adjust` list, measured per-field confidence on all four carriers takes
exactly **two** values: **0.90** (the base) and **0.99** (the cap reached another
way). Measured 2026-07-29.

So a threshold strictly inside `(0.90, 0.99]` is no longer a graded bar but a
binary one — reachable only by a field that hits 0.99, failed by every field at
the base. In this pack that silently repriced `current_charges` 0.95,
`prior_balance` 0.95, `account_number` 0.95, `total_printed` 0.93, `bill_date`
0.93, `invoice_number` 0.92 and `payments_credits` 0.92 into "0.99 or fail". The
narrowing's threshold edits only deleted rows for deferred fields; no surviving
number was revisited.

All four carriers still route `high`, so the band costs this pack nothing today —
but that is luck, not headroom, and the Northstar pack pays for it on three
documents (`northstar-recycling.md` §7). Recalibration belongs with the
per-document persona work, where there is evidence to do it properly.

**Overrides**
- `prior_balance` missing **and** any prior-balance anchor text present on the page → **review**. This
  is the asymmetry that matters: *failing to find* a prior balance is far more dangerous than finding a
  wrong one, because the failure mode is a silent overpayment. Still the right
  rule, and still the reason `prior_balance` is priced at 0.95 even though the
  pack no longer does anything arithmetic with it.
- ~~`arith_balance_mismatch` → review, `amount_payable = null`, never a guess.~~
  **Currently unreachable.** `arith_balance_mismatch` is still in
  `s7_gate.FORCING_MODIFIERS` and the gate machinery is intact and tested, but
  the only two ops that emit it (`grammar/ops/crosscheck.py`,
  `grammar/ops/derive.py`) are deferred. No corpus document can reach it today.
- `identity_basis == account_period` **and** `bill_date` confidence < 0.93 → review. A weak date makes
  the identity key weak, and downstream dedup depends entirely on it. Live —
  `identity_basis` is one of the two derived values the narrowing kept (§3).

---

## 7. Per-document expectations

**Columns marked *(deferred)* are the gold expectation, not current output.** The
pack emits the printed columns and nothing else; `basis`, `carried` and
`amount_payable` are all derivations the narrowing unwired (§3).

| Document | `total_printed` | `prior_balance` | basis *(deferred)* | carried *(deferred)* | `current_charges` | `amount_payable` *(deferred)* | Gold routing | Measured lane |
|---|--:|--:|---|--:|--:|--:|---|---|
| **Centracom** `0384043574` | 33,876.40 | **20,123.80** | `net_of_payments` | **20,123.80** | 13,752.60 | **13,752.60** | **High** | **high** ✓ |
| Comcast `8495 44 462 0365242` | 221.11 | 212.87 | `gross` | 0.00 | 221.11 | 221.11 | High | **high** ✓ |
| Windstream `041069076` | 1,230.14 | 1,231.74 | `gross` | 0.00 | 1,230.14 | 1,230.14 | High | **high** ✓ |
| Lumen `5-QXH7QKM7` | 248.09 | 249.84 | `gross` | 0.00 | 248.09 | 248.09 | High | **high** ✓ |

The `basis` column is load-bearing *when the derivation runs*. CentraCom's printed prior is already net
of a $24,120.20 payment; the other three print a gross prior alongside a signed credit that zeroes it.
One formula cannot serve both — see F1b. The pack still extracts both `prior_balance` and
`balance_from_last_statement` as printed, so the evidence a downstream consumer
needs to make that distinction is on the record even though the classification is not.

All four route **High** and all four match gold — but read the next paragraph
before taking that as a passing pack, because it is exactly the appearance §7
originally warned about.

### The consequence this design accepts

**Centracom's record currently carries 33,876.40 and says nothing whatever about
the 13,752.60 that is payable.** That is a deliberate decision, not a regression:
under printed-fields-only, extraction transcribes what the page prints and
downstream interprets. The $20,123.80 gap is real and it is downstream's to catch.

What makes Centracom the hardest case in the corpus is unchanged: **every
corroboration signal points at the wrong number.** 33,876.40 is printed in the
largest font on the page, it is what the remittance scan line encodes, and it is
what the stub says to remit. The only evidence for 13,752.60 is the composition
`20,123.80 + 13,752.60 == 33,876.40`. A pack that "reads the total" looks correct
on three of these four bills and is $20,123.80 wrong on the fourth.

### The regression test that must never be deleted — currently `skip`ped

`tests/test_f1_centracom_trap.py` is **GUARDRAIL 6**. It still exists, in full,
and it is `skip`ped rather than deleted — the skip message is the deferral reason
and the instruction. Re-registering `derive_amount_payable` means un-skipping
this file **in the same change**. So does GUARDRAIL 2
(`tests/test_f1_antiregression.py`), which pins the same trap at the op level.

```
GIVEN Centracom_0384043574_01012026_BILL.pdf
WHEN  processed by the digital-direction pack
THEN  total_printed   == 33876.40
AND   prior_balance   == 20123.80
AND   current_charges == 13752.60
AND   amount_payable  == 13752.60     # NOT 33876.40   <- skipped: deferred
AND   payable_basis   == "current_charges"             <- skipped: deferred
AND   review_flag     == false        # closure verified: 13752.60 + 20123.80 == 33876.40
```

The three printed lines still hold today and are asserted by the scorecard. The
two marked `skipped: deferred` are what comes back with the derivation.

**While guardrail 6 is off, its position is held from the other side.**
`tests/test_printed_fields_only_path.py::test_centracom_emits_the_printed_total_not_the_payable`
runs the real PDF end to end and asserts that the record carries the **printed**
33,876.40 and that no `amount_payable` reaches it at all. Re-enabling derivation
without re-enabling its guardrails therefore fails immediately and loudly,
instead of turning a $20,123.80 error back on in silence.
