# Review round — `2026-08-07-classification-correctness.md`

Four independent reviewers (adversarial correctness, codebase fit, test design, scope
and risk), each instructed to verify against the code rather than trust the plan.
Every finding below was **independently re-verified** by the author before being
recorded here; findings that did not survive re-verification are not listed.

**Verdict: the plan does not survive review. Rewrite, do not patch.**

Nine defects are blocking, two of them factual errors that invalidate whole tasks.
The three-move architecture (measure → share → fix) survives and is reused in the
revision. The task list, the sequencing and the forecast do not.

---

## Blocking defects

### B1. Task 1 is written against a scorecard API that does not exist

| plan assumed | reality |
|---|---|
| `assertions_for_gold(gold, record)` | `assertions_for(gold)` — one arg, `scorecard.py:566` |
| an `add(...)` helper | none; the idiom is `items.append(Assertion(...))` |
| `Assertion.passed` | `Assertion` is `(name, expected, getter, kind)`; pass/fail is computed at `scorecard.py:737` via `matches(a.expected, a.getter(record), a.kind)` |

`assertions_for` also unconditionally reads `cls["doc_type"]`, `cls["text_source"]`,
`cls["page_roles"]` and `gold["expected_routing"]`, so the plan's `_gold(**classification)`
helper raises `KeyError` — meaning even the intended red step fails for the wrong
reason. This is a rewrite, not the rename the plan called it.

### B2. Task 1's `forbidden_tags` assertion breaks GUARDRAIL 3

`tests/test_scorecard_coverage.py:563` requires **every** assertion to FAIL against an
empty record. A `disjoint` assertion is vacuous by construction: empty record →
`tags: []` → empty intersection → passes. Both new gold entries would land in
`vacuous`, and the guardrail goes red. The plan never mentions the file.

Standing rule 9 (`RESUME.md:390`) forbids exactly this shape, and its allowlist
requires a written reason *plus* a mitigation test. **The fix is not an allowlist
entry** — it is to make the assertion non-vacuous: require that the record produced
tags at all AND none is forbidden, so a do-nothing pipeline fails it.

### B3. Task 8 is mostly already implemented

- `personas/lumen.json` **already declares** `{"field": "invoice_number", "as": "digits_only"}`
- `fields.py:29` **already registers** `invoice_number`
- `replay-gold` today already passes `fields.invoice_number` = `752233001`,
  `derived.document_identity`, and `derived.identity_basis` = `invoice_number`

Steps 1, 6 and 7 describe completed work. Only the retag hook is missing
(`grep -rn no_invoice_number src/` → 0 hits). Task 8 drops from ~1.5 days to ~1 hour.

### B4. Task 5's algorithm fails its own test, and the real document passes by accident

```
'KINETIC BUSINESS by WINDSTREAM'
  matched:   ['kinetic business', 'kinetic business by windstream', 'windstream']
  outermost: ['kinetic business by windstream']  →  1     (plan asserts 2)
```

`LITERAL_ALIASES` contains the composite `"kinetic business by windstream"`, which
swallows both constituents. The real Windstream bill still returns 2 **only because
its text layer breaks the brand across a line** — a cleaner scan of the same bill
drops it to 1 and loses its gold-required `multi_brand_sender`. Outermost-only is
the wrong discriminator.

### B5. The Centracom forecast is arithmetically impossible

Its gold tags are `[prior_balance_present, past_due, no_invoice_number, has_scanline]`
and `tags` is one superset assertion. Task 8 supplies `no_invoice_number`; `past_due`
is the gated Task 10. The assertion still fails, and Task 1 adds no assertion to that
document. **Centracom ends Tasks 1-9 at 28/31, unchanged** — not `29/32`.

Handing an implementer an unhittable target is the mechanism behind the 2026-08-06
phantom fix. Comcast, Windstream and U-PAK forecasts check out.

### B6. Task 7's real-document tests would silently skip

Both paths are wrong. Real: `docs/CANADIAN WITHOUT NOTES U- PAK 4378107 (1).pdf`
and `…6060DTSS … 699.00000.pdf`. Guarded by `skipif(not os.path.exists(...))`, so
Task 7 reports green having opened no PDF — the 2026-08-06 no-op failure mode inside
the task written to prevent it. `RESUME.md:18` also records that all 12 existing
skips are accounted for; these would break that property.

### B7. No final whole-corpus regression sweep

The 2026-08-06 plan ended with a 111-document batch re-run, and **that is what caught
the phantom fix** — the per-task loop passed clean. This plan ends at 11 gold
documents while four tasks change pack-wide rules. This is the single most important
addition.

### B8. Missing tests that make the fixes unfalsifiable

- **Task 4 has no positive case.** `return False` for DD's `past_due` passes both its
  tests, and `test_digitaldirection_ladder.py` has no `past_due` test at all.
