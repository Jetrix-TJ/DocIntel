# The Closed Selector Grammar

**Status:** v1 draft, derived from [`../corpus-analysis.md`](../corpus-analysis.md).

This is the complete vocabulary the rule agent may emit. It is a **closed grammar**: a persona write
naming anything not listed here is **rejected at write time**, not at run time. Per spec Part 6,
*"the agent writes data, never code"* — this document is what makes that enforceable.

Two consequences of closedness worth stating up front:

1. **The validator is the security boundary.** There is no sandbox because there is nothing to
   sandbox. If the validator accepts something it shouldn't, that is the whole vulnerability class.
2. **A document the grammar cannot express stays on the vision path and is flagged, not forced.**
   Growing the grammar is a deliberate, PR-reviewed act with an eval attached — never something the
   agent does for itself.

---

## 1. Selector kinds

Exactly three. A `field_selectors` array is a list of these.

```
selector := field_selector | row_group_selector | scanline_selector
```

### 1.1 `field_selector` — one value

```jsonc
{
  "field":   "<field_name>",        // required, must be in the pack's field set
  "anchor":  "<literal string>",    // optional; printed label to locate
  "anchor_alts": ["<string>", …],   // optional; tried in order after `anchor`
  "anchor_occurrence": "first" | "last" | "mid_line",   // default "first"
  "region":  "<region>",            // required unless anchor is provably unique
  "pattern": "<pattern>",           // required
  "capture": "first" | "all_matches",   // default "first"
  "adjust":  "<adjust_op>" | ["<adjust_op>", …],   // optional, pack-registered
  "required": true | false          // default true; false → absence is not a miss
}
```

**`anchor_occurrence` — which occurrence of the anchor to resolve to.** Closed enum, three values.
Without it every anchor resolves to the first hit in reading order, which is wrong for a label the
document prints more than once: three personas' remit fields read a payee name their invoice prints
two or three times. Applied **per phrase** — to whichever of `anchor` and `anchor_alts` is being
tried, not only to the primary `anchor`.

| Value | Resolves to |
|---|---|
| `first` (default) | the first hit in reading order — **ordinal** |
| `last` | the last hit in reading order — **ordinal** |
| `mid_line` | the last hit that does **not** begin its visual line — **positional** |

**The two ordinal modes are only ever right by count.** `last` is correct on Veritiv and Windstream
because exactly two bare-brand matches exist per primary page today; both pages carry further
mentions that miss only because normalization strips a trailing colon and not a comma or period
(`Veritiv,`, `Windstream.`). One punctuation change and `last` silently resolves to boilerplate.
EDCO prints its payee **three** times and the remittance block sits under the **middle** one, which
neither ordinal reaches at all — that is what `mid_line` exists for.

**`mid_line` is positional, and it is withheld at run time on OCR-sourced documents.** It reads a
fact about visual line bands — a payment stub prints remit-to beside bill-to, so in the flattened
line stream the stub's payee has the other column's text before it, whereas a letterhead, a heading
and a prose sentence each begin their line. OCR line-grouping does not preserve that fact, so when
the document's `text_source` is `ocr` the executor reports **no qualifying occurrence** — an
ordinary miss, left for coverage to escalate — rather than falling back to an ordinal or to a hit
that begins a line. Measured: on an OCR-sourced Windstream sample the stub's payee came back alone
on its line, so `mid_line` skipped it and resolved into a prose sentence, turning a correct remit
address into the word `by`. A wrong remit address that scores as a pass is worse than a miss.

Two notes on that guard. It keys off the **document's actual text source at run time**, not the
persona's `layout_fingerprint.text_source` (§6) — no runtime code reads any fingerprint member, and
`windstream.json` declares `native` while four of its five real samples are OCR-sourced. And it is
one-sided: the ordinal modes read nothing about line bands and are deliberately **not** withheld.

### 1.2 `row_group_selector` — repeating rows

```jsonc
{
  "row_group":    "<group_name>",
  "table_anchor": "<literal string>",       // header row text used to find the table
  "region":       "<region>",               // optional; narrows the page search
  "columns": {                              // matched by HEADER TEXT, never index (F19)
    "<col_name>": "<pattern>", …
  },
  "column_headers": {                       // optional explicit header→column map
    "<col_name>": "<printed header text>", …
  },
  "sub_group": {                            // optional, ONE level only (F19)
    "anchor":  "<literal string>",          // e.g. "WORK ORDER#:"
    "field":   "<field_name>",              // value captured from the anchor line
    "pattern": "<pattern>"
  },
  "row_count": { "min": <int>, "max": <int> },   // range only, never equality (F19)
  "allow_empty_cells": true | false         // default true (F15)
}
```

