# Resume here

Stopped deliberately on 2026-07-27 partway through the convergence loop. Everything
needed to pick up is in git. Nothing is half-committed.

## State in one block

```
branch      feat/pipeline          (base: main @ c82eb76, docs-only baseline)
HEAD        063254f                clean tree, 42 commits
tests       1,242 passing in ~7.2s
mypy        python3 -m mypy        -> 0 errors (covers core/ and grammar/)
ruff        ruff check src tests   -> clean
gold        python3 docs/corpus/validate_gold.py -> 95 checks green
scorecard   0/10 documents green, 211/339 assertions
```

**The 10/10 caveat is discharged, and now enforced.** C2b closed it for the four
contract keys; C3b closed it for the confidence modifiers, 29 unasserted gold
fields and the `lane`. 339 is the honest denominator.

`tests/test_scorecard_coverage.py` (**GUARDRAIL 3**) now makes this mechanical
rather than something to remember: every gold fact must be asserted or explicitly
classified, and **no assertion may pass against an empty record.** Adding a gold
file fails that test until someone classifies it. Standing rule 3 had been
violated five times before it existed.

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
- C3 — the 23 adjust ops, unconditional `derive_document_identity`, a real
  `s6_capture`, the identity contract requirement, `test_f1_antiregression.py`,
  +10 `lane` assertions. 0 rounds. One spec correction and two measurement
  findings; see `execution/task-c3-report.md`.
- C3b — scorecard coverage (+87 assertions) and GUARDRAIL 3. 0 rounds. Corrects my
  own C3 finding in both directions; see `execution/task-c3b-report.md`.
- C4 — a real `s7_gate`: four lanes, forced review, deterministic audit sampling,
  and GUARDRAIL 4. 0 rounds. Two spec errata and one real bug caught only by the
  whole-path test; see `execution/task-c4-report.md`.
- C5a — the pack registry, the Northstar pack (7 modules), 6 authored personas,
  and the Stage 3/4/7 wiring. 0 rounds. **42 → 128 assertions.** One grammar
  extension, one design flaw found in C3, and three known formatting limitations;
  see `execution/task-c5a-report.md`.
- C5b — the Digital Direction pack, 4 carrier personas, the claim-gating fix, and
  GUARDRAIL 6. 0 rounds. **130 → 211 assertions**, and Centracom's $20,123.80 trap
  now derives correctly; see `execution/task-c5b-report.md`.

**Read `execution/task-c5b-report.md`'s "What is still failing" before continuing.**
The remaining 128 failures are dominated by **addresses and vendor names**, not
extraction logic. One change would close most of the address failures: a region
between `near-anchor` and `header-block` — call it `label-block`, the anchor's own
column from the anchor line down to the next blank line. Two vendor names
(Lumen's logo, Windstream's `Windstre am`) are not in the text layer at all and
cannot be captured by any pattern.

The title-case question C5a raised **is decided and shipped**: the scorecard now
compares transcribed text case-insensitively (`kind="text"`). A `title_case` op
was rejected because it would be actively wrong — `LLC` → `Llc`, `OCC` → `Occ`.

## Next: four dispatch units

Sizes are calibrated against C1a (458 src lines / 6 files), C1b (568 / 6),
C2a (1,150 / 4) and C2b (760 / 5). Both C2 estimates ran ~30–60% over, almost
entirely in test lines, so treat the numbers below as floors.

| # | Cluster | Delivers | Est. src | Score after |
|---|---|---|--:|---|
| 1 | **persona polish** *(new)* | a `label-block` region + address/vendor selectors | 100–200 | most of the remaining 128 |
| 2 | C6 | Anthropic vision adapter + cassettes + real `s5b` | 300–400 | — |
| 3 | C7 | SQLite persona store + real `s4`/`s5c` | 400–500 | fast lane |

Every stage is now real except Stage 5b (the vision adapter is still the fake).
**Both F1 traps derive correctly on the real PDFs** — EDCO 69.62 rather than
367.96, and Centracom 13,752.60 rather than 33,876.40, the latter against a
scan line that encodes the trap value.

**Of the 128 still failing, the large majority are addresses and vendor names.**
No document is fully green; DTSS is closest at 23/24, failing only on a two-line
vendor address. Neither C6 nor C7 is on the critical path for the score — the
next real gain is persona polish.

**Optional reorder, now actionable:** hand-author ONE persona for the cleanest
document (D.T.S.S. — one page, three line items, no prior balance) to prove the whole
chain end-to-end at 1/10 before building both packs out. Costs a little rework, buys
much earlier signal. C2b's end-to-end test is a working template for the shape.

## How to dispatch a cluster

Briefs are generated from the plan, not hand-written:

```bash
python3 .superpowers/sdd/2026-07-27-pipeline-implementation/brief.py C5
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
8. **A second pack can silently break the first.** Every hook in a `HookRegistry`
   runs on every document, so Digital Direction's ladder overwrote Northstar's
   `doc_type` and all six Northstar persona lookups missed by key. DTSS dropped
   from 23 passing assertions to 4 and **nothing failed** — only the scorecard
   noticed. Pack hooks are gated on the claim in `packs/registry.py`, not in each
   pack, because a pack that forgot the guard would break a *different* pack.
9. **An assertion that passes on an empty record is a free pass, not coverage.**
   C3b found 2 of the then-39 passing assertions were satisfied by a pipeline that
   computed nothing. Prefer a composite ("the value exists AND no mismatch was
   flagged") over a bare absence check; where a vacuous pass is genuinely correct,
   key it into `VACUOUS_BY_CONSTRUCTION` with a written reason and a mitigation
   test. GUARDRAIL 3 enforces this.
10. **A cluster that adds a pipeline capability must finish with one whole-path test.**
   C2b's worst defect — `line_items` swallowing the totals block and remittance stub that
   sit below *every* invoice table — passed all 42 unit tests and was caught only by the
   end-to-end test that ran a real validated persona through Stage 5a into a validated
   Stage 8 record. Unit tests confirm the units; only the whole path shows what the units
   compose into.

## Deferred, with homes

- ~~**4 contract keys**~~ — **DONE in C2b.** All four are on the record, type-checked by
  `validate_record`, and asserted by the scorecard (+19 assertions). 10/10 green now means
  what it says.
- ~~**`has_flattened_annotations` → forced review**~~ — **DONE in C4.** The full chain
  runs and Federal Recycling reaches its gold routing. Pinned by GUARDRAIL 4
  (`tests/test_f3_forced_review.py`).
- **`document_identity` / `identity_basis` validation** — `validate_record` cannot require
  them yet because no derive op produces them. Scheduled into C3.
- **Minor deferred items** — collected in the ledger, one line each, for the final
  whole-branch review to triage.

## Open questions still with the business

Unchanged from `docs/README.md`: confidence thresholds, audit-sample rate, review SLAs,
regeneration cadence, U-Pak's unexplained −$48.92, and whether annotated and clean copies
of the same invoice both arrive.