- **Task 8 has no wiring test** — while `test_digitaldirection_ladder.py:147` is
  literally `test_the_refinement_is_actually_wired_into_the_pipeline`, written because
  `retag_prior_balance` "was correct code the whole time it was unregistered."
- **Nothing pins `primary_only=False`.** Task 3 bolds that it must not be "tidied";
  no test enforces it, and a superset assertion cannot see a lost tag.
- **No cross-pack parity test** — the plan's entire thesis is unenforced.
- **Boundary constants unpinned:** `max_line_index` can be anything in [6, 25] and
  every proposed test still passes.

### B9. Claim precision is a live defect, not a measurement exercise

Task 9's fixtures were run against the real `resolve_pack`: **3 of 6 over-claim.**

```
different_company_same_zip   → CLAIMED by northstar
ship_to_only_at_marker_zip   → CLAIMED by northstar         (ZIP only in SHIP-TO)
managed_client_as_line_item  → CLAIMED by digitaldirection  (client named in a line item)
```

The plan's own words rank this above everything else it fixes: "a wrong claim is
worse than no claim… a wrongly-claimed document runs a whole rulebook of another
organization's assumptions." Deferring it to a strict `xfail` while shipping a
Comcast tag fix inverts the plan's own priority ordering.

---

## Non-blocking factual errors

- **Task 4's rationale documents a non-bug.** The comment claims `.*` could span
  pages in `re.search(r"\b30 DAYS\b.*\b60 DAYS\b", everything)`. Verified: without
  `re.S`, `.` does not cross `\n`, and both `page.text` and `all_text` join with `\n`.
  The line-scoping is harmless; the justification is false.
- **Task 2's motivating claim is false.** "Digital Direction's `has_tax` is not
  primary-scoped" — DD has **no `has_tax` tag at all**. The real duplication is one
  copied function, not four.
- **Test counts wrong.** `test_signals.py` as written has 12 tests, not 14; Task 2's
  "1723 → 1737" and Task 3's "1737" inherit it. (The ~1770 end state is coincidentally
  right.)
- **`mypy` covers none of this work.** `pyproject.toml:35-42` limits it to `core`,
  `grammar`, `adapters/vision`. `packs/` and `scorecard.py` are unchecked, so "mypy
  passes" in every task's verification line is not coverage.
- **No task updates a pack spec**, though five tasks change pack policy — and the
  commit immediately before this plan (`a5de1fd`) logged exactly that drift as a
  review finding. Task 7 is the sharpest: `northstar-recycling.md:40` defines
  `foreign_currency` as `currency != USD`; the plan implements a printed postal code.
- **`from tests.packs.fixtures...` will not import.** No `tests/__init__.py`, no root
  `conftest.py`, `pythonpath = ["src"]` only, and zero precedent for cross-test
  imports in this repo.
- **Task 3's Files list contradicts its own Step 2** (delete vs. rewrite
  `_credit_memo_title_present`), and two line ranges are off by one.

---

## Claims that survived attack

Recorded because they are what the revision rests on:

- **`foreign_currency`'s postal-code signal is clean.** 1/11 on gold (U-PAK only) and
  **zero false positives across all 111 second-samples** — 77 text-layer, 34 OCR,
  including 27 handwriting-heavy scans. This was the claim expected to break.
- **Task 8's "no invoice-number label"** survives a broader regex including
  `Bill|Statement|Document Number`: Comcast, Windstream, Centracom = 0 lines each.
- **Task 3's migration is genuinely behavior-preserving** — `_aging_table_has_balance`,
  `_short_line_has_nonzero_tax` and `_credit_memo_title_present` were each read
  line-by-line against the proposed helper; ordering, early returns and page scope are
  exact.
- **Task 4's diagnosis** — Windstream page 3 is `supporting`, the fragment is 5 words,
  narrowing loses no legitimate `past_due` across all 7 telecom second-samples.
- **Task 6's "0 of 7 telecom second-samples print credit-memo wording."**
- **The baseline**: 1720 tests, 1/11 green, and every per-document score in the plan's
  table.

---

## Consequence for sequencing

Two facts invert the plan's value ordering:

1. Task 8 is nearly free (B3), and it is 3 of the 4 failing gold tag assertions.
2. Claim precision is a live defect (B9), not a measurement.

And two facts shrink the shared-module investment: DD has no `has_tax` (so
`label_with_corroborating_value` has one caller pack), and `title_near_top` has one
caller until Task 6. Building `signals.py` before it has a second caller is the
"extract early" instinct that fits an interface to one user.

**Revised order:** measure → cheap high-value fixes → shared module once it has two
callers → sweep. See `2026-08-07-classification-correctness-v2.md`.
