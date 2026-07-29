# SDD ledger — plan: docs/superpowers/plans/2026-07-29-weakness-remediation.md

Branch: dev (base main). Working on `dev` directly rather than a new worktree:
`dev` is already the project's feature branch off main, and the OCR disk cache
(`var/ocr-cache`, gitignored) is cold in a fresh worktree, which would make every
scorecard run pay full Tesseract cost on the two scanned documents.

Baseline at start: 202/263 assertions, 1/10 documents green, 1476 tests passing.
Wave 1 = Tasks 1-6. Wave 2+ not in this run.

## Pre-flight scan (before Task 1)

- Task 7 plan text said the line tolerance is "floored at today's 3.0" where its own
  stated intent requires a CEILING (a larger tolerance groups MORE words onto a line,
  so a floor pins every tight page at exactly the value that endangers it). Corrected
  in the plan before execution. Task 7 is Wave 2, not dispatched in this run.
- Known rubric deviations, ruled ACCEPTABLE, not pre-judged for reviewers:
  - Task 6's tests are characterization tests for existing untested ladder branches,
    so they pass on first run rather than failing first. A reviewer may flag the
    missing red phase; ruling if raised: correct as written, the branches exist and
    are unguarded.
  - Task 5 is persona JSON only and has no unit test; the 263-assertion scorecard is
    its gate. Ruling if raised: correct as written, selectors are configuration.

## Progress

Task 1: implemented (commit f8abc65, BASE 84557bf). Scorecard 202/263 unchanged as
predicted; 1484 passed / 12 skipped (the 12 are the pre-existing guardrail-2/6
deferrals). Implementer reported two brief-vs-code deviations it had to make: the
brief's snippets used `ctx.extracted[k] = v` item assignment (real API is
`.set(name, value, quality)`) and a `Gate` class (real class is `ConfidenceGate`).
Both are defects in MY brief's pseudo-code, not in the codebase. Sent to the task
reviewer as two named cross-cutting risks to verify rather than as accepted
deviations. Task review dispatched (sonnet).
Task 1: review clean — spec compliant, quality Approved, 0 Critical, 0 Important.
  Reviewer independently traced the two substitutions and confirmed no assertion was
  weakened: ExtractedFields.get() ignores match_quality, so .set(..., 1.0) is
  behaviourally identical for read purposes; _high_confidence_ctx really does resolve
  to lane high / review_flag False without the tag, so the test proves the tag is what
  flips it. Also confirmed a new frozenset member is inert for the existing
  has_flattened_annotations path (_forced_reasons only intersects ctx.tags).
Task 1: minor (deferred): core/senders.py module docstring still describes the file as
  being about aggregator/sender domains; it now also owns bill-to/roster comparison.
Task 1: minor (deferred): bare-context test builders duplicated across
  tests/grammar/ops/test_infer.py and tests/test_f3_forced_review.py — brief asked for
  file-local helpers, so intentional; future dedup candidate.
Task 1: controller-verified the reviewer's one ⚠️ item (it declined to re-run the
  scorecard, correctly, as out of review scope): replay-gold gives 202/263 and 1/10,
  and no corpus document carries bill_to_mismatch. Both claims hold.
Task 1: complete (commits 84557bf..f8abc65, review clean, 2 minors deferred)

