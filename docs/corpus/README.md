# The gold corpus

Hand-labelled expected outputs for the 10 sample documents in [`../`](../).

Per spec Part 3, the gold set is normally a *side effect* of review work and needs seeding with
20–30 hand-labelled documents per domain before the evals can run at all. These 10 are that seed —
6 for Northstar Recycling, 4 for Digital Direction. They were authored by reading every document
page by page; see [`../corpus-analysis.md`](../corpus-analysis.md) for the findings they encode.

## Why these labels came cheap

The filenames are already human annotations of the trap each document contains —
`EDCO 77087APR25 current charges can be misleading, paying $69.62`,
`CONTRA ONLY Everything already on AR`, `CANADIAN WITHOUT NOTES`. Someone named each file after
what makes it hard. Whoever assembled this folder built a regression suite; this directory just
writes it down in a machine-readable form.

Filename-derived values are used **only** to author and cross-check labels, never as an extraction
source (F17).

## Layout

| File | Doc | Teaches |
|---|---|---|
| `northstar-dtss-6060.json` | D.T.S.S. invoice, 1p | control case — clean, closes, native text |
| `northstar-veritiv-715-33905296.json` | Veritiv invoice, 1p | 3 parties, PO-buried match key, duplicate columns, early-pay discount |
| `northstar-complete-beverage-32930.json` | CBD invoice + BOL, 4p | OCR-only, handwritten backup page, 12/12 line math, zero-value row |
| `northstar-federal-recycling-1330123.json` | Federal Recycling contra, 1p | OCR-only, flattened annotations, mixed sign, alias split |
| `northstar-upak-4378107.json` | U-Pak invoice, 5p | **arithmetic does not close** → `amount_payable: null` |
| `northstar-edco-077087.json` | EDCO invoice, 1p | **the F1 trap** — payable 69.62, printed 367.96 |
| `digitaldirection-centracom-0384043574.json` | CentraCom bill, 10p | **the F1 trap at $20k** — highest-priority test in the repo |
| `digitaldirection-comcast-8495444620365242.json` | Comcast bill, 6p | prior cleared to zero, spaced account number |
| `digitaldirection-windstream-041069076.json` | Windstream bill, 4p | 2 brand names + state entity, page-1 advertisement |
| `digitaldirection-lumen-5-QXH7QKM7.json` | Lumen bill, 6p | **3 brand names**, richest scanline, duplicate anchors |

## Schema

```jsonc
{
  "gold_id":        "…",
  "source_file":    "…",            // relative to docs/
  "pack":           "northstar-recycling" | "digital-direction",
  "teaches":        ["F1", "F8", …],  // findings from corpus-analysis.md
  "priority":       "critical",       // optional
  "excluded_from_promotion": true,    // optional — annotated docs (F3)

  "classification": { "doc_type", "tags", "text_source", "page_count", "page_roles" },

  "fields":  { … },   // PRE-TRANSFORM raw extracted values
  "derived": { … },   // POST-TRANSFORM: amount_payable, document_identity, …

  "line_items": [ … ],
  "charges":    [ { "label", "amount" } ],
  "reference_list": [ { "value", "source_field", "page", "pattern_id" } ],
  "scanline":   { "raw", "encodes_*", "binds_to" },

  "assertions":       [ { "check", "expr", "equals", "note" } ],
  "expected_routing": { "lane", "review_flag", "regen_flag", "reason" }
}
```

### `fields` vs `derived` — why they are separate

Spec Part 3: *"Targets are stored **pre-transform** (raw extracted values), so pack business logic
can never leak into extraction rules through the eval."*

So `fields` holds only what is **printed on the page** — including `total_printed`, `prior_balance`
and `current_charges`, all three of which are printed. `derived` holds what pack logic **computes** —
`amount_payable`, `document_identity`, `identity_basis`.

These feed two different evals:

| Eval | Reads | Asks |
|---|---|---|
| Extraction accuracy | `fields` | did the rules read the page correctly? |
| Payable derivation | `derived` | did the pack logic reason correctly? |

Keeping them apart is what stops a rule regeneration from "learning" to output `13752.60` for
Centracom's `Total Amount Due` — which is the wrong fix to the right problem, and would corrupt
`total_printed` for every downstream consumer.

### Completeness flags

`reference_list_complete` / `line_items_complete` are `false` where only some pages were transcribed
(Complete Beverage p3–4, U-Pak p2–4, and the per-service detail pages of the telecom bills). The
validator **skips** sum checks on those rather than asserting against a partial list. This is
deliberate: a silently partial gold label is worse than an absent one.

## Validating

```bash
python3 docs/corpus/validate_gold.py
```

No dependencies. Recomputes every arithmetic claim from the recorded values and asserts the
routing/derivation rules the packs depend on — 95 checks over the 10 documents.

It does **not** read PDFs or call extraction code. It only asks *"is this label set internally
consistent?"*, because a gold set that contradicts itself poisons every eval that inherits it.

Checks performed: line-item sums · per-row `qty × price` · `subtotal + charges == total` ·
carried-balance closure · payable derivation and basis · routing consistency with closure ·
scanline corroboration · scanline field-binding legality (grammar V7) · identity-basis coherence ·
annotation exclusion · `mixed_sign` tag correctness · page-role/page-count agreement ·
`amount_payable` never present as a raw field (grammar V10).

### It has teeth

Verified by mutation:

| Injected bug | Caught |
|---|---|
| Centracom `amount_payable = 33876.40` (the F1 bug) | ✓ 2 failures |
| U-Pak guesses `14740.85` instead of `null` | ✓ 2 failures |
| EDCO scanline bound to `amount_payable` | ✓ 1 failure |

## One modelling subtlety, discovered by running it

The first version of the closure check was `prior_balance + current_charges == total_printed`. It
passed on EDCO and Centracom and **failed on Comcast, Windstream and Lumen** — because those three
print a *gross* prior balance plus a separate signed payment line, while CentraCom prints
`Previous Balance Due` **already net** of payments.

So every document with a prior balance carries `prior_balance_basis: "gross" | "net_of_payments"`,
and the carried balance is:

```
gross            →  prior_balance + payments_credits
net_of_payments  →  prior_balance          (do NOT subtract payments again)
```

`amount_payable` keys off the **carried** balance, not the printed one. This matters because it is
the same class of bug as F1 one level down: double-subtracting a payment produces a *too low*
payable, which is exactly as wrong as F1's too-high one and much harder to notice. The validator now
requires `prior_balance_basis` to be stated explicitly and refuses to guess.

## Extending

To reach the spec's 20–30 per domain:

1. Prefer documents that break a rule already written down — a new trap beats a fourth clean invoice.
2. Never label from the filename alone; read the document.
3. Set `teaches` to the finding IDs, adding new ones to `corpus-analysis.md` as needed.
4. Mark partial transcriptions with the `*_complete: false` flags.
5. Set `excluded_from_promotion: true` for anything carrying human annotations (F3).
6. Run the validator before committing.
