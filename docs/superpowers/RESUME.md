# Resume here

Stopped deliberately on 2026-07-27 partway through the convergence loop. Everything
needed to pick up is in git. Nothing is half-committed.

## State in one block

```
branch      feat/pipeline          (base: main @ c82eb76, docs-only baseline)
HEAD        0f0ce2c                clean tree, 32 commits
tests       558 passing in ~7.8s
mypy        python3 -m mypy        -> 0 errors (covers core/ and grammar/)
ruff        ruff check src tests   -> clean
gold        python3 docs/corpus/validate_gold.py -> 95 checks green
scorecard   0/10 documents green, 39/242 assertions
```

**The 10/10 caveat is gone.** C2b landed the four contract keys, so the scorecard
now asserts `line_items`, `charges`, `scanline` and `sub_account`. 242 is the honest
denominator; reaching it means the corpus really is satisfied.

Verify all of that in one go:

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests \
  && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold
```

`replay-gold` exits 1 while documents fail — that is expected, not a broken build.

## Read these, in this order

| File | Why |
|---|---|
| `docs/README.md` | The domain. Start here if the corpus is unfamiliar. |
| `docs/corpus-analysis.md` | 21 findings from the 10 sample PDFs. §0 is the one that matters most. |
| `docs/superpowers/plans/2026-07-27-pipeline-implementation.md` | **The plan.** Part A (done) then the Part B cluster catalog. |
| `docs/superpowers/execution/ledger.md` | **Everything that happened.** Every ruling, finding, erratum and process decision, in order. This is the recovery map. |
| `docs/superpowers/execution/task-*-report.md` | Per-task implementer reports — what was tried, measured, and why. |
| `.loop/journal.md` | Convergence-loop journal. |
| `.loop/scorecard.json` | Current machine-readable scorecard. |

## Where the work stopped

**Part A: complete.** 11 tasks, all reviewed. Any PDF traverses all 8 stages and emits a
schema-valid Stage 8 record; `count(intaken) == count(emitted)` is enforced and tested
under injected failures at every stage.

**Part B (the convergence loop): clusters C1 and C2 complete.**

- C1a — `pdf.py`, `ocr.py`, `normalize.py`, wired into stage 2. 3 rounds.
- C1b — `pageroles.py`, `annotations.py`, `scanline.py` + the `page_roles` scorecard
  assertion. 3 rounds.
- C2a — `schema.py`, `patterns.py`, `regions.py`, `validator.py` (V1–V13). 0 rounds.
  Two spec errata and one tightening; see `execution/task-c2a-report.md`.
- C2b — `executor.py`, persona-bound Stage 5a, the four contract keys, +19 scorecard
  assertions. 0 rounds. Three implementation defects found and fixed mid-run; see
  `execution/task-c2b-report.md`.

**Read `execution/task-c2b-report.md` before starting C3.** Its "Notes for C3"
section covers where the `adjust` ops live, what `match_quality` means, and one
corpus fact that will otherwise cost a debugging round: EDCO's statement table
prints its own summary row *inside* the table body, so Σ`line_items` ≠ `subtotal`
there by construction — `crosscheck_line_sum` must not flag it.

## Next: five dispatch units

Sizes are calibrated against C1a (458 src lines / 6 files), C1b (568 / 6),
C2a (1,150 / 4) and C2b (760 / 5). Both C2 estimates ran ~30–60% over, almost
entirely in test lines, so treat the numbers below as floors.

| # | Cluster | Delivers | Est. src | Score after |
|---|---|---|--:|---|
| 1 | **C3** | 4 adjust-op modules + real `s6_capture` + F1 anti-regression test | 400–500 | some `derived.*` |
| 2 | C4 | real `s7_gate` + wire `has_flattened_annotations` to forced review | 150–200 | routing |
| 3 | C5a | pack registry + 6 Northstar modules + 6 persona JSON | 600–800 | most Northstar |
| 4 | C5b | 6 Digital Direction modules + 2 persona JSON | 500–700 | ~8/10 |
| 5 | C6 | Anthropic vision adapter + cassettes + real `s5b` | 300–400 | 10/10 target |
| 6 | C7 | SQLite persona store + real `s4`/`s5c` | 400–500 | 10/10, fast lane |

All the infrastructure is now in place. First real scorecard movement is C3; the
bulk arrives with C5.

**Optional reorder, now actionable:** hand-author ONE persona for the cleanest
document (D.T.S.S. — one page, three line items, no prior balance) to prove the whole
chain end-to-end at 1/10 before building both packs out. Costs a little rework, buys
much earlier signal. C2b's end-to-end test is a working template for the shape.

## How to dispatch a cluster

Briefs are generated from the plan, not hand-written:

```bash
python3 .superpowers/sdd/2026-07-27-pipeline-implementation/brief.py C3
```

If `.superpowers/` is gone (it is gitignored scratch), recreate the extractor — it is
~30 lines that slices the plan by `### Cluster Cn:` heading and prepends the Global
Constraints block. Or simply paste the cluster's plan section directly.