Task 2: BLOCKED — the plan's Task 2 is WRONG, escalated to the human.
  The brief's fix (median pitch, verbatim) fixes the truncation direction and passes a
  hand-verified synthetic test RED->GREEN, but regresses the scorecard 202->200 and
  loses the corpus's only green document. Not committed. Patch preserved at
  task-2-abandoned.patch; working tree reverted, baseline re-verified at 202/263 1/10.

  Three separate findings from the diagnosis, all traced by hand against the real PDFs:

  F1. TWO ASSERTIONS CURRENTLY PASS BECAUSE OF THE BUG. `min`'s collapse-to-smallest
      keeps the break threshold pinned near LABEL_BLOCK_GAP_FLOOR (24.0), and that is
      what correctly terminates two real blocks: DTSS vendor_address (48.14pt section
      gap) and Centracom charges (24.33pt). A more accurate pitch raises the threshold
      and both real section breaks stop breaking. DTSS is the corpus's only green
      document and it goes red. So part of the 202 rests on accidental floor-clamping,
      not on correctness — same class as the project's "defensible figure" deductions.

  F2. THE FIRST GAP IS NOT A PITCH SAMPLE. On DTSS the label-to-first-content gap is
      36.0pt against a body pitch of 14.16pt. It is characteristically larger than the
      body's rhythm and drags a two-sample median up to 25.08. Excluding it is
      principled and independent of min-vs-median — but it fixes DTSS only, leaving
      Centracom's `charges` still regressed (201/263), so it is not a solution on its
      own.

  F3. CENTRACOM HAS NO OUTLIER TO REJECT. Its gaps are 9.92/14.0/14.0 then 24.33;
      14.0 is the honestly representative pitch and is simply too permissive at
      FACTOR=2.0 to reject a 24.33pt section break. No pitch estimator fixes this —
      only a FACTOR/FLOOR change or a break signal that is not pitch-based.

  The brief froze FACTOR and FLOOR ("their roles do not change"), which forecloses the
  only fix. The implementer tried a minimum-sample gate (structural conflict: Centracom
  needs the gate closed at exactly the sample count the synthetic test needs it open)
  and excluding blank-crossing gaps (no effect on either regression; made upak worse).
  Both correctly reverted before reporting.

  My brief was also wrong on the fixture: its literal y-values (gaps 14,4,14,14) cannot
  reproduce the bug at all, because a collapsed pitch of 4 gives max(24, 8) = 24 and a
  14pt gap never exceeds it. The implementer caught this by hand and by running it, and
  built a correct fixture (gaps 14,14,4,26,14) instead. Standing rule 7 earned its keep.
Task 2: HUMAN RULING — defer into Wave 2, execute after Task 8 when FACTOR/FLOOR are
  unfrozen and a re-baseline is already budgeted. Wave 1 is now Tasks 1, 3, 4, 5, 6 and
  stays a no-regression wave. Plan updated: Task 2 carries a deferral banner with all
  four measured findings, and Wave 2's header now orders 7 -> 8 -> 2 with the reason.
  Recorded that Task 2 may legitimately land at 200/263 with a written justification,
  since 2 of the 202 pass only via accidental floor-clamping.
Task 2: deferred (not complete; no commit on this branch; patch preserved)

Task 3: implemented (commit 2c28898, BASE 4087509). Scorecard 202/263 1/10 unchanged as
  required; suite 1490 passed / 12 skipped (+6 tests); mypy, ruff, validate_gold clean;
  RED confirmed (4 failures for the expected reason) before GREEN.
  Notable: no PDF-writing library is a project dependency, so the mixed-document fixture
  was hand-built with an embedded image and no text layer, and verified by printing
  char_count/image_count and by having real Tesseract (not a mock) read the image's text
  back. Cache safety verified empirically rather than by code-reading: identical 175-file
  cache set before and after, zero entries added or removed.
  Implementer flagged one out-of-scope edge case rather than silently patching it: a
  0-page PDF's text_source label flips from "ocr" (old avg-based logic) to "native".
  Sent to the reviewer as a named risk to judge on its merits, not as an accepted call.
Task 3: review dispatched (sonnet).
Task 3: review clean — spec compliant, quality Approved, 0 Critical, 0 Important.
  Reviewer verified all three named risks by direct inspection rather than trusting the
  report: (1) the fixture's image page really has no BT/Tj operator at all, only
  `q ... cm /Im0 Do Q` with a DCTDecode XObject, so pdfplumber genuinely reads "" from it,
  and _IMG_RESOLUTION=200 really does match ocr.RESOLUTION; (2) the merge iterates `meta`
  in document order so reordering/dropping is impossible, and the `or` cannot mask a
  falsy-but-present page because PageText overrides neither __bool__ nor __len__ — the
  only falsy case is a genuinely absent key, already caught by the missing check;
  (3) the 0-page text_source flip is INERT, not a defect, and it verified that
  independently rather than accepting the YAGNI rationale — the classification path
  already indexes ctx.pages[0] unconditionally, so a 0-page document fails earlier.
Task 3: minor (deferred): the "any starved page -> ocr" rationale is stated in both the
  module docstring and the inline comment at the decision point; two places to keep in sync.
Task 3: minor (deferred): pdf.read_pages() reads the full native text layer even on the
  mixed branch, discarding it for pages that get OCR'd. Matches the brief's snippet, so
  not a deviation; a performance note if anyone revisits.
Task 3: controller-verified 202/263, 1/10 green.
Task 3: complete (commits 4087509..2c28898, review clean, 2 minors deferred)

