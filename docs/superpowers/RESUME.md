# Resume here

Stopped deliberately on 2026-07-29 after the printed-fields-only narrowing.
Everything needed to pick up is in git. Nothing is half-committed.

## State in one block

```
branch      feat/pipeline          (base: main @ c82eb76, docs-only baseline)
tests       1,426 passing, 12 skipped, in ~8.5s
mypy        python3 -m mypy        -> 0 errors (core/, grammar/, adapters/vision/)
ruff        ruff check src tests   -> clean
gold        python3 docs/corpus/validate_gold.py -> 95 checks green
scorecard   1/10 documents green, 193/263 assertions
```

**All 12 skips are guardrails 2 and 6**, skipped with the deferral reason as the
skip message. Nothing else in the suite is skipped, and no skip is
unexplained — see "printed-fields-only" below.

Per document, measured 2026-07-29:

| Document | | Document | |
|---|--:|---|--:|
| Centracom | 25/29 | EDCO | 17/26 |
| Comcast | 25/29 | Complete Beverage | 17/25 |
| Lumen | 24/29 | Veritiv | 16/31 |
| Windstream | 24/27 | Federal Recycling | 14/23 |
| **DTSS** | **19/19 PASS** | U-PAK | 12/25 |

**The 10/10 caveat is discharged, and now enforced.** C2b closed it for the four
contract keys; C3b closed it for the confidence modifiers, 29 unasserted gold
fields and the `lane`. 263 is the honest denominator today; it was 339 before the
narrowing removed the derived and arithmetic assertions from it. It was 262
until the final whole-branch review found one genuinely FAILING assertion
(`fields.vendor_email` on Complete Beverage) that had been retired as a spec
decision, and put it back.

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
- *(polish rounds)* — the `label-block` region, header-less row groups, PUA-glyph
  stripping at the pdfplumber boundary, the page-1-first remittance search, and four
  cross-check bugs that were penalizing correct extractions. **211 → 274 assertions.**
- C6 — `AnthropicVision`, `CassetteVision`, the vision privilege boundary
  (`adapters/vision/policy.py`), `--vision {cassette,fake,live,record}`, and
  GUARDRAILs 7 and 8. 0 rounds. **Scorecard deliberately unchanged** — the plan's
  10/10 exit criterion required cassettes hand-authored from gold, which scores the
  gold answer against itself. Read `execution/task-c6-report.md` before touching the
  vision path.
- **printed-fields-only** — both packs narrowed to values printed on the
  document. `REQUIRED_ANY_OF` + a V13 any-of clause, so EDCO's bill_date-only
  shape stays writable. Derived work is **deferred, not deleted**: every module
  and unit test is on disk, guardrails 2 and 6 are `skip` with the reason as the
  message, and gold still records the derived answers. Re-enabling is a wiring
  change. See `specs/2026-07-28-printed-fields-only-design.md`.

  **The plan's predictions were wrong in both directions, and the measured
  numbers are the ones to trust.** The spec forecast 175–200 of ~230 assertions
  and said 10/10 became reachable; the actual end state is **193/263 with 1/10
  green.** The denominator is 32 higher than forecast because two rounds of
  review refused to over-defer — most sharply in Task 4, where three fields that
  had never had a selector were moved *back* into the denominator, dropping the
  rate from 73.8% to 73.7% on purpose. 10/10 is not close: nine documents each
  still miss 2–15 assertions, almost all of them per-document selector work.

  `tests/test_scorecard_coverage.py` now splits the accounting three ways, and
  the distinction is the thing a future reader most needs:

  | List | n | What it means |
  |---|--:|---|
  | `DEFERRED_DERIVED_FIELDS` | 5 | Not printed at all. Cannot come back without re-enabling derivation and its guardrails. |
  | `DEFERRED_PRINTED_FIELDS` | 6 | Printed, and had a *working* selector **on at least one document** until the narrowing. Left for deliverability. **This is the list that shrinks first when scope widens.** |
  | `EXTRACTION_DEBT` | 2 | `tax_id`, `vendor_parent_reference`. Printed, gold-labelled, and never given a selector by any persona — before this spec or after. **Registered in their packs' `FIELDS`, still in `CHECKED_FIELDS`, still measured, still failing.** Moving either into a deferral list would delete a pre-existing gap from the denominator and call it a spec decision; un-registering the names (which this branch briefly did) makes the debt *unpayable*, because V1 rejects a selector targeting an unregistered field. |
  | `CHECKED_FIELDS_BY_GOLD` | 1 | The same debt where it belongs to one *document*. `vendor_email` is a deferral on Lumen (a working selector, a passing assertion) and debt on Complete Beverage (no selector ever, a **failing** assertion) — a name-scoped bucket cannot say that without being wrong about one of them. |

  **"had a working selector" is the honest wording and the earlier "extracted by a
  working selector right up until the narrowing" was not.** `vendor_email` is the
  counter-example above. `currency` needs the same care: Lumen printed a literal
  `(USD)` and `federal_recycling.json` had a selector too, but **8 of the 10
  `fields.currency` passes came from `infer_currency` writing to `derived`**, not
  from ink — the scorecard's `_field_value` falls back to `derived`, which is why
  they scored at all. Re-widening scope recovers two documents by selector; the
  rest need the F14 ladder back.

