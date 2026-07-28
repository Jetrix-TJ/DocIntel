# Cluster C2b — the executor and the four contract keys

**Delivers:** `grammar/executor.py`, a persona-bound Stage 5a, the four missing
Stage 8 keys, and the scorecard assertions that finally measure them.

Executed inline in the controller session (subagent use was disallowed). No fix
rounds; three defects came out of the run itself and are recorded below.

```
tests     558 passing in 7.8s      (503 -> 558; 55 new)
mypy      strict, 13 files         0 errors
ruff      src + tests              clean
gold      validate_gold.py         95 checks green
scorecard 0/10 documents, 39/242 assertions   (was 39/223)
```

**The denominator moved and the numerator did not, and that is the point.**
`assertions_total` went 223 -> 242. The +19 breaks down exactly as intended:

| New assertion | Docs | Finding it un-blinds |
|---|--:|---|
| `line_items.count` | 5 | F8, F19 |
| `line_items.amounts` | 5 | F8, F19 |
| `scanline.raw` | 5 | F7 |
| `charges` | 3 | F14 |
| `sub_account` | 1 | F13 |

All 19 currently fail because no personas exist — that is C5. **The standing
caveat is now discharged: "10/10 green" finally means what it says.** Before
this cluster the loop could have reached 10/10 while extracting no line items,
no surcharges and no scan line at all.

---

## Design decisions

### Stage 5a holds a factory, not an executor

An `Executor` is bound to one persona, and the persona is looked up per document
at Stage 4. A single injected executor instance would therefore either be stale
or belong to whichever document arrived first. `ApplyCachedRules` now takes
`executor_factory: Callable[[Persona], SupportsApply]`, defaulting to `Executor`.

This changed the injection site in two Part A routing tests
(`tests/pipeline/test_stages_skeleton.py`). The invariant each test asserts — a
persona hit costs zero vision calls; a collapsed persona falls back to vision —
is untouched; only the seam moved from `executor=stub` to
`executor_factory=lambda persona: stub`.

### Row groups live in `ctx.row_groups`, and only three are promoted

`ctx.row_groups: dict[str, list[dict]]` is keyed by the persona's `row_group`
name. `build_record` lifts `line_items`, `charges` and `sub_account` into their
own top-level keys and **ignores everything else**. A new top-level contract key
is a contract change; it should need an edit to `_PROMOTED_ROW_GROUPS`, not
appear because a persona author picked a name. There is a test for that.

Row groups are kept out of `ExtractedFields` because a repeating table is not a
name→value pair, and flattening one in would make `fields.line_items` a list
inside a mapping every other consumer reads as scalars.

### `scanline` is a bare string, not an object

`extract.scanline.find` returns `str | None`, so that is what the record carries.
The gold label's `scanline` is a rich object, but its `encodes_account` /
`encodes_amount` keys are *analysis of what the digits mean*, not something the
pipeline transcribes — asserting them would score the label rather than the
extraction. The scorecard compares `record["scanline"]` against
`gold["scanline"]["raw"]` and nothing else.

`validate_record` rejects a non-string scanline: leading zeros carry meaning to
a lockbox scanner, so it must never arrive as a number.

### A multiset of amounts, not the plan's signed sum

The plan specified "count and signed sum". The sum was replaced with a **sorted
multiset of amounts**, for two measured reasons:

1. **A sum cancels errors a multiset catches.** Two rows with swapped amounts,
   or a pair of compensating errors, net to the same total and would pass
   silently. The multiset costs nothing extra to compare.
2. **A sum would have implied an arithmetic claim the corpus does not support.**
   Measured across the five gold files that carry `line_items`: four close
   exactly against a printed total (Complete Beverage 1177.70, DTSS 699.00,
   Federal Recycling 481.20, Veritiv 4608.45 = `subtotal`). EDCO does not — its
   statement table prints a `CURRENT CHARGES:` summary row *inside the table
   body*, so its amounts total 437.58 against a printed total of 367.96. That is
   the table faithfully transcribed, not an extraction error. Proving closure is
   `crosscheck_line_sum`'s job at Stage 6, where it reports a confidence
   modifier rather than a scorecard failure.

`LINE_ITEM_AMOUNT_COLUMNS` is `{amount, charges, balance, total}`. `unit_price`,
`quantity`, `weight` and `quantity_ordered` are deliberately excluded — summing
unit prices is meaningless and would fail the assertion for reasons that say
nothing about extraction quality.

**A coupling worth stating:** line-item column names come from the persona and
the expectations come from the hand-written gold label, so the two must agree.
That is deliberate — it forces a C5 persona to describe the table the way the
document actually prints it (F19) instead of inventing its own vocabulary.

### Page roles: fail-closed

The executor applies §7 (field values never from a `supporting` page), which
`regions.py` deliberately does not. The role lookup is **fail-closed**: a page
with no `PageMeta` entry counts as supporting. A pipeline that skipped role
assignment therefore extracts nothing visible rather than silently reading
totals off a handwritten Bill of Lading (F10). A loud empty result is
recoverable; a confident wrong one is not.

The scan line is the documented exception — scoring-only, so §7 does not apply,
and must not: the remittance stub of a multi-page bill routinely lands on a
continuation page that is legitimately `supporting`. There is a test for that.

