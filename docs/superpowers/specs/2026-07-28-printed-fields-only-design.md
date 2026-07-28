# Printed fields only — narrowing extraction scope

**Status:** design, awaiting approval
**Date:** 2026-07-28
**Branch:** `feat/pipeline`
**Supersedes:** nothing. Narrows the field scope set in
`docs/packs/northstar-recycling.md` §2 and `docs/packs/digital-direction.md` §3.

---

## 1 · The decision

Extract only values that are **printed on the document**. Nothing derived is a
deliverable.

Two sources drove this:

- The consolidated field spec ([artifact `00a5c120`](https://claude.ai/code/artifact/00a5c120-005b-4e90-98db-ac9663561d0a)),
  which grades fields into four requirement levels across both projects.
- A narrower instruction than that artifact's own taxonomy: work the **Required**
  level only, and only where the value is ink on the page.

Derived work is **deferred, not deleted.** Every module and unit test stays in the
tree; only the wiring and the scorecard change. This is recoverable with a revert.

### The mechanical test

A field is in scope if a selector can read it off the page. That is the exact
inverse of `DERIVED_ONLY` in `core/models.py`, so the rule reduces to:

> Nothing derived-only is a deliverable.

---

## 2 · What leaves scope

| Field | Why it is not printed |
|---|---|
| `amount_payable` | Derived by `derive_amount_payable`; `DERIVED_ONLY` by construction |
| `currency` | Produced by the F14 inference ladder |
| `prior_balance_basis` | A derived classification of which label supplied the balance |
| `account_number_normalized`, `vendor_account_number_normalized` | Computed |
| `document_identity`, `identity_basis` | Produced by the identity ladder — but **retained**, see §5 |
| `due_date` when absent | The field spec derives it from terms + invoice date |
| DD `service_type`, `charge_type`, row-type flag | Closed-list classifications of a row, not printed values |
| DD `invoice_file_name` | Envelope metadata; already on the record as the attachment ID |

The last two rows are a finding, not a restatement: **four of the field spec's
eight "Required" Digital Direction fields are not printed values at all.** Three
are classifications and one is metadata. They are derivations wearing field names,
so they land in the same deferred bucket as `amount_payable`.

---

## 3 · Field sets

### `REQUIRED` cannot be a flat set

The field spec's Required level says "**any** parseable date" and "**at least one**
money amount". V13 checks set membership, which cannot express either. Encoding
them as the literal names `invoice_date` and `total_printed` would be a real
over-constraint:

- **EDCO prints a billing date and no invoice date** (`northstar/fields.py:132`).
  Requiring `invoice_date` makes EDCO's persona unwritable.
- **The total's value parses on only 77.2%** of invoices (label present 92.2%).
  Requiring `total_printed` makes every vendor that prints no total unwritable.

So `required_fields` gains a companion:

```python
REQUIRED: frozenset[str]                          # every name needs a selector
REQUIRED_ANY_OF: tuple[frozenset[str], ...]       # each group needs >= 1 selector
```

V13 grows one clause: for each group in `REQUIRED_ANY_OF`, at least one member must
be covered. Derived-only names remain exempt exactly as they are today. This is the
minimum change that lets the spec's own wording be expressed; without it the
narrowing would ship a stricter gate than the one it is derived from.

### Northstar (`packs/northstar/fields.py`)

```python
REQUIRED = frozenset({"bill_to_name"})

REQUIRED_ANY_OF = (
    frozenset({"invoice_date", "bill_date"}),                    # any parseable date
    frozenset({"total_printed", "balance_due", "please_pay",     # >= 1 money amount
               "current_charges", "subtotal"}),
)
```

`bill_to_name` is the only unconditional requirement: it is printed on 94.4% of
documents and it carries the **guard** that the billed party resolves to Northstar,
which is what stops another company's invoice being processed as ours.

`vendor_name` is deliberately absent. See §4.

`FIELDS` narrows to the printed set plus the row-group column names V1 checks:

- **Identity** — `vendor_name`, `invoice_number`, `invoice_date`, `bill_date`
- **Amounts as printed** — `total_printed`, `subtotal`, `tax_amount`,
  `prior_balance`, `current_charges`, `payments_credits`, `please_pay`,
  `balance_due`, `discount_amount`
- **Terms** — `due_date`, `payment_terms`, `discount_date`
- **Allocation** — `service_location`, `vendor_account_number`, `account_number`
- **Addresses and payee** — `bill_to_name`, `bill_to_address`, `bill_to_attention`,
  `remit_payee`, `remit_address`, `return_address`, `vendor_address`
- **Match keys** — `customer_po`, `seal_number`, `bol_number`
- **`_TABLE`** — unchanged; V1 checks row-group columns against it

Removed from `FIELDS`: `amount_payable`, `currency`, `prior_balance_basis`, both
`*_normalized` names, `vendor_parent_reference`, `billing_group`, `account_name`,
`vendor_legal_name`, `vendor_phone`, `vendor_email`, `vendor_website`, `tax_id`.

### Digital Direction (`packs/digitaldirection/fields.py`)

```python
REQUIRED = frozenset({"account_number"})

REQUIRED_ANY_OF = (
    frozenset({"bill_date", "invoice_date", "service_period"}),
    frozenset({"total_printed", "balance_due", "please_pay",
               "current_charges", "amount_previously_due"}),
)
```

`account_number` is the one unconditional requirement, and it is a stronger one
here than anything Northstar can require: the field spec measures the carrier
account number present on **100%** of readable invoices, and it is Digital
Direction's identity key because three of the four carriers print no invoice number
at all (F6). `vendor_name` is excluded for the same reason as Northstar's.

`FIELDS` keeps the printed identity, amount, allocation, address and `_TABLE`
groups, and drops `amount_payable`, `currency`, `prior_balance_basis`,
`account_number_normalized`, `carrier_canonical`, `vendor_parent_reference`,
`billing_group`, `vendor_legal_name`, `vendor_phone`, `vendor_email`,
`vendor_website`.

---

## 4 · `vendor_name` comes from the sender, not a selector

`vendor_name` stays in `FIELDS` — a readable letterhead is still captured — but it
is **never required**. Two corpus documents cannot supply it from the text layer at
all: Lumen's letterhead is an image, and Windstream's text layer breaks the brand
mid-word as `Windstre am`.

Resolution order:

1. A persona selector, when the letterhead is readable.
2. Otherwise the **sender email domain**, via the existing `resolveVendorAlias`
   hook at `beforePersonaLookup`.

### The aggregator constraint

`pipeline-v2.md:169` requires that aggregator senders (bill.com, Ariba,
QuickBooks) be keyed by printed vendor name and **never** by the shared email
domain — otherwise every invoice routed through bill.com resolves to the same
vendor.

This is specified but **not implemented anywhere in `src/`**, and no corpus
document arrives from an aggregator, so it does not bite today. It must not become
a silent gap:

- A module-level `AGGREGATOR_DOMAINS` denylist.
- When the sender domain is on it, `vendor_name` is left **unresolved** and the
  document is flagged, rather than emitting a confidently wrong name.
- A test asserting that an aggregator-domain sender does **not** get a
  domain-derived `vendor_name`. This is the guard that keeps an unimplemented
  branch honest.

---

## 5 · What gets unwired

**Correction to an earlier draft of this section.** The derived work is not
registered as hooks. `northstar/hooks.py:15-17` and `digitaldirection/hooks.py:4-6`
both state that `deriveAmountPayable`, `runArithmeticCrosschecks` and
`inferCurrency` live in **each persona's `adjust` list, run by Stage 6** —
registering them as hooks as well would double-count every confidence boost. So
"unwiring" is mostly a persona edit (§6), not a hook edit.

### Ops removed from persona `adjust` lists

Measured across all ten personas:

| Op | Occurrences | Why it goes |
|---|---:|---|
| `resolve_carried_balance` | 10 | Produces `carried_balance`, `DERIVED_ONLY` |
| `derive_amount_payable` | 10 | Produces `amount_payable`, `DERIVED_ONLY` |
| `infer_currency` | 10 | The F14 inference ladder |
| `crosscheck_filename` | 10 | Confidence-only cross-check |
| `crosscheck_scanline` | 5 | Same |
| `crosscheck_balance_composition` | 4 | Same |
| `crosscheck_total_composition` | 2 | Same |
| `crosscheck_line_sum` | 1 | Same |

### Ops that stay

These normalize a value that **is** printed rather than deriving a new one:

| Op | Occurrences |
|---|---:|
| `join_lines_comma` | 20 |
| `normalize_date_iso` | 15 |
| `resolve_vendor_alias` | 9 |
| `normalize_credit_sign` | 5 |
| `strip_internal_whitespace` | 1 |

`resolve_vendor_alias` stays and becomes more load-bearing, not less: it is half of
the §4 vendor-name path.

### Hooks actually removed

| Hook | Pack | Socket | Why |
|---|---|---|---|
| `apply_billing_conventions` | both | `afterExtraction` | Supplies `prior_balance_basis`, a derived classification |
| `refine_prior_balance_tags` | DD | `beforeConfidenceGate` | Retags on `carried_balance`, which no longer exists |

**Hooks kept:** both ladders (`classifySignals` — `doc_type` is required), both
fingerprint resolvers (`beforePersonaLookup` — the §4 vendor path), and both
`collect_references` registrations, since reference patterns match printed text.

### The one derived thing that stays

`derive_document_identity` **remains wired.** `validate_record`
(`core/contract.py:140-149`) requires the *presence* of `document_identity` and
`identity_basis` on every processed record, so unwiring it raises `ContractError` on
all ten documents and takes the `count(intaken) == count(emitted)` invariant with
it.

This is not an exception to the rule so much as a different category. These two are
**Stage 8 contract keys carrying pipeline provenance**, not claims about what the
document printed — and they live under `derived`, not `fields`, which is where the
record already draws that line. `None` is a valid value there, meaning "looked and
could not build one", which is materially different from "this pipeline never
tried". Removing them would be a contract change and is out of scope.

`core/models.py:DERIVED_ONLY` keeps its entries — the names remain reserved so a
selector can never target them, which is what makes re-enabling a wiring change
rather than a redesign.

---

## 6 · Personas

All ten personas are pruned to the narrowed `FIELDS`. This is not optional
cleanup: **V1 rejects a selector targeting an unregistered field, and a rejected
persona is a lookup *miss*** — the document then falls back to vision quietly
(guardrail 5, `test_personas_validate.py`). Narrowing `FIELDS` without pruning the
personas in the same change silently disables the fast lane on all ten documents.

Current selector counts, all of which shrink: Centracom 21, Lumen 19, Windstream
17, Comcast 17, EDCO 14, U-PAK 12, and 10 each for DTSS, Veritiv, Complete
Beverage, Federal Recycling.

---

## 7 · Gold, scorecard, guardrails

**Gold files are untouched.** Standing rule 6 makes `docs/corpus/gold/*.json`
read-only and a test byte-compares all ten every run. The gold keeps recording
that Centracom's payable is $13,752.60, so the evidence for re-enabling derivation
stays on disk.

**Scorecard.** No new classification mechanism is needed — a second correction to
an earlier draft. `GOLD_ASSERTION_COVERAGE` (`scorecard.py:223`) already carries
four verdict prefixes, one of which is **`deferred:<why>`** for "needs a capability
that does not exist yet". Every derived assertion is re-verdicted to
`deferred:printed-fields-only` with the spec path as the reason.

GUARDRAIL 3 requires each gold fact to be asserted *or* explicitly classified, so
re-verdicting keeps it green without weakening it. `CHECKED_DERIVED`
(`scorecard.py:204`) narrows from four names to the two contract keys that survive
§5, and `test_every_gold_derived_key_is_asserted` follows it.

**Guardrails 2 and 6** (`test_f1_antiregression.py`, `test_f1_centracom_trap.py`)
are end-to-end tests of derived behaviour. They become `skip` with the deferral
reason as the skip message — not deletions. A skip with a reason is recoverable
and greppable; a deletion is neither.

### Expected movement

From 274/339 assertions and 1/10 documents green, to roughly **175–200 of ~230**.
Both numbers drop because derived assertions leave the denominator with their
passes. The **percentage should rise**, and 10/10 becomes reachable for the first
time, because what remains is only what the PDFs actually print.

**Assumption, overrulable:** the convergence loop retargets at *10/10 documents
green on printed fields only*. Recorded here because it sets what "done" means and
was not explicitly confirmed.

---

## 8 · Testing

1. **Field-set unit tests** — `REQUIRED ⊆ FIELDS`, every `REQUIRED_ANY_OF` group is
   non-empty and a subset of `FIELDS`, and `FIELDS ∩ DERIVED_ONLY == ∅` for both
   packs. The last is the machine-checkable form of this whole design.
2. **V13 any-of clause** — a persona covering *one* member of a group passes; a
   persona covering *none* fails. Both directions, because a clause that never
   fails is not a gate. Cover the EDCO case specifically: `bill_date` alone
   satisfies the date group.
3. **All ten personas validate** — guardrail 5, unchanged, must stay green. It is
   the test that catches the §6 failure mode.
4. **Aggregator guard** — §4, new.
5. **Whole-path test per pack** — standing rule 10: a cluster that changes a
   pipeline capability finishes with one end-to-end test. Here: a real PDF through
   the narrowed field set into a validated Stage 8 record carrying no derived key.
6. **`count(intaken) == count(emitted)`** — the invariant is untouched and must
   remain so.

---

## 9 · Risks accepted

- **The Centracom trap moves downstream.** The pipeline will emit
  `total_printed: 33876.40` faithfully and say nothing about the payable
  $13,752.60. This is consistent with `pipeline-v2.md` Part 6, which puts business
  logic downstream — but the $20,123.80 gap is now downstream's to catch, and
  nothing in this pipeline will flag it.
- **Aggregator senders are unhandled**, guarded by a test rather than an
  implementation (§4).
- **`vendor_name` quality depends on the sender domain**, which is weaker evidence
  than a letterhead for any sender that forwards mail.

---

## 10 · Open questions unchanged

Confidence thresholds, audit-sample rate, review SLAs, regeneration cadence,
U-Pak's unexplained −$48.92, and whether annotated and clean copies of the same
invoice both arrive. None are blocked by this change.
