# Cluster C5a — the pack registry and the Northstar pack

**Delivers:** `packs/registry.py`, `packs/store.py`, seven Northstar modules, six
authored personas, and the Stage 3/4/7/CLI wiring.

```
tests     1,208 passing in 6.9s     (1,101 -> 1,208; 107 new)
mypy      strict, 18 files          0 errors
ruff      src + tests               clean
gold      validate_gold.py          95 checks green
scorecard 0/10 documents, 128/339   (was 42/339)
```

| Document | Before | After |
|---|--:|--:|
| DTSS | 4/24 | **23/24** |
| Complete Beverage | 5/30 | 21/30 |
| Veritiv | 4/37 | 20/37 |
| Federal Recycling | 5/29 | 19/29 |
| U-PAK | 7/32 | 17/32 |
| EDCO | 4/35 | 16/35 |
| the four Digital Direction docs | 3 each | 3 each (C5b) |

**0/10 documents green.** The plan's exit criterion was 8/10 and this cluster did
not reach it. What remains is almost entirely **formatting**, not extraction — see
"What is still failing" below. The F1 machinery, the classification ladder, the
row groups and the routing all work on real PDFs.

---

## The blocking discovery: modifiers had no scope

My own C3 Stage 6 applied **every** modifier to **every** field.

`currency_inferred_weak` fires on 8 of the 10 gold documents, because
`pack_default` is the last rung of the F14 ladder and 8 documents resolve there.
So every field of every one of them scored `1.0 x 0.90 = 0.90` against a 0.95
`total_printed` threshold — and **no document could ever reach the `high` lane.**
Seven expect one.

§5 calls modifiers "multiplicative" without saying what they multiply. Some are
plainly about the document (`ocr_source`, `draft_rules`, `soft_miss`,
`handwriting_detected`, `flattened_annotations`); others are about **one field**
(`currency_inferred_weak`, `anchor_alt_used`, `ambiguous_anchor`,
`pattern_timeout`, `scanline_mismatch`). A weakly-inferred currency is no reason
to trust the invoice number less.

`JobContext.field_modifiers` now carries the scoped ones. Stage 6 multiplies
document-wide modifiers into every field and scoped ones into their own field
only. Scoped modifiers still reach the record — a record listing every modifier
that fired is what makes a confidence number auditable.

---

## Design decisions

### A pack claims a document by the bill-to, never the sender or the filename

The **sender** decides which persona applies (Stage 4); the **recipient** decides
which pack applies (Stage 3). Conflating them would mean a new vendor could not be
processed until somebody said which pack it belonged to.

`resolve_pack` returning `None` is a real answer, tagged `unclaimed_document`. An
invoice that landed in the wrong AP inbox is an event somebody needs to see, not a
document to force into whichever pack happens to be first.

### The fingerprint comes from page text, not from an extracted field

`<pack>|<canonical vendor>`, computed at `beforePersonaLookup`. Stage 4 runs
before Stage 5, so no field has been extracted yet — and that ordering is not an
inconvenience to route around. The persona is what tells Stage 5 how to extract,
so the lookup key cannot depend on extraction having happened.

### Four hooks, not eleven

The pack spec's §5 table lists eleven. Seven turned out to be things a persona
already declares or the core already does, and `hooks.py` tabulates every absence
with its reason. The important one: `deriveAmountPayable`,
`runArithmeticCrosschecks` and `inferCurrency` are persona `adjust` declarations
run by Stage 6 — registering them as hooks too would **double-count every
confidence boost**.

### A seventh module the plan did not list: `conventions.py`

EDCO's `prior_balance_basis` is `gross`, and **no selector can supply it** — it is
not printed anywhere. That EDCO's `BALANCE FORWARD` is carried in full is a fact
about how EDCO bills, learned once by whoever read the invoice against the
remittance history. F1b refuses to guess it, so without this the F1 trap document
routes to review with no payable at all.

Deliberately **not** a grammar feature. A "literal value" selector kind would let
a rule agent write arbitrary constants into any field — a far larger hole than one
hand-maintained table per pack. A wrong entry here is a reviewed code change; a
wrong constant in a persona would be an agent write.

### One deliberate grammar extension: `join_lines_comma` (the 24th op)

Ten gold files carry `bill_to_address` and eight carry `vendor_address`. Every one
is a multi-line block represented as a single comma-joined string, and no §4.1 op
produced that — `collapse_internal_spaces` flattens the newline to a space and
loses the separator. Roughly eighteen assertions were unreachable by any *legal*
persona.

§10 says a new op needs review and a reason rather than an agent's say-so. This is
that reason. It is pure formatting: it moves no value between fields and makes no
business decision.

### Measured ladder signals

- **contra** = every per-unit rate on the page is negative (`-40.00/ST`). The
  `/UNIT` suffix is what makes it a *rate*, and it is the only corpus signal that
  separates a contra from an invoice carrying a rebate line: U-PAK prints
  `-40.500` and Complete Beverage `-0.65`, negative unit prices with no suffix,
  and neither is a contra.