### 1.3 `scanline_selector` — the remittance OCR-A line

Scoring-only. Produces **no field value**; it can only raise or lower confidence on fields already
extracted. See F7 — and note the hard constraint on which fields it may touch.

```jsonc
{
  "scanline": true,
  "region": "last-page" | "page:1" | "remittance-block",
  "asserts": [
    { "field": "total_printed",   "as": "digits_no_decimal" },
    { "field": "account_number",  "as": "digits_only" },
    { "field": "invoice_number",  "as": "digits_only" }
  ]
}
```

**Constraint (validator-enforced):** `asserts[].field` may only name
`total_printed`, `account_number`, `invoice_number`, `due_date`.
Naming `amount_payable` or `current_charges` is a **validation error** — Centracom's scanline encodes
the misleading headline total, so binding it to the payable would cement the F1 bug.

---

## 2. Region vocabulary

Closed enum. Regions are resolved against the normalized page geometry, so they behave identically
for native-text and OCR'd documents.

| Region | Resolves to |
|---|---|
| `page:1` … `page:N` | that page, whole |
| `last-page` | final page, whole |
| `first-page` | page 1, whole |
| `any-page` | every page; with `capture: all_matches`, hits from all pages |
| `top-left` `top-right` `top-center` | top third of page 1, horizontal third |
| `header-block` | top 25% of page 1 |
| `totals-block` | anchor-resolved totals region, searched **last page first, then page 1** |
| `remittance-block` | below a detach line (`detach`, `return top portion`, dashed rule), else bottom 30% |
| `last-table-row` | final data row of the nearest table |
| `line_items` | the body of the table matched by the nearest `row_group` |
| `near-anchor` | within 300pt right of / 40pt below the anchor |
| `same-row` | the anchor's text line only |
| `same-cell` | the table cell containing the anchor |

**Why `totals-block` searches the last page first:** U-PAK's payable is on page 5 of 5 and page 1's
`Please Pay` cell is blank (F9). Searching page 1 first finds an empty cell and reports a confident
miss.

---

## 3. Pattern vocabulary

A pattern is **either** a named pattern **or** a restricted regex.

### 3.1 Named patterns (preferred)

| Name | Accepts | Notes |
|---|---|---|
| `currency` | `1,234.56` · `-99.80` · `(249.84)` · `$367.96` · `481.20 USD` · `212.87 cr` | Parens and trailing `cr`/`CR` → **negative**. Never `abs()` (F4). |
| `currency_signed` | as `currency`, but requires an explicit sign | |
| `integer` | `4670` · `1,070` | |
| `decimal` | `2.495` · `83.7900` | |
| `date` | `9/15/2025` · `08/14/2025` · `Dec 09, 2025` · `September 01, 2025` · `03/31/25` · `January 01, 2026` | Normalized to ISO. Ambiguous 2-digit years → confidence penalty. |
| `date_loose` | as `date`, plus `MARCH 31, 2025`, `EOM plus 15` → unparsed passthrough | |
| `text` | any non-empty run on one line | |
| `text_block` | multi-line run within the region | For addresses. |
| `account_number` | alphanumeric with internal spaces/dashes preserved **and** a normalized form | `8495 44 462 0365242` → `8495444620365242` (F6) |
| `phone` | `416-675-3700` · `918-653-3103` | |
| `postal_code` | `45887` · `01028-2744` · `M9W 7E9` · `N1G 4N4` | CA postal codes matter for currency inference (F14) |
| `tax_id` | `123142812RT0001` | Must **not** satisfy `currency` — guards the H.S.T. anchor hazard (F14) |
| `digits_run` | `≥10` consecutive digits, spaces allowed | For `scanline` |

### 3.2 Restricted regex

When a named pattern won't do, a raw regex is allowed under hard limits:

- Runs on a **linear-time engine** (RE2 / `regex` with backtracking disabled) — no backreferences, no
  lookbehind, no possessive/atomic groups.
- Hard **50 ms** timeout per field per document. Timeout → field miss + `pattern_timeout` modifier,
  never a wedged worker.
- Max length **200** characters. Max **1** capture group (the value).
- Unbounded quantifiers (`.*`, `.+`) are **rejected** unless bounded (`.{0,80}`).
- `\d{7}`-style bare patterns are **rejected** unless the selector also carries a `region` narrower
  than `any-page`, or a `column_headers` scope. Unscoped they match phone numbers and zip+4 (F11).

---

## 4. `adjust` ops — the closed enum