Task 4: implemented (commit 27ee8e0, BASE 2c28898). Scorecard 202/263 1/10 unchanged;
  suite 1495 passed / 12 skipped (+5); mypy, ruff, gold byte-compare clean. 95 insertions,
  0 deletions across 4 files — no persistence or config crept in.
  Its rulings on the two judgement calls I left open:
  - Dead-letter sighting: YES when the ctx carries a real identity, because
    document_identity is computed inside s6_capture, so a document that got past Stage 6
    and failed later still has a genuinely page-derived identity; a later unrelated stage
    failing does not make that identity false. `_minimal_dead_letter` left unchanged on
    the claim that it never has a real identity to offer.
  - Runner lifetime: one index per Runner instance; confirmed against the code.
  Emit-path safety: the call is a pure dict setdefault + equality check with no I/O, and
  it sits inside _emit's pre-existing try/except Exception, so even a hypothetical raise
  degrades to _minimal_dead_letter exactly as a build_record failure does today.
  tests/test_invariant.py (injected failures at every stage) passed unchanged.
  Substitution reported: the brief's Step 5 snippet referenced a nonexistent `_runner()`
  helper and `VERITIV_PDF` constant. That is the THIRD brief of mine with a bad snippet.
  Sent to review as three named risks, including the consequence the implementer's
  dead-letter ruling implies: the "first" pointer can name a failed document.
Task 4: review dispatched (sonnet).
Task 4: review Spec ❌ / Needs fixes — 1 Important, 2 Minor. Risks 2 and 3 both cleared
  under direct inspection (JobContext is non-frozen so the assignment cannot raise; the
  call is inside the pre-existing try; _emit returns a dict on both paths;
  new_context(source_path="") really does give an empty DerivedFields so
  _minimal_dead_letter genuinely has no identity to offer).
  IMPORTANT: the dead-letter ruling produces an uncorroborable duplicate claim. The
  index mutation (setdefault) is committed BEFORE build_record/validate_record are
  attempted. If those raise, the except branch discards ctx and rebuilds a fresh empty
  context, and validate_record exempts dead_letter records from requiring
  document_identity — so document A permanently owns the identity slot while its own
  emitted record carries no identity and no possible_duplicate_of. A later document B
  then points at A, and A's record has nothing to corroborate it. Exactly the
  false-confidence signal this task exists to remove, reintroduced at the edges.
  Reviewer also noted the finding is untested: test_invariant.py does not exercise
  "identity computed, then contract build/validate fails" plus a later same-identity
  document.
  This is NOT plan-mandated — the ordering was the implementer's choice, not the brief's
  — so it is a straight fix round, no human ruling needed.
Task 4: fix round 1/5 dispatched — resumed the original implementer with the finding
  verbatim, both of the reviewer's suggested fixes offered, choice left to the
  implementer, permission to argue the reviewer is wrong on the merits instead of fixing,
  and a required regression test either way.
Task 4: fix round 1/5 (2 addressed, 1 NEW open; commits 27ee8e0..4d3ff14).
  Both original findings ADDRESSED — peek/commit split closes the uncorroborable-claim
  hole, commit sits after validate_record inside the same try so the except fires first,
  and the new regression test at tests/pipeline/test_runner.py:220-263 genuinely
  exercises "identity computed, validate_record raises, later same-identity document"
  and would fail pre-fix.
  NEW BREAKAGE from the fix itself: the split dropped the self-replay guard. peek()
  takes no document_id, so it cannot exclude self-matches, and _emit assigns its result
  directly. Reprocessing one document_id on the same runner now reports it as a
  duplicate of itself. Controller-verified independently before dispatching round 2
  (read duplicates.py:37-45 and runner.py:100-120 directly).
  The instructive part: the guard still EXISTS, in see(), and the brief's mandated unit
  test test_the_same_document_id_twice_is_a_replay_not_a_duplicate still passes — but
  see() is now dead code in the pipeline, so the test asserts a guarantee on a path
  nothing runs. Unit-level coverage gave false assurance about runner-level behaviour.
  Same species as this project's standing rule 10 (only the whole path shows what the
  units compose into).
Task 4: fix round 2/5 dispatched — required a test at the _emit level specifically, since
  tests/core/test_duplicates.py is the layer that passed while the bug shipped.