- **final whole-branch review** — six task-scoped reviews all passed; a review of
  the branch *as a whole* found one Critical and five Important issues none of
  them could see. All fixed in a single wave. Full account in
  `execution/ledger.md`, last section. Two of them change what you should believe
  about this branch:

  **The Critical was a false claim, not a missing one.** Unregistering
  `refine_prior_balance_tags` left `ladder.tags_for`'s anchor-text guess as the
  pipeline's final answer, and Centracom prints a payment anchor — so the record
  said `prior_balance_cleared` on a document with $20,123.80 outstanding. The
  spec accepts saying *nothing* about the payable; it does not accept saying
  something false. The refinement is re-wired against `prior_balance` and
  `payments_credits`, both printed, and re-registered. It survived six reviews
  because Centracom's gold `tags` assertion is a **superset** check that was
  already red — the regression went FAIL → FAIL, and no number moved.

  **The `(0.90, 0.99)` dead band is the thing to fix next in the gate.** With the
  crosscheck corroboration boosts unwired, measured per-field confidence is
  binary: 27 fields at 0.90 and 71 at 0.99 across the corpus, nothing between
  except on the two documents carrying document-wide multipliers. Every threshold
  strictly inside that band is now "0.99 or fail", which is why **EDCO and
  Veritiv raise review flags gold calls `False`** (two false-positive reviews on
  clean documents) and **U-PAK routes `medium` instead of `review`** — it still
  reaches a human, `s7_gate` sets `review_flag` on `medium` too; what it loses is
  the reason code. Deliberately **not** recalibrated: that belongs with the
  per-document persona work, which is where the evidence is. Both pack docs' §6
  now say so in a "dead band" subsection.

**Read `execution/task-c5b-report.md`'s "What is still failing" before continuing.**
The `label-block` region it proposed **is shipped**, and it closed most of the
address failures (211 → 274). The two vendor names it flagged as unreachable
(Lumen's logo, Windstream's `Windstre am`) are still not in the text layer and
still cannot be captured by any pattern — they are vision's job, not a persona's.

The title-case question C5a raised **is decided and shipped**: the scorecard now
compares transcribed text case-insensitively (`kind="text"`). A `title_case` op
was rejected because it would be actively wrong — `LLC` → `Llc`, `OCC` → `Occ`.

## Next: four dispatch units

Sizes are calibrated against C1a (458 src lines / 6 files), C1b (568 / 6),
C2a (1,150 / 4) and C2b (760 / 5). Both C2 estimates ran ~30–60% over, almost
entirely in test lines, so treat the numbers below as floors.

| # | Cluster | Delivers | Est. src | Score after |
|---|---|---|--:|---|
| 1 | **per-document persona polish** | selectors for the 69 remaining assertions | 100–200 | most of the remaining 69 |
| 2 | C7 | SQLite persona store + real `s4`/`s5c` | 400–500 | fast lane |
| 3 | *(decision)* | should an OCR document get a vision second opinion? | — | unlocks C6's machinery |
| 4 | *(decision)* | re-enable derivation downstream of extraction | — | un-skips guardrails 2 and 6 |

**Every stage is now real.** `--vision cassette` (the default) replays recorded
calls; `--vision live` calls the API.