Ops run at Stage 6 in declaration order. The agent may **reference** these; it may never define one.
A persona write naming an unregistered op is rejected (spec Stage 6).

### 4.1 Base ops — available to every pack

| Op | Effect |
|---|---|
| `strip_internal_whitespace` | `8495 44 462 0365242` → `8495444620365242` (F6) |
| `strip_currency_symbols` | `$1,177.70` → `1177.70` |
| `parens_to_negative` | `(249.84)` → `-249.84` |
| `trailing_cr_to_negative` | `212.87 cr` → `-212.87` |
| `normalize_date_iso` | → `YYYY-MM-DD` |
| `uppercase` · `lowercase` · `trim` | |
| `collapse_internal_spaces` | for name matching |
| `dedupe_preserve_order` | on `all_matches` lists |

### 4.2 Derivation ops — the F1 machinery

| Op | Effect |
|---|---|
| `derive_amount_payable` | If the **carried** balance ≠ 0 → `amount_payable = current_charges`; else `amount_payable = total_printed`. Emits `payable_basis: "current_charges" \| "total_printed"`. |
| `resolve_carried_balance` | Computes the carried balance from `prior_balance_basis` (F1b): `gross` → `prior_balance + payments_credits`; `net_of_payments` → `prior_balance` as printed. Basis undeterminable → review flag, never a default. |
| `normalize_credit_sign` | Forces `payments_credits` negative regardless of notation: `-212.87 cr` · `$1,231.74 CR` · `(249.84)` · unsigned column. Runs **before** any arithmetic. |
| `subtract_prior_balance_if_present` | `total_printed − prior_balance`. Kept for the case where `current_charges` is not separately printed. |
| `prefer_current_charges_line` | When several current-charge anchors match, take the one nearest the totals block. |

> **`derive_amount_payable` never guesses.** If `prior_balance + current_charges != total_printed`
> (±0.01) it sets `amount_payable = null`, applies `arith_balance_mismatch`, and raises a **review
> flag**. That is precisely the U-PAK case (F8): `14,789.77` vs `14,740.85`, unexplained −48.92, aging
> all zero. A human must resolve it; the pipeline must not average it away.

### 4.3 Consistency ops — scoring only, never value-changing

| Op | Effect |
|---|---|
| `crosscheck_line_sum` | `Σ line_items` vs `subtotal` → boost / `arith_lines_mismatch ×0.85` |
| `crosscheck_total_composition` | `subtotal + Σ charges[]` vs `total_printed` → boost / `arith_total_mismatch ×0.85` |
| `crosscheck_balance_composition` | `prior + current` vs `total_printed` → boost / `arith_balance_mismatch ×0.80` + review |
| `crosscheck_scanline` | value appears in the scanline digits → boost / `scanline_mismatch ×0.85` |
| `crosscheck_duplicate_anchor` | body occurrence == stub occurrence → boost / disagreement → review (F12) |
| `crosscheck_filename` | value appears in the filename → `filename_crosscheck: agree \| disagree \| absent` (F17) |

### 4.4 Inference ops

| Op | Effect |
|---|---|
| `infer_currency` | Ladder: ISO code → symbol → tax regime (`H.S.T.`/`G.S.T.` → CAD, `VAT` → GBP/EUR) → vendor address country → pack default. Records `currency_basis`; lower rungs carry a confidence penalty (F14). |
| `resolve_vendor_alias` | Applies the pack's alias table; prefers the remittance payee over the letterhead (F5). |

---

## 5. Confidence modifiers — the closed enum

One mechanism, multiplicative, all listed on the emitted record (spec Stage 6). No other means of
lowering confidence exists.

| Modifier | × | Cause |
|---|--:|---|
| `soft_miss` | 0.80 | Layout fingerprint diverged |
| `draft_rules` | 0.85 | Persona status is `draft` |
| `ocr_source` | 0.90 | `text_source: ocr` (F2) |
| `ambiguous_anchor` | 0.90 | Anchor occurs more than once, no region given (F12) |
| `anchor_alt_used` | 0.95 | Primary anchor missed; a fallback matched |
| `pattern_timeout` | 0.50 | Regex hit the 50 ms budget |
| `arith_lines_mismatch` | 0.85 | F8 |
| `arith_total_mismatch` | 0.85 | F8 |
| `arith_balance_mismatch` | 0.80 | F8 → also raises review |
| `scanline_mismatch` | 0.85 | F7 |
| `filename_disagree` | 0.95 | F17 |
| `currency_inferred_weak` | 0.90 | `currency_basis` = address or default (F14) |
| `ambiguous_two_digit_year` | 0.95 | `03/31/25` |
| `handwriting_detected` | 0.60 | Primary page has handwriting (F10) |
| `high_skew` | 0.85 | Page skew beyond threshold |
| `flattened_annotations` | 0.75 | F3 → also **forces** review, unconditionally |