Task 4: fix round 2/5 (1 addressed, 0 open; commits 4d3ff14..0dad48a). peek now takes
  document_id and owns the self-exclusion; see is redefined as peek+commit composed, so
  there is ONE copy of the logic and see's unit tests are true statements about what
  _emit gets even though _emit never calls see. Re-reviewer verified byte-for-byte
  equivalence to the old see by hand, traced the runner-level test to confirm it drives
  the real _emit -> peek -> commit path and would fail under the reverted signature, and
  checked no other caller of peek exists. Notably it also checked that the three
  REWRITTEN unit tests peek from a different document_id than the one committed, so they
  still test non-mutation and no-op rather than accidentally passing via the new
  self-exclusion path. New breakage: none.
Task 4: controller-verified 202/263, 1/10 green.
Task 4: complete (commits 2c28898..0dad48a, review clean after 2 fix rounds, 2 minors deferred)

Task 5: implemented (commit 20c1211, BASE 0dad48a). 202 -> 203/263, 1/10 green.
  DONE_WITH_CONCERNS: veritiv cleared; windstream re-anchored correctly but its assertion
  still fails on a ~60-char OCR-junk suffix in the PDF's own text layer, left failing
  rather than papered over; edco not fixed on a genuine structural blocker.
Task 5: review — spec compliant, quality APPROVED, 0 Critical, 1 Important, 1 Minor.
  The reviewer independently re-derived EVERY factual claim from the raw PDF text layer
  via pdfplumber, including re-running the two rejected edco anchors and reproducing
  their exact wrong outputs verbatim. It confirmed the debt removals are earned: the
  guardrail tests "is the anchor inside its value", not "does the assertion pass", and
  both cleared entries satisfy the former.
Task 5: IMPORTANT (parked with ruling): `anchor_occurrence: "last"` is count-dependent,
  not structurally guaranteed, and this diff is its first real use in the repo. It
  resolves correctly only because exactly two bare-word matches of the payee name exist
  per primary page. The reviewer found veritiv has a THIRD occurrence (`Veritiv,` at
  y=384.4) and windstream two more (`Windstream.` y=522.8, `WINDSTREAM,` y=541.6) that
  miss only because `_norm` (executor.py:141) strips a trailing colon but not a comma or
  period. One punctuation change in a future invoice and "last" silently resolves to a
  footer line, with no validation failure to catch it — GUARDRAIL 5 checks grammar shape,
  not layout stability.
  RULING: park, do not fix in this task. There is no in-scope fix. The reviewer itself
  says do not revert ("first" is demonstrably worse), and the only real fix is an
  nth-occurrence primitive in the grammar — a Python change the brief forbids, and the
  same gap that blocked edco. Two independent cases now demonstrate the need, which is
  stronger evidence than either alone. Carried into the plan as a Wave 2 candidate and
  flagged for the final whole-branch review. Surfaced to the human as overrulable.
Task 5: minor (deferred): grammar/schema.py:181-186 (pre-existing, outside this diff)
  asserts "the occurrence above the remittance block is the LAST one" for all three
  personas INCLUDING edco. The implementer's testing via the real Executor shows that is
  false for edco, whose name prints three times so "last" lands on the vendor-address
  block. A stale comment that would mislead a future author into thinking edco is a
  trivial anchor_occurrence fix.
Task 5: complete (commits 0dad48a..20c1211, review approved, 1 Important parked, 1 minor deferred)

Task 6: implemented (commit 00a7cf4, BASE 20c1211). Tests only, no src/ change.
  6 new tests (4 DD, 2 Northstar); suite 1501 -> 1507 passed / 12 skipped; scorecard
  unchanged at 203/263, 1/10. No new test revealed a bug — all four branches behave as
  documented. Meaningfulness confirmed by perturb/observe/restore on all 5 non-trivial
  assertions; each perturbation flipped the assertion to a documented FAILED first.
  It also spotted my uncommitted plan edit in the working tree, identified it as not its
  own work, and deliberately kept it out of its commit. Committed separately as f5f0423.
Task 6: first review attempt died on a network error (ENOTFOUND) before producing a
  report. Infrastructure, not a substantive failure. Verified the tree was untouched and
  clean at f5f0423, then re-dispatched the identical review on a fresh agent with a note
  that a prior attempt died and to start fresh.