**Both F1 traps still derive correctly — but the pipeline no longer runs the
derivation.** `derive_amount_payable` and its unit tests are intact and green
logic; they are simply not in any persona's `adjust` list. On the real PDFs the
record now carries EDCO's printed 367.96 and Centracom's printed 33,876.40, and
says nothing about the 69.62 and 13,752.60 that are actually payable. That gap is
downstream's to close, by design, and
`tests/test_printed_fields_only_path.py::test_centracom_emits_the_printed_total_not_the_payable`
pins it so it cannot flip back silently without guardrails 2 and 6 coming back
with it.

**193/263 assertions, 1/10 documents green** (DTSS passes at 19/19). Per-document
breakdown is in "State in one block" above.

**C6's machinery is built and unused, on purpose.** All ten documents extract
through `5a_cached` and none collapses, so nothing reaches Stage 5b. Making vision
pay off requires deciding when a vision second opinion is worth its cost — most
plausibly for OCR-sourced documents, whose text layer is the thing we distrust.
That is a policy decision, not a wiring one, which is why C6 did not make it
silently. Windstream's `return_address` and Lumen's logo vendor name are the two
gaps persona work genuinely cannot close; they are what that decision would buy.

**The prove-it-on-one-document reorder is done and paid off:** DTSS passes 19/19, so
the whole chain — pack claim, persona lookup, grammar execution, confidence
pricing, gate, contract — is demonstrated green end to end on a real PDF.
Everything remaining is per-document selector work against that proven chain.

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
11. **Retire expectations before capabilities.** Narrowing `FIELDS` before
   re-verdicting the scorecard leaves the tree red for two whole tasks, and worse:
   V1 rejects the personas, a rejected persona is a lookup MISS, and all ten
   documents silently fall back to vision. Scorecard first, then field sets, then
   personas — in the same commit as their field set.

## Deferred, with homes

- ~~**4 contract keys**~~ — **DONE in C2b.** All four are on the record, type-checked by
  `validate_record`, and asserted by the scorecard (+19 assertions). 10/10 green now means
  what it says.
- ~~**`has_flattened_annotations` → forced review**~~ — **DONE in C4.** The full chain
  runs and Federal Recycling reaches its gold routing. Pinned by GUARDRAIL 4
  (`tests/test_f3_forced_review.py`).
- ~~**`document_identity` / `identity_basis` validation**~~ — **DONE in C3.**
  `derive_document_identity` runs unconditionally and `validate_record` requires
  both keys to be PRESENT (`None` is a valid value, absence is not). This is why
  they are the one derived thing the printed-fields-only narrowing kept: dropping
  them would break `count(intaken) == count(emitted)`. Pinned by
  `tests/test_printed_fields_only_path.py`.
- **Minor deferred items** — collected in the ledger, one line each, for the final
  whole-branch review to triage.

## Open questions still with the business

Unchanged from `docs/README.md`: confidence thresholds, audit-sample rate, review SLAs,
regeneration cadence, U-Pak's unexplained −$48.92, and whether annotated and clean copies
of the same invoice both arrive.

## Guardrails, and what each one is guarding against

| # | Test | Would otherwise happen silently |
|---|---|---|
| 2 | `test_f1_antiregression.py` **(`skip`ped)** | a selector pointed straight at `amount_payable` looks right on 7/10 documents |
| 3 | `test_scorecard_coverage.py` | an assertion satisfied by a pipeline that computed nothing |
| 4 | `test_f3_forced_review.py` | values invisible to the text layer emitted without a human ever looking |
| 5 | `test_personas_validate.py` | a rejected persona is a lookup *miss*, so the document falls back to vision quietly |
| 6 | `test_f1_centracom_trap.py` **(`skip`ped)** | every corroboration signal points at the wrong number |
| 7 | `test_vision_policy.py` | a vision model gains the power to route a document's lane |
| 8 | `test_cassette_provenance.py` | a hand-authored answer scores against the gold it was copied from |

Guardrails 2 and 6 are the only skipped tests in the suite. The skip message on
each is the deferral reason and the instruction: un-skip them in the same change
that re-registers `derive_amount_payable`. While they are off,
`tests/test_printed_fields_only_path.py` holds their position from the other
side — it asserts that Centracom emits the *printed* 33,876.40 and that no
`amount_payable` reaches the record at all, so re-enabling derivation without
re-enabling its guardrails fails immediately instead of quietly.