**Regenerate briefs after ANY plan edit.** The plan was edited 11 times mid-execution and
a stale brief nearly shipped a real bug (a `dict` check where a `Mapping` check was needed,
which would have leaked `Decimal` objects into every emitted record).

Then per cluster: dispatch a fresh implementer → generate a review package → dispatch a
reviewer for spec compliance AND quality → fix rounds → scoped re-review → append to the
ledger → commit.

## Standing rules learned the hard way

1. **Fresh implementer per cluster; swap on the SECOND fix round.** One C1b agent reached
   ~390k tokens over three rounds and its returns went flat. Handoff is cheap only because
   every implementer writes its reasoning to `task-*-report.md`.
2. **Corpus-only tests confirm corpus-fit and cannot detect corpus-overfit.** C1b shipped a
   page-role rule that matched all 10 gold labels and still hardcoded page 1 as primary —
   it would have missed the total on any invoice with a cover page. Require synthetic
   fixtures for cases the 10 documents do not contain.
3. **When a cluster adds a capability, check the scorecard measures it.** The scorecard
   originally asserted 12 fields and measured none of ten documented findings; the loop
   could have hit 10/10 with an empty `reference_list`. `page_roles` was the same class of
   miss, found later.
4. **Measure before arguing about cost.** Adding a content hash to the cache key looked too
   expensive to justify; hashing the whole 6.98MB corpus turned out to take 9ms.
5. **Never measure performance while something else is running.** A 210s test run in the
   background produced a bogus "OCR takes 110s per page" reading and sent an agent after
   the wrong hotspot.
6. **`docs/corpus/gold/*.json` is READ-ONLY.** A test byte-compares all ten every run. A
   gold change requires re-reading the source PDF and a written justification.
7. **Self-review the tests, not just the implementation.** All three defects C2a's
   self-review caught were in new tests, and the worst one *passed* — the `same-cell`
   test's fixture helper made a claimed "5pt gap" an actual 23pt column gap, so a green
   test was asserting the opposite of its own docstring. A test that passes for the wrong
   reason is worse than a missing test: it reports coverage it does not have. Recompute
   fixture arithmetic by hand rather than trusting the comment next to it.
8. **A cluster that adds a pipeline capability must finish with one whole-path test.**
   C2b's worst defect — `line_items` swallowing the totals block and remittance stub that
   sit below *every* invoice table — passed all 42 unit tests and was caught only by the
   end-to-end test that ran a real validated persona through Stage 5a into a validated
   Stage 8 record. Unit tests confirm the units; only the whole path shows what the units
   compose into.

## Deferred, with homes

- ~~**4 contract keys**~~ — **DONE in C2b.** All four are on the record, type-checked by
  `validate_record`, and asserted by the scorecard (+19 assertions). 10/10 green now means
  what it says.
- **`has_flattened_annotations` → forced review** — the tag is set but `s7_gate` does not
  consume `ctx.tags`. Scheduled into C4. Federal Recycling cannot reach its gold routing
  until then.
- **`document_identity` / `identity_basis` validation** — `validate_record` cannot require
  them yet because no derive op produces them. Scheduled into C3.
- **Minor deferred items** — collected in the ledger, one line each, for the final
  whole-branch review to triage.

## Open questions still with the business

Unchanged from `docs/README.md`: confidence thresholds, audit-sample rate, review SLAs,
regeneration cadence, U-Pak's unexplained −$48.92, and whether annotated and clean copies
of the same invoice both arrive.