Task 6: review clean (retry attempt) — spec compliant, quality Approved, 0 Critical,
  0 Important. Reviewer hand-traced all six fixtures against the real ladder order in
  both packs and confirmed each reaches the branch it claims with no earlier rung firing;
  confirmed every assertion pins the full (doc_type, signal_that_fired) tuple rather than
  just [0]; confirmed neither Northstar fixture contains "northstar recycling" anywhere,
  so the own_paperwork four-line trap is avoided; and hand-traced _has_table to show the
  negative fixture's line has exactly 3 money tokens, which is what flips it and pushes
  classification past the statement branch. Most importantly it re-derived the
  perturbation evidence from the ladder source for all 5 non-trivial assertions and
  confirmed every described edit produces the described flip.
Task 6: minor (deferred): the two simple positive DD tests have no docstrings, unlike the
  rest of the file. Matches my brief's snippet verbatim, so a style nit.
Task 6: controller-verified the one ⚠️ item — 1507 passed / 12 skipped, mypy 27 files
  clean, ruff clean, gold internally consistent, scorecard 203/263 1/10.
Task 6: complete (commits 20c1211..00a7cf4, review clean, 1 minor deferred)

## WAVE 1 COMPLETE — 5 of 6 tasks landed, 1 deferred by human ruling

Commits fcf47f3..f5f0423. Scorecard 202/263 -> 203/263, 1/10 green. Suite 1476 -> 1507
passed, 12 skipped (unchanged, the pre-existing guardrail-2/6 deferrals).
Deferred minors for the final review to triage: 6. Parked Important: 1 (Task 5's
anchor_occurrence fragility). Deferred whole task: Task 2 -> Wave 2.

## Fix wave (whole-branch review) — commits f5f0423..0d9107a

All 9 findings ADDRESSED. Re-review clean. 1508 passed / 12 skipped, mypy 27 files clean,
ruff clean, gold 95/95, scorecard 203/263 1/10 — unchanged, as Group A being comment-only
requires. Controller-verified independently, including that `grep "def normalize_name"
src/` returns exactly 1 hit and `see` is gone.

The Critical the whole-branch review found, and which five task reviews missed: Task 1's
bill_to_mismatch is reachable ONLY from the printed rung, and 5 of 10 personas declare no
bill_to_name selector (comcast, windstream, edco, upak, veritiv), so they always take rung
2 — where _roster_match is a whole-page re.search with no head-of-line rule. Controller
reproduced it: a Veritiv-template invoice billed to Contoso that merely mentions Northstar
in a shipping line yields derived bill_to_name = "Northstar Recycling", no tag, routes
high. Weakness A2 surviving on the majority path, with a test docstring certifying it as
correct. I wrote that docstring in the brief.

B5 judgement accepted: PermanentError, not TransientError. The trigger is deterministic
(pdf.read_meta naming a page pdfplumber lacks) and ocr_pages writes the short result to
the disk cache BEFORE the completeness check, so retries can never see a different answer
— a "transient" error the cache makes permanent. tests/test_invariant.py already
parametrizes PermanentError at every stage boundary, so the invariant is covered.

Task 4: parked (fix-wave residual) — identity-capture ordering. The B2 reorder moved
  `peek` above the beforeEmit hook (so hooks can observe possible_duplicate_of) but the
  `identity` local is captured BEFORE the hook and reused for `commit` AFTER it, while
  build_record reads ctx.derived fresh after the hook. A future beforeEmit hook mutating
  derived.document_identity would desynchronise the committed identity from the shipped
  record's. RULING: park. Verified inert — beforeEmit is declared as a socket
  (pipeline/hooks.py:24) and NO pack registers anything on it, so there is no trigger.
  This is the only re-review by design; a controller fix would skip review for a
  one-line caveat. Registered as a Wave 2 item instead, which is more visible than a
  docstring. Note it is the inverse of the pre-fix arrangement: identity used to be
  captured after the hook, so peek/commit and the record agreed but the hook could not
  observe the field. The reorder traded an unobservable-but-consistent arrangement for an
  observable one with a latent inconsistency. Wave 2 should capture identity once, after
  the hook, and peek from that.

## WAVE 1 CLOSED

fcf47f3..0d9107a, 15 commits. 202/263 -> 203/263, 1/10 green. Suite 1476 -> 1508.
5 of 6 tasks landed; Task 2 deferred to Wave 2 by human ruling.
Deferred minors: 4 shipped as debt, 2 corrected in the fix wave.
Wave 2 inherits: Task 2 (block-break), Task 8c (nth-occurrence primitive), the rung-2
mention gap, the per-page threshold recalibration, the gate's forced-vs-collapse ordering,
and the identity-capture ordering.