**Boosts** are capped: the product of all boosts on one field may not exceed **1.10**, and a boost can
never lift a field above `0.99`. Cross-checks are corroboration, not proof — three agreeing renderings
of an OCR'd number can still all be wrong the same way.

---

## 6. Layout fingerprint

Document-level, never page-level (F20).

```jsonc
{
  "page_count":       { "min": 1, "max": 6 },   // range, never equality
  "has_table":        true,
  "header_signature": "logo-left|addr-right",   // from the FIRST page
  "totals_page_role": "last" | "first",         // page role, not a page number
  "column_signature": ["Description","Qty","Rate","Amount"],  // header text set
  "text_source":      "native" | "ocr" | "either"
}
```

Divergence on `column_signature` or `header_signature` → **soft miss** (spec Stage 4). Divergence on
`page_count` alone is **not** a soft miss — bills legitimately vary in length month to month.

---

## 7. Page roles

New in this grammar; required by F10.

```jsonc
{ "page_role": "primary" | "supporting" | "unknown" }
```

| Role | Heuristic | Extraction behavior |
|---|---|---|
| `primary` | Carries the document-number anchor **and** a totals block | Field values come from here |
| `supporting` | High skew / handwriting / photocopy noise, no totals block | Reference patterns run here; **field values never taken from here** |
| `unknown` | Neither | Treated as `supporting` |

- Exactly one `primary` + ≥1 `supporting` → `doc_type: invoice_with_attachment`, processed normally.
- ≥2 `primary` with **different** document numbers → batch. Flag, do not split (spec Stage 1).
- ≥2 `primary` with the **same** document number → duplicated print (front/back copy). Use the first.

---

## 8. Validation rules

Run at persona-write time. Any failure rejects the **whole** persona write — no partial application, so
a persona is never half-migrated to a bad rule set.

| # | Rule |
|---|---|
| V1 | Every `field` is in the pack's registered field set for that `doc_type` |
| V2 | Every `adjust` op is registered (base + pack) |
| V3 | Every `region` is in the §2 enum |
| V4 | Every pattern is a §3.1 name or passes the §3.2 regex restrictions |
| V5 | A selector with a non-unique `anchor` and no `region` is rejected |
| V6 | Bare-digit regexes require a narrowing `region` or `column_headers` |
| V7 | `scanline_selector.asserts[].field` is within the permitted set (§1.3) |
| V8 | `sub_group` nesting depth ≤ 1 |
| V9 | `row_count` is a range, not an equality |
| V10 | No selector produces a field the pack marks `derived_only` (e.g. `amount_payable`) |
| V11 | Total serialized persona size ≤ 64 KB |
| V12 | `few_shot_examples` length ≤ 3, and none is drawn from a document tagged `flattened_annotations` (F3) |
| V13 | Every field the pack marks `required` is **covered** — by a selector, or by an op that supplies it (`OP_SUPPLIED_FIELDS`) — or the write is `draft` only |
| V14 | A pattern that captures **fixed text** needs an `anchor` or a narrowing `region`; and no `anchor` may restate a value the same persona captures |

**V10 is load-bearing.** `amount_payable` is *derived* from `total_printed`, `prior_balance` and
`current_charges` — never extracted. Letting the agent write a selector straight onto `amount_payable`
is the single easiest way to reintroduce the F1 bug, because on 7 of the 10 sample documents such a
selector would look perfectly correct.

**V14 is V6 inverted, and it exists because 19 of 118 shipped rules broke it.** V6 forbids a pattern
with *no* literal text on a whole-page region, because a bare digit run also matches phone numbers.
V14 forbids a pattern with *nothing but* literal text there, because a capture with no shape to it
makes no claim about location — `(CITY OF DUBLIN)` states what the answer was on one document and
returns nothing on the next one where it differs. An `anchor` or a narrowing `region` satisfies it:
either is a positional claim, and confirming a vendor's own name in a known place is legitimate.

Only the **capture group** is judged, so a literal doing an anchor's job is fine —
`Circuit:\s?([0-9]{10})` passes, `payable to (Comcast)` does not. Put the label in `anchor`, where the
grammar can see it.

The second clause is the only part of the anchor problem decidable at write time. An anchor is a
literal string by nature, so `Account Name:` and `CLYDE COMPANIES` are indistinguishable — unless the
persona also captures that string as a field value, which is the persona declaring it to be a value.
**An anchor keyed to a value the persona does not also capture still passes, and no static rule can
catch it.** That limit is real; it is why the corpus needs a second invoice per sender.

