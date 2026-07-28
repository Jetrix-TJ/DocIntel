# Cluster C3b — making the scorecard honest

**Delivers:** the missing scorecard coverage, and a guardrail that stops the next
gap of this kind being silent.

Not in the original plan. Created from C3's finding 2, on the user's approval.

```
tests     1,061 passing in 8.2s     (994 -> 1,061; 67 new)
mypy      strict, 18 files          0 errors
ruff      src + tests               clean
gold      validate_gold.py          95 checks green
scorecard 0/10 documents, 41/339 assertions   (was 39/252)
```

**The denominator moved 252 → 339 (+87) and the numerator 39 → 41.** The +2 is
real: `ocr_source` on Complete Beverage and `ocr_source` + `flattened_annotations`
on Federal Recycling. Those are C1a's and C1b's detection working, turned into
modifiers by C3's Stage 6 — capability that has been correct for three clusters
and was measured by nothing.

---

## The finding was bigger than reported

C3's finding 2 said "68 gold assertions ignored, 37 machine-checkable, several
uncovered". Mapping all 55 check names against the record showed that estimate was
**wrong in both directions**, and the correction matters:

**Fewer of the assertions were genuinely new than I claimed.** Of the 25 distinct
check names carrying an `equals`, 13 were already covered by an existing scorecard
assertion (`amount_payable`, `payable_basis`, `identity_basis`/`identity_fallback`,
`review_not_needed`, `currency_inferred`, `service_location_captured`,
`prior_balance_is_net`, `prior_balance_derivation`, `discount_is_one_percent`,
`amount_previously_due_is_zero`, `payable_mismatch`), and several more were
arithmetic narrative whose components were each asserted individually.

`balance_composition` is the clearest case of why a check name cannot be mapped
mechanically: on four documents its `equals` is `total_printed`, and on Lumen it
is the **carried balance** (`249.84 - 249.84 + 0.00 = 0.0`, while Lumen's total is
248.09). The same name means two different things.

**But a much larger gap sat next to it, unmentioned.** A sweep of gold *field*
names found **29 never asserted, across 73 occurrences**:

| Gold field | Files |
|---|--:|
| `bill_to_address` | 10 |
| `currency_basis` | 10 |
| `vendor_address` | 8 |
| `remit_address` | 7 |
| `vendor_phone` | 6 |
| …24 more | 1–3 each |

`currency_basis` is in all ten files and is **C3's own output** — the F14 inference
ladder's record of which rung answered. Five members of `MONEY_FIELDS` were
declared as money and then never checked (`amount_previously_due`, `balance`,
`balance_from_last_statement`, `credits_adjustments`, `total_weight`).

So the honest summary: the array I flagged was mostly redundant, and the thing I
had not looked at was three times larger.

---

## What was wired

### The confidence-modifier mechanism (the real gap)

Spec §5 — 16 modifiers — was asserted **nowhere**. Nothing would have noticed if
`arith_balance_mismatch` stopped being applied, which is the modifier that decides
whether a human ever looks at U-PAK's unexplained 48.92.

`_expected_modifiers` derives expectations from three gold signals rather than a
hand-written list, so a new gold file gets its expectations for free:

- `classification.text_source == "ocr"` or an `ocr_only` tag → `ocr_source`
- a `has_flattened_annotations` tag → `flattened_annotations`
- any `assertions` entry named `<modifier>_applied` with `equals: true`

Asserted as a **superset** (a pack may legitimately add more), and only where gold
implies at least one — see the vacuity section below.

`handwritten_supporting` deliberately implies nothing: §5's `handwriting_detected`
is about handwriting on a *primary* page, and that tag says the opposite.

### Composite arithmetic assertions

Each gold `*_composition` / `line_sum` / `scanline_agrees_*` entry documents
arithmetic whose components are already asserted individually. What was *not*
observable is whether the pipeline **checked** it — the cross-check ops report a
modifier, and modifiers were unasserted.

Four new assertions, each deliberately **composite**:

```
arithmetic.balance_closed    amount_payable is not None AND no arith_balance_mismatch
arithmetic.total_closed      total_printed is not None AND no arith_total_mismatch
arithmetic.lines_closed      line_items non-empty  AND no arith_lines_mismatch
arithmetic.scanline_agrees   scanline is not None  AND no scanline_mismatch
```