- **handwriting** = OCR noise ratio ≥ 0.40 on a *supporting* page. Measured
  0.51/0.46 on Complete Beverage's handwritten BOL pages against 0.22/0.28 on its
  printed ones and 0.17 on Federal Recycling. Examining only supporting pages
  removes the false-positive risk entirely — Federal Recycling carries a
  handwritten margin note but is single-page, and its gold is correctly untagged.
- **past_due** = `PAST DUE` on a short line (≤6 words), or an aging header.
  Federal Recycling's terms print "PAST DUE AMOUNTS SUBJECT TO INTEREST..." on
  every invoice it sends; its gold is correctly untagged.

### The required field set is deliberately narrow

`{vendor_name, total_printed, amount_payable, bill_to_name}`. `invoice_number` is
omitted because three of ten corpus documents print none (F6) — that is the whole
reason the identity ladder falls back to account+period, so requiring a selector
would make the documents F6 was written for unwritable. `invoice_date` is omitted
because EDCO prints a billing date and no invoice date.

---

## Defects found during the run

1. **An unbounded `\s+` in a persona regex, and the silent failure behind it.**
   V4 correctly rejected the persona — and **a rejected persona does not error.**
   It is a lookup *miss*, so the document fell back to the vision path. DTSS
   dropped from 23 passing assertions to 14 and nothing but the scorecard
   noticed. GUARDRAIL 5 (`tests/packs/test_personas_validate.py`) now validates
   every shipped persona, so this cannot ship again.

2. **Two fixture defects, both standing rule 7.** `test_registry`'s `_page`
   hardcoded `page_number=1`, so a two-page fixture was two copies of page 1 and
   the supporting-page test passed for the *wrong reason*.
   `test_northstar_ladder`'s `_page` put every token on one visual line, which
   made `_is_own_paperwork` see the bill-to inside its four-line letterhead window
   and made every `PAST DUE` banner look like prose — two tests failed against
   *correct* code.

3. **A raw `TypeError` from `json` in the CLI.** A `DateResult` reaches the record
   whenever a persona uses `date` without `normalize_date_iso`, which is legal.
   `_serialize` now handles both structured pattern results, duck-typed so `core`
   does not import `grammar`.

4. **Gold's `currency_basis` vocabulary is not the one C3 invented.** It is
   `explicit_iso_code` / `tax_regime_marker` / `pack_default`. Renamed — naming the
   rungs anything else would have made the field unassertable, so the scorecard
   would have silently stopped measuring the F14 ladder it exists to check.

---

## What is still failing, and why it is formatting rather than extraction

**Three limitations account for most of the remaining 84 Northstar failures.**

1. **Gold title-cases an all-caps document.** EDCO prints
   `EDCO WASTE & RECYCLING SERVICE` and `HUNTER INDUSTRIES 260 S PACIFIC ST`; its
   gold labels read `EDCO Waste & Recycling Service` and
   `Hunter Industries, 260 S Pacific St`. No §4.1 op produces title case. This is
   most of EDCO's 19 failures. **Options: a `title_case` op, or a
   case-insensitive comparison for non-money text fields in the scorecard.** The
   second is probably right — `EDCO WASTE` and `EDCO Waste` are the same vendor,
   and a scorecard that fails on case is measuring the labeller's typing.

2. **`near-anchor` reaches 40pt below, and several addresses span further.** DTSS's
   vendor address is street + city on lines that do not both fit. Widening the
   region past the spec's 40pt would pull in the Date/Invoice# block that shares
   those lines. A region between `near-anchor` and `header-block` would fix it.

3. **A persona cannot capture its own anchor text as a value.** The executor
   excludes the anchor's words from the candidate list — correct for
   `service_location`, wrong for `bill_to_name` when the label *is* the value
   (`NORTHSTAR RECYCLING` shares a line with the vendor name). The workaround is a
   literal regex with no anchor, which works but reads oddly.

None of these is an extraction failure. Every one of the six documents extracts
its total, its identity and its line items correctly, and the F1 trap derives
69.62 rather than 367.96.

---

## Notes for C5b

- The Digital Direction pack mirrors this structure. `packs/registry.PACK_MODULES`
  is the one place to add it.
- `DEFAULT_FORCED_REVIEW_TAGS` and `FORCING_MODIFIERS` are pack-independent; DD
  needs neither.
- Centracom is the F1 trap's larger sibling — 20,123.80 at stake. Its
  `prior_balance_basis` is `net_of_payments` and, like EDCO's, will need a
  `conventions.py` entry rather than a selector.
- Lumen's gold `currency_basis` is `explicit_iso_code`, so its persona needs a
  `currency` selector capturing the printed code.
- Before authoring, decide the title-case question above — it affects how many
  text-field assertions DD's four documents can reach.