**V13's op exemption follows from V14.** Two of the four telecom templates print their bill-to with no
label anywhere near it, so no anchor exists and no selector can read it — which is precisely why those
personas hardcoded the client's name. `resolve_bill_to_alias` reads it from the pack's roster instead,
and without the exemption V13 and V14 would be jointly unsatisfiable exactly where the document is
least helpful.

---

## 9. Worked example — EDCO, the F1 trap

The persona that gets the misleading-total document right:

```jsonc
{
  "sender_fingerprint": "edcodisposal.com|edco waste & recycling service",
  "doc_type": "standard_invoice",
  "rule_version": "v1",
  "status": "draft",

  "field_selectors": [
    { "field": "invoice_account", "anchor": "Account Number",
      "region": "header-block", "pattern": "account_number",
      "adjust": ["strip_internal_whitespace"] },

    { "field": "bill_date", "anchor": "Billing Date",
      "region": "header-block", "pattern": "date",
      "adjust": ["normalize_date_iso"] },

    { "field": "total_printed", "anchor": "Total Amount Due",
      "anchor_alts": ["Amount Due"],
      "region": "totals-block", "pattern": "currency",
      "adjust": ["crosscheck_scanline", "crosscheck_duplicate_anchor"] },

    { "field": "prior_balance", "anchor": "BALANCE FORWARD",
      "region": "line_items", "pattern": "currency", "required": false },

    { "field": "current_charges", "anchor": "CURRENT CHARGES:",
      "anchor_alts": ["CURRENT CHARGES", "Current Charges"],
      "region": "line_items", "pattern": "currency",
      "adjust": ["derive_amount_payable", "crosscheck_balance_composition"] },

    { "field": "service_location", "anchor": "FOR SERVICE AT:",
      "region": "near-anchor", "pattern": "text_block" },

    { "field": "bill_to_name", "anchor": "SEND PAYMENT TO:",
      "region": "header-block", "pattern": "text_block", "required": false },

    { "row_group": "line_items", "table_anchor": "DESCRIPTION",
      "column_headers": { "description": "DESCRIPTION", "charges": "CHARGES",
                          "payments": "PAYMENTS", "balance": "BALANCE" },
      "columns": { "description": "text", "charges": "currency",
                   "payments": "currency", "balance": "currency" },
      "row_count": { "min": 1, "max": 40 }, "allow_empty_cells": true },

    { "scanline": true, "region": "remittance-block",
      "asserts": [ { "field": "total_printed",  "as": "digits_no_decimal" },
                   { "field": "invoice_account", "as": "digits_only" } ] }
  ],

  "layout_fingerprint": {
    "page_count": { "min": 1, "max": 2 }, "has_table": true,
    "header_signature": "vendor-left|boxes-right",
    "totals_page_role": "first", "text_source": "native",
    "column_signature": ["DESCRIPTION","CHARGES","PAYMENTS","BALANCE"]
  }
}
```

**Traced against the document:**

| Field | Extracted | Note |
|---|---|---|
| `total_printed` | `367.96` | The big box. Corroborated by the scanline `25600770871000367962`. |
| `prior_balance` | `298.34` | `BALANCE FORWARD` row |
| `current_charges` | `69.62` | `CURRENT CHARGES:` row |
| `amount_payable` | **`69.62`** | Derived: prior ≠ 0 → use current. `payable_basis: current_charges` |
| closure check | `298.34 + 69.62 == 367.96` ✓ | Confidence boost, no review flag |

The human who named this file *"current charges can be misleading, paying $69.62"* and the pipeline
now agree — and the pipeline can say **why**.

---

## 10. Deliberately excluded

Things the grammar does **not** have, and the reason:

| Excluded | Why |
|---|---|
| Arbitrary code / expressions / templates | Spec Part 6: data only, no sandbox to secure |
| Conditionals and loops in selectors | Branching belongs in pack hooks — hand-written, PR-reviewed |
| Agent-defined `adjust` ops | A new op is a business-logic change; it needs review and an eval |
| Selectors targeting `amount_payable` | V10 — the F1 footgun |
| Nesting beyond one `sub_group` level | No corpus evidence; unbounded nesting is unbounded debugging |
| Cross-document rules | A persona describes one document, in isolation, by construction |
| Backreferences / lookbehind / unbounded quantifiers | Linear-time guarantee is what makes the 50 ms budget honest |
| Writes to matching or resolution logic | Spec Part 3: hard boundary on what the agent may touch |