A bare "modifier is absent" check would have passed trivially on a pipeline that
computed nothing — eight free passes, making the score read better while measuring
less. Paired this way, each fails until the op genuinely runs and closes.

### 29 gold fields, and a fields-then-derived getter

`CHECKED_FIELDS` grew by 27 names. Only the two `*_note` fields are excluded, and
a test asserts that exemption list stays at two entries and that both end in
`_note`.

`currency_basis` forced a small design decision. Gold puts it under `fields`;
`infer_currency` writes it to `derived`, correctly, because nothing read it off a
page. Rather than move the op's output to fit the label, the field getter now
looks in `fields` and falls back to `derived`: **gold labels a fact about the
document and does not say whether a pipeline should read it or compute it.**
Provenance is not thereby unmeasured — it is exactly what `currency_basis` and
`payable_basis` record, and both are asserted.

### Two derived values that live only in the assertions array

`derived.filename_crosscheck` (EDCO, `agree`) and `derived.vendor_canonical`
(Lumen `lumen`, Windstream `windstream`, via `alias_collapse`). Neither appears in
any gold file's `derived` block, so the existing loop could not see them.

---

## The guardrail

`tests/test_scorecard_coverage.py` — **GUARDRAIL 3**. Standing rule 3 has now been
violated five times (`reference_list` and all fifteen tags, `page_roles`, the four
contract keys, `lane`, and this). Every one was invisible: no test failed, no count
looked wrong.

The guardrail makes it mechanical rather than something to remember:

- every gold `assertions` check name must appear in `GOLD_ASSERTION_COVERAGE`
  with one of four verdicts — `covered:<assertion>`, `wired:<assertion>`,
  `documentation`, `deferred:<why>`
- the table may not carry stale entries for checks no gold file makes
- a `covered:` or `wired:` verdict must name an assertion the scorecard actually
  emits — a verdict pointing at nothing reads as coverage that is not there
- every gold field, derived key and `expected_routing` key must be asserted or
  declared prose
- **no assertion may pass against an empty record**

Adding a gold file, or one assertion to an existing one, fails here until somebody
classifies it.

### The vacuity check earned its keep immediately

It found that **2 of the then-39 passing assertions were free passes**: U-PAK's
`derived.amount_payable` and `derived.payable_basis` both expect `null`, which an
empty record satisfies by coincidence. That confirmed C3's suspicion that U-PAK's
derived assertions had been passing without measuring anything.

They are allowed, in a keyed list with a written reason each, because `null` **is**
the correct answer for U-PAK (F8) — but the allowance is mitigated, not waved
through: U-PAK also asserts `confidence_modifiers` requiring
`arith_balance_mismatch`, which cannot be satisfied without the derivation
actually running and refusing. There is a test asserting exactly that mitigation
exists, so U-PAK cannot reach green on the vacuous pair alone.

`VACUOUS_BY_CONSTRUCTION` has four entries. A test asserts none of them is stale.

---

## What is still not measured, and why

- **`ctx.boosts` never reaches the record.** A corroboration boost shows up only
  as a slightly higher confidence number, and no gold label predicts a confidence
  value. `duplicate_anchor_agrees` is classified `documentation` for that reason.
  Worth revisiting if a pack ever needs to prove a cross-check fired.
- **`expected_routing.reason`** (3 files) is free text explaining a routing
  decision, not a value.
- **`annotation_dates_not_captured` / `annotation_values_excluded`** are
  `deferred:C5` — "the overlay value was not captured" needs a pack that knows
  which values are overlays.
- **Nine confidence modifiers have no gold signal** that implies them
  (`ambiguous_anchor`, `anchor_alt_used`, `pattern_timeout`, `high_skew`, …).
  They are unit-tested but not corpus-asserted, which is the right place for them:
  no gold label states them.

---

## Notes for C4

- `lane` fails on all ten documents and `arithmetic.*` fails on eight. Those are
  C4's and C5's scoreboards respectively.
- Adding an assertion now means passing GUARDRAIL 3, including the empty-record
  rule. If a new assertion passes vacuously, either make it composite or add a
  keyed allowance with a reason.
- `review_flag` / `regen_flag` are allowed to pass vacuously because `False` is
  both the gold expectation and the `JobContext` default. `lane` is the
  non-vacuous gate on the gate having run — which is why it matters that C4 sets it.