### What the executor refuses to do

Each of these would be the executor quietly taking over another stage's job, and
each has a test pinning the boundary:

- **No `adjust` ops.** §4 runs them at Stage 6. `s6_capture` reads them off
  `ctx.persona`, so no intermediate "pending ops" structure has to exist and
  none can drift out of sync with the persona that produced it.
- **No confidence arithmetic.** It records `match_quality` (1.0 anchored / 0.95
  anchor-alt / 0.90 region-only) and appends modifier *names*. `core.confidence`
  turns those into a number at Stage 6.
- **No `required` enforcement.** A missing required field is a miss, priced at
  Stage 6 and routed at Stage 7. Raising here would turn an ordinary, reviewable
  gap into a pipeline error.
- **No `row_count` filtering.** Truncating to `max` would silently discard real
  rows. A violation is logged and left visible; there is no modifier for it in
  the closed §5 enum, and inventing one here is the quiet vocabulary growth the
  grammar forbids. Wiring it to review is C4's call.

### The 50 ms budget, and its honest residual

§3.2 promises "Timeout → field miss + `pattern_timeout` modifier, never a wedged
worker". A true preemptive timeout is not available in pure Python without
threads or signals, so the budget is checked **between candidate strings**. Each
candidate is a cell, a word or a line — short — so total time per field is
bounded by the budget plus one candidate's runtime.

**Residual, stated plainly:** a single pathological match against one candidate
can still overrun the budget. What makes that acceptable is C2a's static
restrictions (no unbounded quantifiers, no nested quantifiers, ≤200 chars, ≤1
capture group), which is why those two halves were always meant to ship together.

When the budget blows, whatever was found so far is **discarded**, not kept — a
partial `all_matches` list is worse than a visible miss because it looks complete.

---

## Defects found during the run

1. **`_column_bounds` abandoned its search after the first header.** A
   `for/else/break` treated "the accumulated text ran past the needle length"
   identically to "matched", so the outer loop exited. Every cell of every row
   landed in the leftmost column. Fixed by extracting a shared `_runs` helper —
   anchor lookup and column-header location are the same operation asked twice —
   where the length guard only ever ends the inner scan. Removed a block of
   duplication as a side effect.

2. **A single declared column swallowed the whole row width.** The column grid
   was derived from the *declared* columns, so a persona naming only `amount` on
   a `DESCRIPTION | AMOUNT` table got one column spanning the full page and
   `currency` matched none of the cells. The grid is now built from **every**
   cell of the header row, with declared columns mapped onto it.

3. **`line_items` ran to the foot of the page.** Caught by the end-to-end test,
   and the most consequential of the three: the `line_items` region starts below
   the table header and ends at the page bottom, so the row group swallowed the
   totals block, the remittance stub and everything else below the table. **This
   is the common case, not a corner case** — every corpus invoice prints a totals
   block below its table and five also print a stub — so row groups would have
   been unusable in C5 and the F8 closure check meaningless.

   Fixed with a vertical-rhythm break: a gap larger than
   `max(24pt, 2.5 x established row pitch)` ends the table. The pitch is seeded
   from the header-to-first-row gap. Three tests pin it: a table followed by a
   totals block 120pt below, a uniformly spaced 20-row table that must *not*
   break, and a tightly-leaded 6pt-pitch table that must survive a 15pt gap
   (which is what the floor is for).

---

## Known limitations, for C5 to push on

- **Table-end detection is geometric only.** A table with a genuine internal
  section header separated by a large gap will truncate early. No corpus
  document does this; the generous 2.5x factor is the mitigation, and a real
  persona hitting it will show up as a short `line_items.count`.
- **Two tables with the same row pitch and no gap between them** will merge. The
  break rule needs vertical separation to see a boundary.
- **`text` and `text_block` candidate granularity is coarse.** Candidates are
  tried cells → words → whole line, first match wins, with the anchor's own
  words excluded. Good enough for anchored numeric fields; multi-line addresses
  will want tuning once real personas exercise them.
- **`_norm` strips a trailing colon and is otherwise strict.** `Total` will not
  match `Total:` — it will, via the colon rule — but `Total` will not match
  `Totals`. That is deliberate (substring matching would find `TOTAL` inside
  `SUBTOTAL`); `anchor_alts` is the escape hatch.
- **No `ocr_source` modifier is applied.** `Span` carries `source` precisely so
  Stage 6 can, but nothing emits it yet.

---

## Notes for C3

- `ctx.persona` is where the `adjust` ops are. Read them from the selector that
  declared them, in declaration order, per §4.
- `ctx.extracted.match_quality[field]` is the base for `apply_modifiers`.
- `ctx.row_groups["line_items"]` holds Decimals, not strings — serialization to
  string happens in `build_record`, so arithmetic ops work on exact values.
- `derived.*` is still empty, so `validate_record` still cannot require
  `document_identity` / `identity_basis`. That was C3's to unblock and still is.
- The corpus fact worth knowing before writing `crosscheck_line_sum`: EDCO's
  table contains its own summary row, so Σ line_items ≠ subtotal there by
  construction. Do not treat that as a mismatch to flag.
