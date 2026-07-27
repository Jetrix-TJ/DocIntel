# Resume here

Stopped deliberately on 2026-07-27 partway through the convergence loop. Everything
needed to pick up is in git. Nothing is half-committed.

## State in one block

```
branch      feat/pipeline          (base: main @ c82eb76, docs-only baseline)
HEAD        0a736b2                clean tree, 29 commits
tests       275 passing in ~6.3s
mypy        python3 -m mypy        -> 0 errors (covers core/ and grammar/)
ruff        ruff check src tests   -> clean
gold        python3 docs/corpus/validate_gold.py -> 95 checks green
scorecard   0/10 documents green, 39/223 assertions
```

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

**Part B (the convergence loop): cluster C1 complete.**

- C1a — `pdf.py`, `ocr.py`, `normalize.py`, wired into stage 2. 3 rounds.
- C1b — `pageroles.py`, `annotations.py`, `scanline.py` + the `page_roles` scorecard
  assertion. 3 rounds.

**C2a was in flight when work stopped and was cancelled.** It committed nothing. It left
`src/docintel/grammar/__init__.py` (an 11-line package stub) which is harmless and
deliberately kept — it makes bare `python3 -m mypy` resolve. Everything else in C2a is
still to do.

## Next: eight dispatch units

Sizes are estimates calibrated against C1a (458 src lines / 6 files) and C1b (568 / 6).

| # | Cluster | Delivers | Est. src | Score after |
|---|---|---|--:|---|
| 1 | **C2a** | schema, 13 named patterns, 14 regions, validator V1–V13 | 700–900 | 0/10 |
| 2 | C2b | executor + 4 contract keys + their scorecard assertions | 350–450 | 0/10 |
| 3 | C3 | 4 adjust-op modules + real `s6_capture` + F1 anti-regression test | 400–500 | some `derived.*` |
| 4 | C4 | real `s7_gate` + wire `has_flattened_annotations` to forced review | 150–200 | routing |
| 5 | C5a | pack registry + 6 Northstar modules + 6 persona JSON | 600–800 | most Northstar |
| 6 | C5b | 6 Digital Direction modules + 2 persona JSON | 500–700 | ~8/10 |
| 7 | C6 | Anthropic vision adapter + cassettes + real `s5b` | 300–400 | 10/10 target |
| 8 | C7 | SQLite persona store + real `s4`/`s5c` | 400–500 | 10/10, fast lane |

The score stays near zero through C2b — those are infrastructure. First real movement is
C3; the bulk arrives with C5.

**Optional reorder worth considering:** after C2b, hand-author ONE persona for the
cleanest document (D.T.S.S.) to prove the whole chain end-to-end at 1/10 before building
both packs out. Costs a little rework, buys much earlier signal.

## How to dispatch a cluster

Briefs are generated from the plan, not hand-written:

```bash
python3 .superpowers/sdd/2026-07-27-pipeline-implementation/brief.py C2a
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

## Deferred, with homes

- **4 contract keys** — `line_items`, `charges`, `scanline`, `sub_account` have no Stage 8
  key, so the scorecard cannot assert them. Scheduled into C2b's plan section. **Until they
  land, 10/10 green does NOT mean the corpus is satisfied.**
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
