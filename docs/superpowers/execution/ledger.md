# SDD ledger — plan: docs/superpowers/plans/2026-07-27-pipeline-implementation.md

Branch: feat/pipeline
Merge base (main): c82eb76

Pre-flight scan of the plan found 5 defects in the plan's own test code, all
fixed in the plan before Task A1 was dispatched (no user adjudication needed —
each contradicted the plan's own Global Constraints or asserted something other
than its name claimed):
1. scorecard._money compared money via float() — violates "Money is Decimal,
   never float". Replaced with a Decimal-valued `matches(expected, actual, kind)`.
2. test_skeleton_fails_most_assertions pinned summary.failed == 10 — would fail
   on every successful loop iteration. Reframed to guard the instrument.
3. test_all_eight_stages_appear_in_the_event_log never read the event log.
   Split into a sequence test and a real event-log test using a Spy stage.
4. test_invariant_holds_when_a_pack_hook_throws did not test the invariant.
   Renamed; notes that cluster C5 must add the end-to-end case.
5. s3_classify.py contained a `ctx = ctx` no-op. Replaced with a comment.

Plan erratum (fixed): Task A1 step 5 stated "Expected: PASS, 25 tests"; the
brief's own test code specifies 24 (15 parse_money params + 7 not_money params
+ 2 plain tests). Implementation was faithful at 24; the plan's number was
wrong and has been corrected. No implementation defect.

Task A1: implemented (commit eb5fce1) — scaffold + Decimal money parsing, 24/24
  money tests pass, full suite green, validate_gold.py 95 checks green, ruff
  clean. Review dispatched.
Task A1: review clean — spec COMPLIANT, quality APPROVED. Reviewer confirmed by
  live execution: all 15 positive cases parse to exact Decimals, all 7 reject
  cases return None, no float, no abs(), no scope creep.
Task A1: minor (deferred): is_money() is never asserted True for a valid money
  string — only False for the reject list. Coverage gap inherited from the brief.
Task A1: minor (deferred): implementer report said "Deviations: None" without
  noting the 25-vs-24 test-count discrepancy it had itself recorded.
Task A1: ESCALATED to human — plan contradiction, not a code defect. The plan's
  Global Constraints hoisted selector-grammar.md 3.2's regex limits (max 1
  capture group, max 200 chars) as binding "every task", but that section
  governs AGENT-AUTHORED selector patterns. money.py's hand-written MONEY_RE has
  5 named groups and ~436 chars. Awaiting ruling on whether the constraint is
  scoped to selector regexes (affects cluster C2's validator scope).
Task A1: complete (commits c82eb76..eb5fce1, review clean, 2 minors deferred,
  1 escalation pending)
RULING (human, 2026-07-27): regex limits are scoped to AGENT-AUTHORED selector
  patterns only (persona `pattern` fields, grammar V4). Hand-written regexes in
  core/ and extract/ are exempt; money.MONEY_RE stands as written. Cluster C2's
  validator must enforce the limits on persona patterns and nowhere else. Plan
  Global Constraints reworded; briefs A3-A11 and C1-C7 regenerated to carry it.
  Task A1's Important finding is resolved with NO code change.

Task A2: implemented (commit 460f08c) — date parse ladder, 15/15 date tests,
  full suite 39/39, validate_gold.py 95 green, ruff clean. Review dispatched.
Task A2: review clean — spec COMPLIANT, quality APPROVED, no Critical/Important.
  Reviewer verified live: all corpus formats, all 5 never-invent cases, and
  invalid calendar dates (13/45/2025, 02/30/2025) correctly rejected. Only the
  two permitted files touched.
Task A2: minor (deferred): on the invalid-calendar-date path, _ok() resets
  ambiguous_two_digit_year to False even when the year was 2-digit. Inherited
  from the brief's reference implementation, not an implementer choice.
Task A2: complete (commits eb5fce1..460f08c, review clean, 1 minor deferred)
Task A3: implemented (commit d6e4157) — core models with structural
  extracted/derived split, 7/7 task tests, suite 46/46, gold 95 green, ruff
  clean, mypy clean inside core/ (only the expected missing-grammar-dir error).
  Review dispatched.
Task A3: review 1 — spec COMPLIANT, but CRITICAL finding: the V10 separation was
  bypassable via `ef.values[k]=v` and `ExtractedFields(values={...})`. Inherited
  from the brief (plan defect), not an implementer deviation. Data path via set()
  was closed; code path was not, so the design doc's "structurally impossible"
  claim was false as implemented.
RULING (human, 2026-07-27): harden it so the claim is true.
Task A3: fix round 1/5 (1 critical + 1 minor addressed, 0 open; commits
  d6e4157..10dc735) — _GuardedDict rejects derived_only keys on __setitem__ and
  update(); __post_init__ re-wraps caller dicts; test now imports DERIVED_ONLY
  from source so it cannot drift (previously omitted carried_balance). Also fixed
  a pre-existing mypy strict error at dates.py:53 that Task A2's review missed
  because mypy was not in A2's verification list. mypy strict now 0 errors.
  Controller verified all 4 bypass paths raise; suite 50/50; gold 95 green.
PROCESS FIX: mypy strict is now in the verification list for every remaining task.
Task A3: re-review 1 — finding #1 NOT ADDRESSED. `_GuardedDict` closed
  __setitem__/update/ctor but setdefault and |= stayed open: CPython implements
  both in C and neither dispatches to an overridden __setitem__. Findings #2 and
  #3 confirmed ADDRESSED. Controller's own round-1 verification also missed these
  two, having tested only the paths it specified rather than probing the surface.
Task A3: fix round 2/5 (1 critical addressed, 0 open; commits 10dc735..6d8aa81)
  — abandoned dict subclassing for composition: private _values/_match_quality,
  exposed as read-only MappingProxyType views, set() the sole insertion path.
  Controller enumerated the proxy's whole public surface (copy/get/items/keys/
  values) and confirmed all 12 mutation paths blocked; suite 57/57; mypy strict
  0 errors; gold 95 green.
  Residual, by design: `e._values[k]=v` reaches the private name. That is
  Python's universal limit, not an accidental path; flagged to the re-reviewer.
PLAN CHANGE (consequence): A5's contract._serialize must test isinstance(value,
  Mapping) not dict, because .values is now a MappingProxyType. A dict check
  would pass the proxy through unserialized and leak Decimal into records. Plan
  and briefs updated before A5 runs.
Task A3: re-review 2 — finding #1 ADDRESSED. All mutators blocked on both views;
  _GuardedDict fully removed (grep clean); legitimate set/get/items work;
  DerivedFields still unguarded; mypy strict clean; no source caller relied on
  mutating .values. New breakage: none. Deferred: none.
Task A3: RULING on residual `e._values[k]=v` — reviewer independently agreed it
  is unclosable and acceptable: __slots__ does not stop mutating a mutable
  attribute's contents, name mangling is still reachable as
  _ExtractedFields__values, and a frozen dataclass blocks rebinding not mutation.
  Design claim is therefore "no accidental path, one intended writer" — NOT
  "structurally impossible". Design doc wording must be corrected to match.
Task A3: complete (commits 460f08c..6d8aa81, review clean after 2 fix rounds)
Task A4: implemented (commit e2b361f). Controller verified all 16 MODIFIERS
  values against the authoritative table in selector-grammar.md §5 directly (not
  just the brief): 16/16 exact, none extra, none missing; 6 error classes all
  subclass DocIntelError.
Task A4: review 1 — spec COMPLIANT. CRITICAL: apply_boosts did not clamp when
  count<=0 (early return skipped it), so apply_boosts(1.5,0)==1.5. IMPORTANT:
  apply_modifiers had no upper clamp, so apply_modifiers(2.0,[])==2.0. Both are
  brief defects, not implementer deviations.
CONTROLLER RULING (no escalation): the plan's Global Constraints state "a field
  may never exceed 0.99" UNQUALIFIED, whereas selector-grammar.md §5 scopes the
  ceiling to boosts only. That discrepancy was introduced by the controller when
  writing the plan. Resolved toward the plan's stricter reading — CEILING is a
  global invariant on every return path — because it is what implementers are
  working from, it matches the design's own logic that agreeing OCR renderings do
  not establish certainty, and every pack threshold is <= 0.97 so nothing breaks.
  Behavioural consequence, intentional and documented in a test docstring:
  apply_modifiers(1.0, []) now returns 0.99, not 1.0.
Task A4: fix round 1/5 (1 critical + 1 important addressed, 0 open; commits
  e2b361f..d6bc65e) — module-private _clamp() on every return path; 8 new tests
  including a property-style sweep. Controller ran an exhaustive sweep of 1430
  base x modifier-combination cases: zero violations of [0, 0.99]. All
  previously-passing values unchanged (0.765, 0.55, 0.99, 0.81, 0.0, 0.9).
  Suite 72/72; mypy strict 0 errors; gold 95 green.
Task A4: re-review 1 — both findings ADDRESSED. _clamp on all 3 return paths; no
  test assertion removed or loosened (explicitly checked); intentional change
  apply_modifiers(1.0,[])==0.99 ACCEPTED by reviewer; only the 2 permitted files
  touched; mypy strict clean. New breakage: none.
Task A4: complete (commits 6d8aa81..d6bc65e, review clean after 1 fix round)
PROCESS NOTE: briefs must be regenerated after ANY plan edit. A5's brief was
  stale — the plan's contract._serialize was changed to test Mapping instead of
  dict (a consequence of A3's MappingProxyType fix) after the previous
  regeneration. Caught before dispatch; all remaining briefs re-extracted.
Task A5: implemented (commit ea7c171) — Stage 8 contract. Controller verified
  end-to-end: json.dumps round-trips, money crosses as strings ("33876.40"), no
  float in fields/derived, MappingProxyType genuinely serialized to a real dict
  (the stale-brief bug did NOT land), skipped and dead_letter records both
  validate, and the validator rejects all 4 injected mutations (missing key, bad
  disposition, float money, malformed reference entry). 18 REQUIRED_KEYS.
  Suite 82/82; mypy strict 0 errors across 7 modules. Review dispatched.
Task A5: review 1 — spec COMPLIANT (18/18 REQUIRED_KEYS justified against
  pipeline-v2.md Stage 8 and corpus-analysis §6; deltas 1/2/3 all present and
  correctly shaped). 4 IMPORTANT + 3 MINOR findings, all validator PERMISSIVENESS
  (accepting what it should reject), not malformed-input handling.
Task A5: fix round 1/5 (3 important + 2 minor addressed, 1 important DEFERRED by
  design, 0 open; commits ea7c171..33832e8) — validate_record now requires
  non-empty doc_type on processed records, confidence in [0.0, 0.99] excluding
  bool, strict reference_list value types (page int >= 1, bool excluded), genuine
  bools on the three flags, non-empty document_id. 21 new tests. Controller
  verified 12/12 bad records now rejected and 8/8 legitimate records still
  accepted (no over-tightening): skipped/dead_letter with null doc_type, empty
  confidence dict, confidence exactly 0.0 and 0.99, int 0, page exactly 1, empty
  reference_list. Suite 103/103; mypy strict 0 errors; gold 95 green; ruff clean.
DEFERRED WITH A HOME (not dropped): requiring document_identity/identity_basis in
  derived on processed records. Cannot be enforced in Part A — those values come
  from derive ops that do not exist yet, so it would fail every document in the
  walking skeleton. Written into cluster C3's brief as an explicit carried-over
  requirement with rationale (finding F6: 3 of 10 corpus docs print no invoice
  number, so these two fields are the only dedup key downstream has).
Task A5: re-review 1 — all 6 findings ADDRESSED. All 10 original tests present and
  unchanged (the single edit to an original test was finding 6's intended added
  assertion, not a weakening); only the 2 permitted files touched; all 5 new
  checks raise ContractError naming the offending key; mypy strict clean; the
  deliberately-deferred document_identity check was correctly NOT added.
  New breakage: none.
Task A5: complete (commits d6bc65e..33832e8, review clean after 1 fix round)
Task A6: implemented (commit 73d430b) — 8 hook sockets, chain dispatch, failure
  isolation. Controller verified: 8/8 socket names exact; a nested raise names the
  INNERMOST pack and does not accumulate wrapping (packB, single "hook " in the
  message); empty socket returns the same object by identity; short-circuit stops
  the chain; unknown socket rejected at register time. Suite 110/110.
Task A6: CONTROLLER-FOUND GAP (not from the reviewer): a hook that returns None
  is not guarded — HookRegistry.run() returns None and it propagates into the
  pipeline, crashing a later stage far from the cause. `def fn(ctx, nxt):
  nxt(ctx)` without a return is an easy pack-author mistake and precisely the
  class of third-party bug PackError isolation exists to convert into a clean
  dead-letter. Runner (A7) guards stages this way; hooks do not. Brief defect.
  Flagged to the reviewer as an area of attention without stating the conclusion.
Task A6: review 1 — spec COMPLIANT. Reviewer independently confirmed the
  controller-found None gap as CRITICAL, and added: IMPORTANT live-list aliasing
  (registering mid-dispatch splices into the in-flight chain), IMPORTANT zero test
  coverage of malformed-pack cases, plus 3 minors.
Task A6: CONTROLLER ADJUDICATION — 2 findings REJECTED, with reasons:
  (a) "except Exception misses MemoryError" is FACTUALLY WRONG. Verified
      issubclass(MemoryError, Exception) is True and the chain already wraps it as
      PackError. Only KeyboardInterrupt/SystemExit/GeneratorExit propagate raw,
      which is correct: catching BaseException would make a runaway pack
      un-interruptible by Ctrl-C and swallow interpreter shutdown. No change.
  (b) "a hook passing a different context to next() is silently accepted" is not a
      defect. Verified the substituted context flows through the remaining chain
      and is returned coherently — a legitimate functional-style transform.
      No change. Both behaviours are now pinned by tests so no future change can
      silently reverse them.
Task A6: fix round 1 dispatched — return-contract validation (PackError naming the
  pack when a hook returns a non-JobContext), chain snapshot via tuple(), one-shot
  next() guard, docstring, and 8 new tests covering the malformed-pack surface.
Task A6: fix round 1/5 (1 critical + 1 important + 2 minor addressed, 2 rejected
  with rulings, 0 open; commits 73d430b..3f5bafc). Controller verified: all 4
  malformed returns (None, dict, str, int) raise PackError naming the pack;
  next() twice raises PackError; mid-dispatch registration does NOT affect the
  in-flight run but DOES apply to the next run; both rejected findings remain
  pinned (MemoryError still contained, KeyboardInterrupt still propagates raw,
  context substitution still works); empty-socket identity and short-circuit
  behaviour unchanged. Suite 118/118; mypy strict 0 errors; gold 95 green.
Task A6: re-review 1 — all 4 findings ADDRESSED, both rejected findings respected,
  no new breakage, mypy clean. Controller additionally confirmed by name that all
  7 original tests are present and passing (the re-reviewer's answer to that
  question inferred from the report rather than the diff), that the one-shot
  next() guard is per-hook not per-chain (3-hook chain does not trip it), and that
  a malformed return from the MIDDLE of a chain raises PackError naming the
  correct pack.
Task A6: complete (commits 33832e8..3f5bafc, review clean after 1 fix round)
PLAN BUG FOUND BY CONTROLLER, fixed before A7 dispatch: Runner.process() built and
  validated the record AFTER the finally block that increments _emitted. A
  ContractError would then propagate to the caller — no record returned — while
  stats already claimed the document was emitted. The invariant would silently
  become a lie in exactly the situation it exists to catch. Plan now routes
  emission through _emit(), which degrades a failed validation into a minimal
  dead-letter record built from a FRESH context (so no partially-run pipeline
  state can make the fallback fail too), and increments _emitted only after a
  record exists. A regression test was added to A7's brief.
Task A7: BLOCKED on first attempt (correctly — the implementer stopped rather than
  editing a test to make the suite pass). 8/10 runner tests passed; 2 failed.
  ROOT CAUSE: A5's fix round added "processed records require a non-empty
  doc_type", but A7's Ok/Flaky stage doubles never classify, so _emit() correctly
  degraded them to dead_letter and broke their own "processed" assertions.
CONTROLLER RULING: the contract rule and runner are both right; A7's test doubles
  were unrealistically minimal. Verified (a) a processed record with doc_type=None
  is rejected with a clear message, and (b) the real Classify stage in A8 does set
  doc_type="standard_invoice", so live runs were never affected — only these
  doubles. Plan updated: a _classified() helper mirrors stage 3, and Ok/Flaky use
  it. Contract and runner untouched. Brief regenerated; implementer resumed.
  Note this is cross-task coupling the per-task reviews could not have caught:
  A5's tightening was correct in isolation and A7's tests were written before it.
Task A7: RESOLVED and implemented (commit fd01d10). runner.py unchanged from the
  original transcription; only the test doubles were updated. Suite 128/128.
Task A7: controller stress verification — the invariant holds 300/300 under every
  Exception-class failure shape (RuntimeError, MemoryError, PermanentError,
  PackError, TransientError, returning None, returning a non-context), at both
  max_retries=0 and 2, with every returned record passing validate_record.
  Produced 285-287 dead_letters and 13-15 processed per run.
Task A7: CONTROLLER FINDING, ruled NOT a defect. A BaseException (KeyboardInterrupt
  / SystemExit) escapes process(), leaving intaken > emitted. This is correct on
  both counts: (a) catching BaseException would make a runaway pipeline
  un-interruptible and swallow interpreter shutdown — the same ruling already made
  for hooks in A6; (b) the resulting counter gap is the TRUE signal, since a
  document did enter and produce no record. The invariant's scope is therefore
  Exception-class failures, which is exactly what A11's test injects. Boundary now
  pinned by a new test added to A11's brief so no future change can make the
  runner swallow interrupts.
Task A7: review 1 — spec COMPLIANT, quality APPROVED with findings. IMPORTANT:
  self.hooks stored but NEVER invoked anywhere in the pipeline, while the module
  docstring claimed a throwing pack hook was a guarded escape route — the entire
  pack-failure-isolation story was unreachable code. Minors: assert used for
  load-bearing control flow (python -O strips it -> raise None); dead
  ctx.emitted assignment; one test not asserting stats/validate_record.
  Reviewer's ⚠️ item (shared mutable defaults in new_context) RESOLVED by
  controller: every mutable field uses per-call default_factory, fully isolated.
CONTROLLER DESIGN DECISION (recorded because it binds cluster C5): the runner owns
  the 6 BOUNDARY sockets, being the only object that can see the seams between
  stages. classifySignals stays inside stage 3 (a pack injects its ladder there);
  onRegenTrigger belongs to the rule lifecycle. All 8 sockets now have a declared
  owner. beforeEmit deliberately fires inside _emit(), NOT at a stage boundary,
  because skipped and dead-lettered documents break out of _run_stages early yet
  still emit records — a boundary mapping would have silently skipped exactly the
  documents most needing pack enrichment.
Task A7: fix round 1/5 (1 important + 2 minor addressed, 2 rulings, 0 open;
  commits fd01d10..7313570). Controller verified: all 8 sockets accounted for; all
  6 runner-owned sockets fire in declared order; beforeEmit reaches a skipped doc;
  a throwing pack hook yields a dead letter naming the pack with the invariant
  intact; a hook returning None still emits (A6's guard and A7's catch-all compose
  correctly); retry exhaustion now behaves under `python -O`. Suite 131/131.
Task A7: minor (deferred): dead `ctx.emitted = True` assignment retained — the
  field is asserted in A3's tests, so removing it ripples outside A7's file scope.
Task A7: re-review 1 — all 3 findings ADDRESSED, both rulings respected, no new
  breakage, mypy clean. Confirmed: hook dispatch sits inside process()'s failure
  net so a PackError from any boundary socket is dead-lettered; a throwing
  beforeEmit hook degrades via _minimal_dead_letter built from a FRESH context so
  pollution cannot leak; the loop-lambda capture in the boundary test uses an IIFE
  and would genuinely fail if a socket stopped dispatching (not vacuous).
Task A7: ACCEPTED TRUST BOUNDARY (recorded, not a defect): because the after-socket
  runs before the disposition check, a pack hook can reset disposition from
  "skipped" back to "processed" and the pipeline will continue. This is inherent to
  hooks being able to mutate the context at all, and the spec's position is that
  hooks are hand-written PR-reviewed pack modules — the same trust boundary that
  lets a beforeEmit hook invalidate a record (which validate_record then catches).
  Noted so a future reader does not mistake it for an oversight.
Task A7: complete (commits 3f5bafc..7313570, review clean after 1 fix round)
Task A8: implemented (commit b26f77b) — WALKING SKELETON MILESTONE. 10 stage
  modules + vision port + FakeVision. Suite 137/137.
  Controller verified end to end: (1) stage names exactly match the runner's hook
  contract with zero orphaned hook keys; (2) all 8 stages observably run per the
  event log (s5a absent by design — no persona, so hard-miss routes to 5b, and 5c
  also fires on weak confidence); (3) all 6 runner-owned sockets fire during a real
  corpus run, with classifySignals and onRegenTrigger correctly not firing;
  (4) all 10 real corpus PDFs emit schema-valid records, intaken==emitted==10;
  (5) a .txt file and a missing file are both skipped with clear reasons, never
  dropped. Every document lands processed/low/standard_invoice, which is the
  correct starting state: no extraction layer and no packs exist yet.
Plan erratum (fixed): A8 step 5 said "5 tests"; the brief's test file specifies 6.
Task A8: review 1 (retried after the first reviewer died on an expired OAuth token
  — nothing lost, commit and ledger were already written) — spec COMPLIANT, 2
  IMPORTANT + 1 IMPORTANT-coverage + 1 minor.
  IMPORTANT: s5c set regen_flag on a hard miss. Confirmed against the spec: Part 3
  "First-time" says a hard miss emits "with the one-shot result and a review flag",
  and Stage 7 defines regen_flag as "the rules are wrong". Verified the real
  consequence: all 10 corpus documents emitted regen_flag=True with
  extraction_rule_version="none" — flagging regeneration of rules that do not
  exist. IMPORTANT: s5c and s7_gate were both writing regen_flag with nothing
  clearing a stale True. IMPORTANT: stage 5 — the branch the plan itself calls the
  one the design turns on — had coverage of ONLY the hard-miss path; 3 of 4 routes
  were unverified by anyone.
Task A8: fix round 1/5 (3 important + 1 minor addressed, 0 open; commits
  b26f77b..245942c). s5c now sets review_flag; Stage 7 is the sole regen_flag
  writer (grep-confirmed: s7_gate.py:46 is the only write); _collapsed docstring
  corrected to cover the zero-fields case; 4 routing tests added with _StubStore
  and _StubExecutor standing in for the Persona DB (C7) and grammar executor (C2).
  Controller verified all four paths: (a) hit/good -> 5a_cached with ZERO vision
  calls and rule_version v14 — the architecture's economic claim; (b) hit/collapsed
  -> 5b_vision, 1 call; (c) soft miss -> 5a_cached; (d) hard miss -> 5b_vision,
  review=True, regen=False. regen_flag now 0/10, review_flag 10/10. Suite 141/141.
Task A8: re-review 1 — all 4 findings ADDRESSED, s7_gate.py untouched, no new
  breakage, mypy clean. All 6 original skeleton tests intact with unchanged
  assertions. All 4 new tests confirmed falsifiable (FakeVision genuinely records
  calls, proven by the inverse low-quality test). _StubStore.lookup and
  _StubExecutor.apply confirmed to match the real component shapes, so the routing
  tests will not mask a wiring failure in clusters C2/C7.
  (The 2 doc files appearing in that diff range are the controller's own c0f30d7
  plan-corrections commit, not an implementer scope violation.)
Task A8: complete (commits 7313570..245942c, review clean after 1 fix round)
Task A9: implemented (commit 3fd6ce7) — filesystem intake + CLI. Suite 147/147.
  Controller verified: `docintel process docs` prints 10 lines and exits 0; --json
  emits 10 records, every one passing validate_record, 21 keys each; document IDs
  are identical across two separate FilesystemIntake instances; the CLI invariant
  guard genuinely returns exit code 2 when a document is dropped (proven by
  subclassing Runner to decrement the emitted counter — the guard is not
  decorative); `replay-gold` fails with a clean ModuleNotFoundError, correct until
  Task A10 lands scorecard.py. Console script entry point works.
Task A9: review 1 — spec COMPLIANT, 2 IMPORTANT + 2 minor, all confirmed by the
  reviewer through execution. IMPORTANT: the suffix filter never checked isfile, so
  a DIRECTORY named archive.pdf was yielded and reported "processed" with fabricated
  fields while real PDFs inside it were never seen. IMPORTANT: no recursion — a PDF
  one directory down was invisible: not skipped, not dead-lettered, not counted in
  intaken. Worse than a crash, and a hole UPSTREAM of where the never-drop promise
  is enforced. Minor: exit 0 could mislead an operator scripting on it. Minor:
  _stable_id path+size collision — accepted, it is an acknowledged stand-in for the
  real mail-message-id key.
Task A9: fix round 1/5 (2 important + 1 minor addressed, 1 accepted, 0 open;
  commits 3fd6ce7..05bad8d). os.walk resolves both Important findings at once,
  since it separates dirnames from filenames. CLI now tallies dispositions and
  prints a summary; the subparser description states what exit 0 and exit 2 mean.
  Controller verified against a hostile tree: a directory named archive.pdf is NOT
  yielded as a document, the PDF inside it IS found, a PDF two levels down IS
  found, .txt is excluded, traversal is deterministic, and docs/ still yields
  exactly 10 (no regression). A run where every document dead-letters now prints
  "10 emitted (10 dead_letter)" rather than silently exiting 0. Suite 150/150.
CONTROLLER RULING: exit-code semantics unchanged. Overloading exit 2 to mean "a
  document dead-lettered" would destroy the invariant signal it exists to carry;
  the summary line and help text fix the ambiguity without that cost.
Task A9: re-review 1 — all 3 findings ADDRESSED, both must-not-change items held
  (_stable_id still path+size; exit codes still 0/2), no new breakage, mypy clean.
  All 6 original tests intact with test_directory_expands_to_its_pdfs byte-identical.
  Summary line correctly suppressed in --json mode and when nothing was processed.
  os.walk called WITHOUT followlinks=True, so a symlink loop cannot hang the run.
Task A9: complete (commits 245942c..05bad8d, review clean after 1 fix round)
Task A10: implemented (commit 92ae4a9) — gold scorecard. Baseline 0/10 documents
  green, 27/137 assertions. Gold untouched (byte-compare test + git status clean).
Task A10: CONTROLLER FINDING (found by asking what the instrument FAILS to measure,
  not whether it measures correctly — the 0/10 baseline looked perfectly healthy).
  The scorecard asserted only 12 scalar fields plus 4 flags, and therefore measured
  NONE of ten documented findings and ZERO of fifteen tags. reference_list and
  bill_to_name appear in all 10 gold files and were asserted in neither. The
  convergence loop could have reached "10/10 green" with an empty reference_list,
  no tags and no carried-balance basis — then STOPPED, because its exit condition
  was met. An objective function that cannot see the target is worse than none,
  because it terminates the work.
Task A10: fix round 1/5 (1 controller finding addressed, 0 open; commits
  92ae4a9..f88bf36). matches() gained `superset` and `set` kinds; CHECKED_FIELDS
  grew 12 -> 32, each entry tied to a named finding; tags asserted as superset (a
  pack may add more than the label enumerates); reference_list asserted as exact
  set where reference_list_complete is true and superset where false, because 6 of
  10 golds transcribe page 1 only. Controller verified: 213 assertions (was 137),
  27 passed, 0/10 green — instrument widened, behaviour untouched; all ten findings
  now measured; Federal Recycling gets kind=set, so an annotation-sourced
  reference leaking into the record WOULD now fail (the F3 guard is live).
DEFERRED WITH A HOME: `line_items`, `charges`, `scanline`, `sub_account` cannot be
  asserted — no Stage 8 key exists. Four contract additions scheduled into cluster
  C2's brief with the explicit warning that 10/10 green before they land does NOT
  mean the corpus is satisfied.
Task A10: minor (deferred): a gold `reference_list: []` with complete=true (EDCO)
  generates no assertion, so a record that spuriously invents references there
  would not fail. Low harm relative to missing references; noted for final review.
Task A10: re-review 1 — finding ADDRESSED, out-of-scope assertions correctly
  omitted, no new breakage, mypy clean. Confirmed the F3 guard is live: Federal
  Recycling has complete=true -> kind=set, so an annotation-sourced reference
  leaking in WOULD fail; had that flag been false it would silently pass.
Task A10: minor (deferred): tags use `superset`, which cannot reject a SPURIOUS
  tag. Partly mitigated — a spurious tag that changes routing is caught by the
  exact review_flag/regen_flag assertions (verified); an inert spurious tag is
  unmeasured. Switching to exact-set was rejected for now because a later cluster
  legitimately adding a tag would then fail all 10 documents as noise.
Task A10: minor (deferred): a gold `reference_list: []` (EDCO) generates no
  assertion at all, so invented references there go undetected. EDCO's `teaches`
  list does not include F11, so no targeted finding is blinded.
Task A10: controller erratum — the fix dispatch said CHECKED_FIELDS "grew from 12
  to 32"; the real count is 30 (plus 4 CHECKED_DERIVED). The plan text itself never
  claimed 32, so nothing in the repo was wrong.
Task A10: complete (commits 05bad8d..f88bf36, review clean after 1 fix round)
PLAN FIX before A11 dispatch: A11's brief still carried a placeholder hook test
  whose docstring said "stages do not dispatch hooks until cluster C5". A7's fix
  made that stale — the runner now dispatches all 6 boundary sockets. Replaced with
  a parametrized end-to-end test asserting the invariant holds when a pack hook
  throws at EACH of the six sockets.
Task A11: implemented (commit fb1ffa0) — invariant suite, 48 tests, no production
  code touched (git status --short src/ empty). 40 stage-failure-injection cases
  (4 exception types x 10 stage positions) + 6 pack-hook sockets end-to-end + 1
  BaseException boundary + 1 whole-corpus pass. Suite 205/205.
Plan erratum (fixed): A11 step 2 said "42 tests"; parametrizing the hook test over
  6 sockets makes it 48.

########## PART A EXIT CHECK — PASSED ##########
1. `docintel process docs` -> 10 records, "10 emitted (10 processed)", exit 0
2. `replay-gold --json` -> scorecard: 0/10 documents green, 27/213 assertions
3. `pytest tests/test_invariant.py` -> 48 passed
All gates: 205 tests, mypy strict 0 errors, gold validator 95 green, ruff clean.
Gold files byte-identical to baseline c82eb76 across the whole of Part A.
20 commits on feat/pipeline. Baseline for the Part B convergence loop is
0/10 documents green, 27/213 assertions.
Task A11: review clean — spec COMPLIANT, quality APPROVED, no finding above Minor.
  The reviewer MUTATION-TESTED the suite: narrowing runner.py's `except Exception`
  to `except (PermanentError, TransientError)` broke 25 of 48 tests, empirically
  proving the matrix exercises process()'s catch-all rather than asserting
  something trivially true. Controller confirmed the mutation was reverted
  (git diff --stat HEAD -- src/ empty, both `except Exception` lines intact,
  205 tests still green).
Task A11: minor (deferred): 30 of the 40 matrix cases are pairwise-redundant —
  PermanentError, RuntimeError and MemoryError all take the identical path out of
  _run_one. Only TransientError differs (retry loop). Redundancy is harmless, not
  gap-hiding.
Task A11: minor (deferred): _emit()'s own degradation path is covered in
  test_runner.py, not test_invariant.py — coverage of one guarantee lives in two
  files. By design, but worth noting.
Task A11: complete (commits f88bf36..fb1ffa0, review clean, 0 fix rounds)

########## PART B — CONVERGENCE LOOP, ITERATION 1 ##########
Scorecard read: 0/10 documents green, 27/213 assertions, 39 failing assertion
types over 186 failing assertions. Ranked by ROOT CAUSE, not by document:
    136 failing  <- needs selectors that can read a field (C2 + C5)
     26 failing  <- needs adjust ops (C3)
     15 failing  <- needs pack ladders: doc_type, tags (C5)
      7 failing  <- routing (review_flag)
      2 failing  <- text_source on the 2 image-only PDFs (C1)
CLUSTER CHOSEN: C1, the extract layer. Tier 1 — a whole layer is missing, and all
136 top-group assertions are unreachable while ctx.pages is empty. This confirms
by measurement what the plan predicted by reasoning.
DE-RISKED FIRST: verified in this environment that pdfplumber.to_image works (via
pypdfium2) and tesseract reads the image-only Federal Recycling PDF — finding
1330123, 481.20 and HAUL, with 261 word rows carrying bboxes. The OCR path is
viable, so C1 is not a research task.
C1 SPLIT into C1a (pdf + ocr + normalize, the seam that makes ctx.pages real) and
C1b (pageroles + annotations + scanline, the detectors), because six modules in one
dispatch is too large to review as a unit.
Cluster C1a: implemented (commit c9194d3) — extract seam: pdf.py, ocr.py,
  normalize.py, wired into s2_filter. 13 new tests, suite 218/218.
  Controller verified the seam is correct: OCR reports 609x791 POINTS (not
  1692x2199 pixels), so the pixel->point scaling that would have silently broken
  PageText.lines() grouping is right; EDCO's CURRENT CHARGES / 69.62 / 298.34 /
  367.96 and Centracom's 13,752.60 / 20,123.80 / 33,876.40 are all reachable in
  extracted text; OCR recovered 1330123, 481.20, HAUL, OCC from the image-only
  contra invoice; U-Pak's 14740.85 is on the LAST page and absent from page 1 (F9).
  Scorecard 27/213 -> 29/213 assertions, still 0/10 documents — correct, since no
  selector exists yet to consume ctx.pages.
Cluster C1a: PERFORMANCE DEFECT found by controller. Suite went 0.16s -> 210.49s.
  CONTROLLER MISDIAGNOSIS, corrected: the first measurement claimed a single OCR
  page took >110s. That was invalid — it was taken while a 210s pytest run was
  executing in the background, so the two competed for CPU. The agent was told the
  wrong hotspot and then promptly corrected.
  TRUE UNCONTENDED FIGURES: load_document on the 1-page OCR doc 0.89s; replay-gold
  over all 10 docs including 5 OCR pages 7.68s (acceptable); full suite 210.49s;
  tests/test_invariant.py alone 156.62s of that, with the slowest matrix cases at
  ~4.6s each.
  ROOT CAUSE: repeated NATIVE parsing, not OCR. The 40-case invariant matrix
  processes 10 documents per case, so the same 6-page PDF is parsed ~400 times at
  ~0.46s each. Primary fix redirected to in-process memoization of load_document
  keyed on (abspath, st_size, st_mtime_ns); the disk OCR cache is retained as a
  secondary win for cold cross-process runs. Target: full suite under 30s, with an
  explicit instruction NOT to lower RESOLUTION or thin the invariant matrix (a
  reviewer mutation-tested those 40 cases to prove they are load-bearing).
Cluster C1a: fix round 1 (performance defect addressed; commits c9194d3..68b763f).
  In-process lru_cache memo on load_document + disk-backed OCR cache under var/.
  MEASURED, idle machine: full suite 210.49s -> 4.28s (223 tests, 5 new);
  test_invariant.py >120s -> 3.70s; replay-gold cold 7.54s / warm 3.8s;
  load_document on the 4-page OCR doc cold 3.35s / warm 0.37s. A cold clone pays
  only a few seconds of OCR total, so committed OCR fixtures are NOT needed.
  Controller confirmed caching changed no behaviour: EDCO trap values, Federal
  OCR values (1330123/481.20/HAUL), U-Pak's page-5 total, and the 609x791-point
  box are all unchanged; var/ has 0 tracked files and is gitignored; scorecard
  still 0/10. RESOLUTION was not lowered and the invariant matrix was not thinned.
  NOTE for cluster C1b: the memo returns the SAME tuple object on repeat calls.
  That is safe only because PageText, Word and PageMeta are frozen dataclasses and
  pages/meta are tuples. C1b's pageroles.assign() must RETURN A NEW TUPLE rather
  than mutate, or cached page metadata will leak between documents and tests.
  ACCEPTED: native parsing is still re-done per process (the memo is
  process-lifetime; only OCR is cached across processes). replay-gold cold 7.5s is
  acceptable, so a disk cache for native parsing is not worth the complexity.
Cluster C1a: review 1 — spec COMPLIANT. 1 CRITICAL + 2 IMPORTANT + 2 minor, all
  found in the caching layer added by fix round 1.
  CRITICAL (reproduced by the reviewer): the memo key (abspath, size, mtime_ns)
  served a stale WRONG-DOCUMENT result when a file is overwritten in place at
  identical byte size with mtime restored — real triggers being rsync -t, cp
  --preserve=timestamps and timestamp-preserving archive extraction.
  IMPORTANT: DOCINTEL_OCR_CACHE=0 bypassed the disk cache but NOT the memo, so via
  the real production path a repeat call never re-ran OCR — a debugging escape
  hatch that silently did nothing, which is worse than none since someone trusts
  it. IMPORTANT: var/ocr-cache/ had no eviction, TTL or cap.
  Minors: one cache test could not distinguish a hit from a recompute; one memo
  test was structurally unable to fail (different abspaths guarantee different
  keys, so it never probed the same-path hazard).
CONTROLLER NOTE ON PROCESS: the instinct was to argue the Critical's trigger was too
  unlikely to be worth the hashing cost. Measured instead: hashing the entire
  6.98MB corpus takes 9ms, and the 400 hashes the invariant matrix performs cost
  0.16s. A 4% suite cost to remove a class of silently-wrong results is not a
  trade-off. Reasoning about probability is how correctness holes survive; the
  measurement took seconds and made the argument unnecessary.
Cluster C1a: fix round 2 (1 critical + 2 important + 2 minor addressed, 0 open;
  commits 68b763f..04d0adf). blake2b content hash added to BOTH cache keys;
  DOCINTEL_OCR_CACHE=0 now bypasses memo and disk; disk cache capped at 512 entries
  with oldest-first eviction; both weak tests replaced, and the new same-path
  collision test was proven to FAIL pre-fix before passing post-fix.
  Controller independently reproduced the exact attack: same path, identical byte
  size, mtime restored via os.utime — the second load now correctly returns Veritiv
  content rather than stale D.T.S.S. content. Suite 223/223 in 5.29s (was 210.49s
  pre-cache, 4.15s pre-hash); trap values and the 609x791-point box unchanged;
  var/ still untracked; scorecard still 0/10, 29/213.
  ACCEPTED residual: every cache lookup re-hashes full file content. Fine at
  single-digit ms for this corpus; would need revisiting at orders-of-magnitude
  scale.
Cluster C1a: re-review 2 — all 5 findings ADDRESSED, no new breakage, mypy clean.
  Content hash confirmed present in BOTH the memo key and the disk-cache key (a
  hash on only one would have left the other exploitable). Eviction wrapped at two
  levels and provably cannot delete the entry it just wrote. RESOLUTION still 200,
  invariant matrix still 40 cases. Both test replacements were the intended ones;
  the original 13 tests are untouched.
Cluster C1a: COMPLETE (commits 40be4e2..04d0adf, review clean after 2 fix rounds).
  Three rounds total, and each earned its place: round 1 was a 50x speedup that
  made the convergence loop viable at all; round 2 closed a wrong-document cache
  hit. Neither was cosmetic.
CONTROLLER FINDING carried into C1b: `page_roles` is on the emitted record and in
  every gold file's classification block, but the scorecard does NOT assert it —
  the same blind-spot class as the A10 defect. C1b produces page roles, so C1b will
  add the assertion. Adding it will raise the assertion denominator; that is an
  instrument change, not a behaviour change, and must be reported as such.
Cluster C1b: implemented (commit ac02966) — pageroles, annotations, scanline +
  s2_filter wiring + the page_roles scorecard assertion. Suite 255/255 in 6.22s
  (+32 tests). Scorecard 29/213 -> 39/223: the +10/+10 delta is exactly the new
  page_roles assertion, all 10 passing. Documents-green still 0/10 (correct — no
  selectors exist). Controller verified independently: page_roles match gold on
  10/10 documents; F3 flags ONLY Federal Recycling; F7 returns a scanline on
  exactly the 5 expected documents and None on the other 5; the scanline module
  documents the 4-field-only constraint; pageroles.assign does NOT corrupt the
  memoized PageMeta.
Cluster C1b: NOTABLE BUG the agent found and fixed unprompted — `from __future__
  import annotations` in extract/__init__.py bound the package attribute
  `annotations` to a __future__._Feature object, so `from docintel.extract import
  annotations` silently resolved to the feature flag rather than the new
  annotations.py submodule. An explicit dotted import fixes it, and the hazard is
  documented at length in both files so it is not "tidied" back.
Cluster C1b: minor (known, one-line): Pillow DeprecationWarning at
  annotations.py:167 — Image.getdata() is removed in Pillow 14 (2027-10). Verified
  get_flattened_data() exists in the installed Pillow 12.1.1, so the swap is cheap.
CARRIED FORWARD to cluster C4 (the gate): s7_gate does not consume ctx.tags, so
  `has_flattened_annotations` is set but not yet wired to forced review. Finding F3
  requires that tag to force review regardless of confidence. Not a C1b defect —
  C1b's scope ends at setting the tag — but it must land in C4 or Federal Recycling
  can never reach its gold routing.
Cluster C1b: review 1 — spec COMPLIANT. 1 CRITICAL + 3 IMPORTANT + 1 minor.
  CRITICAL: pageroles.assign hardcoded `role = primary if (i == 0 or
  every_page_primary)`, so a page's own signals never decided its role. A 3-page
  invoice with a cover page and totals on page 2 would mark page 1 primary and
  page 2 supporting — and since field capture reads only primary pages, the total
  would be MISSED ENTIRELY. every_page_primary existed solely to fit U-PAK.
  The reviewer's diagnosis of WHY nothing caught it is the more valuable half: all
  32 tests ran against the 10 real corpus documents with zero synthetic fixtures,
  so the suite could confirm corpus-FIT but was structurally unable to detect
  corpus-OVERFIT. That is a methodological gap affecting every remaining cluster,
  not a one-off bug. Synthetic generalization tests are now a standing expectation.
  IMPORTANT: scanline.corroborates had no field parameter, so the grammar's
  four-field restriction was docstring-only and unenforceable — and Centracom's
  scanline encodes the trap value. IMPORTANT: annotation detection is entirely
  saturation-based, so greyscale or black-pen annotations are silently undetected.
  IMPORTANT: zero synthetic tests (per above).
Cluster C1b: fix round 1 (1 critical + 3 important + 1 minor addressed, 0 open;
  commits ac02966..0adba24). Role rule is now per-page: primary = has_anchor AND
  has_totals, no index logic, with a two-tier LOGGED fallback (totals-only page,
  then page 1 as last resort) so every document still has a primary page, and
  "unknown" is now reachable. The agent verified rather than trusted the
  controller's hypothesis and found it directionally right but incomplete — bare
  `AMOUNT DUE` / `CURRENT CHARGES` would have false-positived Lumen and Windstream
  page 3 once the page-1 collapse was dropped, so _TOTALS_RE was tightened to 6
  precise phrases with an 8-word line cap on the anchor. corroborates() now takes a
  required field and enforces CORROBORATABLE_FIELDS. Greyscale blind spot is
  documented AND pinned by a synthetic desaturated test. Pillow deprecation fixed.
  Controller verified: gold page_roles still 10/10; the generalization case (cover
  page 1, totals page 2) now yields ['supporting','primary','supporting'];
  corroborates allows exactly the 4 permitted fields and rejects amount_payable,
  current_charges and balance_due with clear messages. Suite 267/267 in 6.21s.
  Scorecard unchanged: 0/10 documents, 39/223 assertions.
CONTROLLER ERRATUM: initially claimed the new fallback log lines pollute stdout and
  would corrupt `replay-gold --json`. Wrong — they go to stderr; the JSON parses
  cleanly from byte 0. They merely interleave in a terminal, which renders both
  streams. No defect, no action.
Cluster C1b: re-review 1 — all 5 findings ADDRESSED. Synthetic tests confirmed to
  genuinely probe generalization (the page-2-primary test would have FAILED against
  the pre-fix code, verified by reading it). RESIDUAL flagged honestly by the
  reviewer: _TOTALS_RE is a 6-phrase enumeration, so novel wording like "Balance
  Payable" cascades to the tier-2 page-1 last resort — the overfitting moved out of
  the index logic and into the regex rather than disappearing.
CONTROLLER RULING on that residual: do NOT chase a general totals regex. That trades
  a KNOWN gap for UNKNOWN false positives on documents this corpus cannot show us,
  and the next unusual invoice defeats any enumeration anyway. Structural fix
  instead — make the tier-2 guess VISIBLE IN THE DATA as a page_role_fallback tag,
  because field capture reads only primary pages, so a wrong primary silently loses
  the total, and this design refuses silent failure. Plus the two obvious phrase
  additions (BALANCE PAYABLE, NOW DUE) and nothing more.
Cluster C1b: fix round 2 (commits 0adba24..0a736b2). assign() now returns
  (meta, used_last_resort: bool) — a plain 2-tuple matching load_document's existing
  convention rather than a new dataclass; s2_filter turns True into the tag, tier 1
  stays untagged. PageMeta's shape untouched. Suite 275/275 in 6.31s.
  Controller verified: the tag fires for EDCO (the only tier-2 corpus document) and
  not for Lumen; gold page_roles still 10/10; the two new phrases appear nowhere in
  the real corpus so they changed nothing; scorecard unchanged at 0/10 and 39/223.
  EDCO's `tags` assertion still fails, and was verified NOT newly broken — its gold
  expects `past_due`, which no pack signal ladder exists to emit yet (cluster C5).
Cluster C1b: COMPLETE (commits 04d0adf..0a736b2, 2 fix rounds).
PROCESS CORRECTION (user): the C1b implementer reached ~390k tokens over three
  rounds; the user directed swapping to a fresh subagent rather than resuming a
  bloated one. Correct, and the skill's own guidance says escalate to a fresh
  implementer at round 4. The handoff was cheap ONLY because each implementer writes
  its full reasoning to task-*-report.md, which is the persistent memory a fresh
  agent reads. NEW STANDING RULE: fresh implementer per cluster, and swap on the
  SECOND fix round rather than the third. A redundant handoff agent was dispatched
  and stood down cleanly when the original committed first.
Cluster C2a: EXECUTED INLINE (no dispatched implementer — the resumed session
  forbade subagent use). Delivers schema.py, patterns.py, regions.py, validator.py;
  executor.py and the four contract keys remain C2b. 228 new tests, suite 503/503
  in 7.6s, mypy strict clean over 12 files, ruff clean, gold 95 green. Scorecard
  UNCHANGED at 0/10 and 39/223 — verified, not assumed (standing rule 3): C2a adds
  a validator, not an extraction capability, so nothing it produces is observable
  in a Stage 8 record and there is no new assertion for the scorecard to carry.
  First real movement is still C3.
CONTROLLER DECISION (user-approved, two options presented): region resolvers return
  a new frozen `Span` type (page_number, source, words, bbox + lines()/text) rather
  than trimmed PageText objects, because a PageText whose word set is not the page's
  while its width/height still describe the page is a lie, and the region bbox is
  wanted for field provenance. Uniform 3-arg signature with an optional anchor, one
  RESOLVERS dict, one executor call site.
FINDING (mid-test, unplanned): a bare `Word` cannot say which page it came from, and
  `Word` is a frozen core.models contract. Added `Anchor(word, page_number)` — the
  page is part of the LOCATION, not context the caller supplies separately. Also
  found ANCHOR_REQUIRED is FIVE regions, not the three the spec's prose implies:
  line_items and last-table-row are equally anchor-relative.
RULING: regions.py stays pure geometry and does NOT filter `supporting` pages, even
  though §7 forbids field values from them. Reference-pattern matching must run
  across every page and uses these same resolvers, so `any-page` must mean every
  page; role filtering belongs to the executor, the only layer that knows whether
  it is capturing a field or a reference. Pinned by a test asserting any-page does
  NOT filter, so a later "fix" cannot quietly break reference matching.
RULING on V5: §1.1 waives `region` for a "provably unique" anchor. Uniqueness is a
  property of a DOCUMENT, not a persona, so it cannot be established at write time
  — `region` is therefore always required. A persona with a unique anchor loses
  nothing by naming `any-page` explicitly and gains a reviewable statement of intent.
SPEC ERRATUM 1: §3.2 specifies a linear-time engine ("RE2 / `regex` with
  backtracking disabled"). Not implementable as written — the `regex` module has no
  backtracking-disabled mode, and true RE2 is a new binary dependency. Built on
  stdlib `re` + the static restrictions, with the 50ms runtime budget (C2b) as the
  second half. Surfaced to the user, left as-is. If a real linear-time guarantee is
  later required, google-re2 is the change and it is NOT a drop-in: RE2 rejects
  lookahead, which §3.2 permits.
SPEC ERRATUM 2: §9's worked EDCO example asserts `invoice_account` in its scanline,
  which §1.3 forbids (permitted set: total_printed, account_number, invoice_number,
  due_date). §1.3 is normative and load-bearing — it is what stops the F1 bug being
  cemented via F7 — while §9's field naming is illustrative and already diverges
  from the Northstar pack elsewhere (invoice_account vs vendor_account_number,
  bill_date vs invoice_date). Read as a typo for account_number. §9's persona is
  reproduced as a validator test with that one correction, so the grammar is pinned
  against the spec's own worked example.
TIGHTENING beyond the plan: §1.3 writes the scanline's region as its own narrower
  enum than §2's. First draft accepted any known region there; now restricted to
  {last-page, remittance-block} plus any page:N. An OCR-A remittance line is a
  physical feature of the payment stub, so a persona claiming one in a header-block
  describes something that cannot exist, and the spec's position is that closed
  vocabularies are rejected at WRITE time. page:N generalizes §1.3's literal
  page:1 — a five-page bill's stub is on page five.
ADDED beyond §3.2: compile_restricted also rejects a quantifier nested inside a
  quantified group. Bounded-ness is NOT sufficient for linear time —
  `(?:a{0,20}){0,20}` is bounded at every level and still exponential. Check order
  inside compile_restricted is load-bearing: length before structure, and
  backreferences independently of the capture count, because `(a)\1` is WITHIN the
  1-capture budget and still forbidden.
SELF-REVIEW found 3 defects before the commit, all in the new tests rather than the
  implementation: (1) the same-cell test passed for the wrong reason — the fixture
  helper's 6pt-per-char width made a claimed "5pt gap" an actual 23pt column gap,
  so the test was asserting that a two-word cell SPLITS; (2) a V6 test used the
  anchor-relative `same-row` with no anchor and was correctly rejected by the new
  anchor-presence check; (3) test_V4_rejects_an_unknown_pattern_name_as_a_regex
  asserted the OPPOSITE of its name — `currancy` is accepted as a literal regex.
  Renamed, and its docstring now states the real limitation: the grammar cannot
  distinguish a typo'd pattern name from a deliberate literal matcher (`BALANCE
  FORWARD` is exactly that shape and legitimate), so the eval attached to a persona
  write catches this, not V4. Also fixed a TypeError leak in V12 when `source_tags`
  was neither a string nor a sequence — the boundary must raise ValidationError or
  nothing.
Cluster C2a: COMPLETE (0 fix rounds). Full detail in task-c2a-report.md.
Cluster C2b: EXECUTED INLINE (subagents still disallowed). Delivers
  grammar/executor.py, a persona-bound Stage 5a, the four missing Stage 8 keys,
  and the scorecard assertions that measure them. 55 new tests, suite 558/558 in
  7.8s, mypy strict clean over 13 files, ruff clean, gold 95 green.
  SCORECARD DENOMINATOR MOVED: 39/223 -> 39/242. The +19 is line_items.count (5),
  line_items.amounts (5), scanline.raw (5), charges (3), sub_account (1). All 19
  currently FAIL because no personas exist (that is C5) — the numerator is
  unchanged at 39 by design. THE STANDING CAVEAT IS DISCHARGED: "10/10 green" now
  means the corpus is satisfied. Before this cluster the loop could have reached
  10/10 while extracting no line items, no surcharges and no scan line at all.
CONTROLLER DECISION: Stage 5a holds an executor FACTORY, not an executor. An
  Executor is bound to one persona and the persona is looked up per document at
  s4, so a single injected instance would either be stale or belong to whichever
  document arrived first. This moved the injection seam in two Part A routing
  tests from `executor=stub` to `executor_factory=lambda persona: stub`; the
  invariants those tests assert (persona hit costs zero vision calls; collapsed
  persona falls back to vision) are untouched.
CONTROLLER DECISION: row groups live in ctx.row_groups keyed by the persona's
  row_group name, and build_record promotes ONLY line_items, charges and
  sub_account. A new top-level contract key is a contract change and must need an
  edit to _PROMOTED_ROW_GROUPS, not appear because a persona author picked a name.
  Tested. Kept out of ExtractedFields because a repeating table is not a
  name->value pair and flattening it would make fields.line_items a list inside a
  mapping every other consumer reads as scalars.
CONTROLLER DECISION: record `scanline` is a bare string, matching what
  extract.scanline.find returns. The gold label's scanline is a rich object, but
  its encodes_* keys are ANALYSIS of what the digits mean, not something the
  pipeline transcribes — asserting them would score the label rather than the
  extraction. validate_record rejects a non-string scanline: leading zeros carry
  meaning to a lockbox scanner.
PLAN DEVIATION (measured, deliberate): the plan asked for line_items "count and
  signed sum". Shipped count + a sorted MULTISET of amounts instead, for two
  reasons. (1) A sum cancels what a multiset catches — two rows with swapped
  amounts, or compensating errors, net to the same total and pass silently.
  (2) A sum would imply an arithmetic claim the corpus does not support. Measured
  across the 5 golds carrying line_items: four close exactly against a printed
  total (Complete Beverage 1177.70, DTSS 699.00, Federal Recycling 481.20,
  Veritiv 4608.45 = subtotal), but EDCO does NOT — its statement table prints a
  `CURRENT CHARGES:` summary row INSIDE the table body, so its amounts total
  437.58 against a printed 367.96. That is the table faithfully transcribed, not
  an error. Proving closure is crosscheck_line_sum's job at Stage 6, where it
  reports a modifier rather than a scorecard failure. NOTE FOR C3: do not treat
  EDCO's Σ line_items != subtotal as a mismatch to flag.
RULING: the executor's page-role lookup is FAIL-CLOSED — a page with no PageMeta
  entry counts as supporting. A pipeline that skipped role assignment therefore
  extracts nothing visible rather than silently reading totals off a handwritten
  Bill of Lading (F10). A loud empty result is recoverable; a confident wrong one
  is not. The scan line is the documented exception (scoring-only, so §7 does not
  apply, and must not: a multi-page bill's stub routinely lands on a legitimately
  supporting continuation page). Both directions tested.
RULING: row_count is a stated expectation, not a filter. Truncating to `max` would
  silently discard real rows; raising would turn a layout change into a pipeline
  error. A violation is LOGGED and left visible. There is no modifier for it in
  the closed §5 enum and inventing one here is the quiet vocabulary growth the
  grammar forbids — wiring it to review is C4's call, with a modifier added
  deliberately if it needs one.
50ms BUDGET, honest residual: a preemptive timeout is not available in pure Python
  without threads or signals, so the budget is checked BETWEEN candidate strings
  (each a cell, word or line — short), bounding time per field to the budget plus
  one candidate's runtime. A single pathological match on one candidate can still
  overrun. What makes that acceptable is C2a's static restrictions, which is why
  the two halves were always meant to ship together. On a blown budget whatever
  was found so far is DISCARDED, not kept: a partial all_matches list is worse
  than a visible miss because it looks complete.
THREE DEFECTS found during the run, all in the implementation this time (C2a's
  were all in tests): (1) _column_bounds abandoned its search after the first
  header — a for/else/break treated "ran past the needle length" identically to
  "matched", so every cell of every row landed in the leftmost column. Fixed by
  extracting a shared _runs helper (anchor lookup and column-header location are
  the same operation asked twice), which also removed a block of duplication.
  (2) A persona declaring only SOME columns got one column spanning the full page
  width, because the grid was derived from the declared columns rather than from
  the header row. Grid now built from every header cell with declared columns
  mapped onto it. (3) THE IMPORTANT ONE, caught by the end-to-end test:
  `line_items` ran to the foot of the page, so the row group swallowed the totals
  block and the remittance stub. This is the COMMON case, not a corner case —
  every corpus invoice prints a totals block below its table and five also print
  a stub — so row groups would have been unusable in C5 and the F8 closure check
  meaningless. Fixed with a vertical-rhythm break: a gap larger than
  max(24pt, 2.5x the established row pitch) ends the table, pitch seeded from the
  header-to-first-row gap. Three tests pin it, including a uniformly spaced
  20-row table that must NOT break and a 6pt-pitch table that must survive a
  15pt gap.
PROCESS NOTE: defect (3) was found only because the cluster ended with an
  end-to-end test that ran a real validated persona through Stage 5a into a
  validated Stage 8 record. Every unit test passed with the bug present. NEW
  STANDING RULE candidate: a cluster that adds a pipeline capability must finish
  with one test that exercises the whole path, not only its units.
Cluster C2b: COMPLETE (0 fix rounds). Full detail in task-c2b-report.md.
Cluster C3: EXECUTED INLINE. Delivers the 23 adjust ops (base/derive/crosscheck/
  infer), an unconditional derive_document_identity, a real s6_capture, the
  carried-over validate_record identity requirement, and tests/test_f1_
  antiregression.py. 436 new tests, suite 994/994 in 7.9s, mypy strict clean over
  18 files, ruff clean, gold 95 green. Scorecard 39/242 -> 39/252 (the +10 is the
  lane assertion, finding 1).
SCORE DID NOT MOVE and the plan predicted it would. "Score after: some derived.*"
  was optimistic: every op only runs when a persona declares it in `adjust`, and
  no personas exist until C5. U-PAK's two derived assertions ALREADY passed before
  C3 (its gold expects null and a .get on an absent key also returns None), so
  there was nothing for C3 to win. Verified per-document, not assumed.
SPEC CORRECTION: §4.2 words the closure check as prior_balance + current_charges
  != total_printed. That predates F1b and is only correct for net_of_payments.
  Measured on all 5 corpus documents with a prior balance, the closure holds
  against the CARRIED balance: Centracom 20123.80+13752.60, EDCO 298.34+69.62,
  Comcast/Lumen/Windstream 0.00+printed. Against the RAW prior, Comcast reads
  212.87+221.11=433.98 vs a printed 221.11 — a false mismatch on a completely
  correct extraction. Written against carried, which reduces to the spec's wording
  in the net_of_payments case. Pinned by a named test.
CONTROLLER DECISION: two op shapes, one closed enum. base.VALUE_OPS is
  Callable[[Any],Any] (§4.1, one field's value); OPS is Callable[[JobContext],
  JobContext] (§4.2-4.4, reasons across fields). test_registry asserts
  ALL_OP_NAMES == schema.BASE_ADJUST_OPS in BOTH directions, because either drift
  is silent: declared-but-unimplemented means the validator accepts a persona and
  s6 skips the op, so a document is scored as if a cross-check passed when nothing
  ran; implemented-but-undeclared means the op is unreachable.
RULING: op order is pinned by ops.ORDER, NOT the persona's declaration order. A
  persona listing derive_amount_payable before resolve_carried_balance would read
  a carried_balance that does not exist yet and fall back to the printed total —
  THE F1 BUG, REACHABLE PURELY BY HOW A PERSONA WAS WRITTEN. Test lists the three
  ops backwards and asserts Centracom still comes out at 13752.60. Value ops DO
  run in declaration order, because there the composition is the author's intent.
CONTROLLER DECISION: derive_document_identity is NOT an adjust op. The plan's
  carried-over requirement demands validate_record require document_identity/
  identity_basis, but the plan lists no op producing them. Rather than adding a
  24th name to a closed enum §4 does not contain, it is an unconditional Stage 6
  step — a persona must not be able to opt out of something the contract requires
  by omitting a name. Ladder measured against gold: invoice_number, else
  NORMALIZED account + '|' + period, else both keys None. The normalization is the
  point of F6: Comcast prints '8495 44 462 0365242', gold identity is
  '8495444620365242'; a key from the printed form would not join.
RESOLVED (looked like a sequencing problem, was not): the identity requirement
  demands PRESENCE, not a non-null value. A non-null requirement would dead-letter
  all ten documents until C5 and destroy the loop's signal for two clusters.
  derive_document_identity always sets both keys, using None for "looked and could
  not build one" — materially different from "never tried", and the only one of the
  two a reviewer can act on. Non-null would also break count(intaken) ==
  count(emitted), since a document whose identity cannot be built still has to be
  emitted and routed. Fixing the 3 tests this broke followed the precedent already
  documented in tests/pipeline/test_runner.py's `_classified` helper, which stands
  in for stages a double skips.
MEASURED: two vendors compose their totals differently and no single formula
  covers both. U-PAK subtotal 8119.44 + charges 6670.33 == 14789.77 (its 2325.69
  H.S.T. already inside those parts); Veritiv subtotal 4608.45 + tax 299.55 ==
  4908.00 with no surcharges. crosscheck_total_composition therefore tries every
  plausible decomposition and boosts if ANY closes, flagging only when none does.
  Picking one formula would false-flag whichever vendor did not use it, and a false
  mismatch on a correct extraction is worse than a missed corroboration — it trains
  reviewers to ignore the flag.
EDCO TRAP (flagged by C2b) turned out safe by construction: crosscheck_line_sum
  requires a printed `subtotal` and EDCO prints none, so its self-summing table
  (805.54 of amount columns vs a printed 367.96) is SKIPPED rather than flagged.
  Only Veritiv exercises the op in the corpus. A test asserts EDCO is skipped, so a
  future change that loosens the subtotal requirement fails loudly.
RULING: infer_currency leaves 9 of 10 documents with NO currency, and that is
  correct rather than a gap. "Most invoices are USD" is a PACK POLICY, not
  something the document says, so the rung supplying it is pack_default and packs
  arrive in C5. Only U-PAK is CAD and says so via its H.S.T. line (rung 2). VAT is
  deliberately not a currency signal — it spans the UK and the whole euro area, so
  inferring either would be a guess wearing a basis.
DEFECT (1, mine, in a test): a synthetic partially-paid fixture was arithmetically
  impossible — prior 500 gross, payments -400, current 100, printed 600. Carried is
  100, so 100+100 != 600 and derive_amount_payable correctly refused; the test was
  asserting a payable the arithmetic forbids. Printed corrected to 200 with the
  arithmetic spelled out. STANDING RULE 7 LANDING FROM THE OTHER DIRECTION: in C2a
  bad fixtures made tests PASS for the wrong reason; here one made a correct
  implementation look broken.
FINDING 1 (FIXED): `lane` was never asserted. All ten gold files specify
  expected_routing.lane; the scorecard asserted only review_flag and regen_flag.
  The lane IS the routing decision, so a scorecard checking the two booleans but
  not the lane cannot tell a correctly-routed document from a wrongly-routed one —
  same blind-spot class as the tags/reference_list/page_roles gaps. Now asserted
  (+10, all failing since s7_gate is a stub). Implementing it is C4's; MEASURING it
  starts now so C4 has a visible target rather than an unstated one.
FINDING 2 (NOT FIXED, NEEDS A DECISION): every gold file carries an `assertions`
  array the scorecard NEVER READS — 68 entries across 55 distinct `check` names, of
  which 37 carry a machine-checkable `equals`. Some duplicate existing coverage
  (amount_payable, payable_basis, line_sum) but several are exactly C3's output and
  are uncovered: balance_composition (5 docs), total_composition (2),
  current_charges_composition, duplicate_anchor_agrees (2),
  scanline_agrees_with_printed_total, filename_crosscheck, currency_inferred,
  arith_balance_mismatch_applied. UNDERNEATH IT IS A BIGGER GAP:
  `confidence_modifiers` is not asserted AT ALL — the entire §5 mechanism, 16
  modifiers of which C3 emits 8, is unmeasured, and nothing would notice if
  arith_balance_mismatch stopped being applied. Same class as standing rule 3, so
  10/10 GREEN STILL DOES NOT FULLY MEAN THE CORPUS IS SATISFIED: the caveat C2b
  discharged for the four contract keys reappears here for modifiers and routing.
  Not fixed in C3 because it is real work with its own design (expr strings need
  evaluating or ignoring; 55 check names map to record locations non-uniformly;
  ~18 prose-only entries are about C4/C5 capabilities) and doing it inside C3 would
  have been an unreviewed scope expansion. RECOMMENDATION: a small C3b before C4,
  wiring the 37 `equals` entries plus a confidence_modifiers superset assertion.
  Est. 150-250 src lines, mostly a check-name -> getter table.
Cluster C3: COMPLETE (0 fix rounds). Full detail in task-c3-report.md.
Cluster C3b: EXECUTED INLINE. NOT in the original plan — created from C3's finding
  2 on the user's approval. Delivers the missing scorecard coverage plus
  tests/test_scorecard_coverage.py (GUARDRAIL 3). 67 new tests, suite 1061/1061 in
  8.2s, mypy strict clean over 18 files, ruff clean, gold 95 green.
  Scorecard 39/252 -> 41/339. The +87 denominator is the coverage; the +2 numerator
  is REAL — ocr_source on Complete Beverage and ocr_source+flattened_annotations on
  Federal Recycling, i.e. C1a's and C1b's detection working, turned into modifiers
  by C3's Stage 6. Capability that had been correct for three clusters and was
  measured by nothing.
CONTROLLER ERRATUM on my own C3 finding 2: the estimate was wrong in BOTH
  directions. (a) FEWER of the 68 gold assertions were genuinely new than claimed —
  of the 25 distinct check names carrying `equals`, 13 were already covered by an
  existing scorecard assertion and several more were arithmetic narrative whose
  components were each asserted individually. balance_composition is the clearest
  case of why a check name cannot be mapped mechanically: on four documents its
  `equals` is total_printed, on Lumen it is the CARRIED BALANCE (249.84-249.84+0.00
  = 0.0, while Lumen's total is 248.09) — the same name means two different things.
  (b) A MUCH LARGER gap sat next to it, unmentioned: 29 gold FIELD names never
  asserted across 73 occurrences, including bill_to_address and currency_basis in
  ALL TEN files, plus 5 MONEY_FIELDS members declared as money and never checked.
  currency_basis is C3's OWN OUTPUT. So the array I flagged was mostly redundant
  and the thing I had not looked at was three times larger.
THE REAL GAP was the confidence-modifier mechanism: spec §5, 16 modifiers, asserted
  NOWHERE. Nothing would have noticed if arith_balance_mismatch stopped being
  applied — the modifier that decides whether a human ever looks at U-PAK's
  unexplained 48.92. _expected_modifiers derives expectations from three gold
  signals (text_source/ocr_only tag, has_flattened_annotations tag, any
  `<modifier>_applied: true` assertion) rather than a hand-written list, so a new
  gold file gets its expectations for free. handwritten_supporting deliberately
  implies nothing: §5's handwriting_detected is about a PRIMARY page and that tag
  says the opposite.
RULING: the four new arithmetic assertions are COMPOSITE ("the enabling value
  exists AND no mismatch modifier was applied"), not bare "modifier is absent". A
  bare absence check passes trivially on a pipeline that computed nothing — eight
  free passes, making the score read BETTER while measuring LESS. Paired this way
  each fails until the op genuinely runs and closes. Same reasoning kept
  `no_prior_balance` unwired and kept the confidence_modifiers assertion off the
  seven documents whose gold implies no modifier.
DESIGN DECISION: the field getter now looks in `fields` then falls back to
  `derived`. Gold puts currency_basis under `fields`; infer_currency writes it to
  `derived`, correctly, because nothing read it off a page. Rather than move the
  op's output to fit the label: GOLD LABELS A FACT ABOUT THE DOCUMENT AND DOES NOT
  SAY WHETHER A PIPELINE SHOULD READ IT OR COMPUTE IT. Provenance is not thereby
  unmeasured — it is exactly what currency_basis and payable_basis record, and both
  are asserted.
GUARDRAIL 3 (tests/test_scorecard_coverage.py): standing rule 3 has now been
  violated FIVE times (reference_list + all 15 tags, page_roles, the 4 contract
  keys, lane, and this), every one invisible — no test failed, no count looked
  wrong. The guardrail makes it mechanical: every gold assertion check name must
  carry one of four verdicts in GOLD_ASSERTION_COVERAGE (covered:/wired:/
  documentation/deferred:); the table may not go stale; a covered:/wired: verdict
  must name an assertion the scorecard ACTUALLY EMITS (a verdict pointing at
  nothing reads as coverage that is not there); every gold field, derived key and
  expected_routing key must be asserted or declared prose; and NO ASSERTION MAY
  PASS AGAINST AN EMPTY RECORD.
THE VACUITY CHECK EARNED ITS KEEP IMMEDIATELY: it found that 2 of the then-39
  passing assertions were FREE PASSES — U-PAK's derived.amount_payable and
  derived.payable_basis both expect null, which an empty record satisfies by
  coincidence. Confirms C3's suspicion that U-PAK's derived assertions had been
  passing without measuring anything. Allowed via a KEYED list with a written
  reason each (null IS the correct answer for U-PAK, F8), but MITIGATED not waved
  through: U-PAK also asserts confidence_modifiers requiring
  arith_balance_mismatch, which cannot be satisfied without the derivation actually
  running and refusing. A test asserts that mitigation exists, so U-PAK cannot
  reach green on the vacuous pair alone. VACUOUS_BY_CONSTRUCTION has 4 entries and
  a test asserts none is stale.
STILL UNMEASURED, deliberately: ctx.boosts never reaches the record (a boost shows
  up only as a higher confidence number and no gold label predicts a confidence
  value — hence duplicate_anchor_agrees is classified `documentation`);
  expected_routing.reason is free text; annotation_*_not_captured is deferred:C5
  because "the overlay value was not captured" needs a pack that knows which values
  are overlays; and 9 of the 16 modifiers have no gold signal implying them, which
  is the right place for them since no gold label states them.
Cluster C3b: COMPLETE (0 fix rounds). Full detail in task-c3b-report.md.
Cluster C4: EXECUTED INLINE. Delivers a real s7_gate (four lanes, forced-review
  overrides, deterministic audit sampling) and tests/test_f3_forced_review.py
  (GUARDRAIL 4). 40 new tests, suite 1101/1101 in 7.8s, mypy strict clean over 18
  files, ruff clean, gold 95 green. Scorecard 41/339 -> 42/339.
THE +1 IS THE DELIVERABLE RESUME HAD OWED SINCE C1b: Federal Recycling's `lane`
  now passes and the F3 chain works end to end across three clusters —
  annotations.detect_flattened (C1b) -> has_flattened_annotations tag ->
  flattened_annotations modifier (C3) -> forced review + `review` lane (C4).
SPEC ERRATUM 1: the spec's Stage 7 table lists THREE lanes (High, Medium/Low, Very
  Low). Two gold files expect a FOURTH, `review`, and gold is the objective
  function. It earns its place rather than being a synonym for `medium`: Federal
  Recycling's fields may extract perfectly and the reason a human must look is that
  the page carries values invisible to the text layer. Filing it under `medium`
  would put it in the queue for documents whose NUMBERS look shaky, a different
  queue with a different fix. Corpus: 7 high, 1 medium, 2 review, 0 low.
SPEC ERRATUM 2: handwriting_detected now fires on the `handwritten_supporting` tag.
  §5 defines it as "Primary page has handwriting" and the tag says the opposite, so
  C3 had not applied it — but Complete Beverage's gold routing DEPENDS on it, its
  expected_routing.reason names it explicitly ("ocr_source and handwriting
  modifiers apply"), and it is the better reading: a supporting page exists to
  corroborate the primary one (F10), so handwritten corroboration is weaker
  evidence. §5's wording is too narrow rather than this being too broad.
DESIGN CORRECTION (the gate needed a SECOND dimension): the inherited rule was
  `low` when the SHARE of short fields reaches 0.60. That cannot work. A
  document-wide modifier (ocr_source, draft_rules, handwriting_detected) penalizes
  EVERY field equally, so the share is always 0.0 or 1.0 and `medium` is
  unreachable for any document whose only penalties are document-wide. Complete
  Beverage is exactly that: 0.90 x 0.60 = 0.54 on every field, gold expects
  `medium` with regen False, and the share rule alone routes it to `low` and raises
  a regen flag telling someone to rewrite a persona that is working correctly.
  `low` now ALSO requires most fields below VERY_LOW_FLOOR (0.50). 0.50 is chosen
  to sit below 0.60, the harshest single modifier in the §5 enum — one harsh signal
  must never on its own read as "the rules are broken", because the fix for a
  handwritten page is not a new persona. A test asserts that RELATIONSHIP rather
  than the bare number.
THE BUG (real, and the important part of this cluster): the first implementation
  treated a pre-existing ctx.review_flag as a forcing reason, on the strength of
  C3's own handover note. ALL 34 GATE UNIT TESTS PASSED AND ALL TEN CORPUS
  DOCUMENTS CAME OUT `review` — including DTSS, which has no tags, no modifiers and
  nothing wrong with it. Cause: s5c_agent sets review_flag for every hard miss,
  correctly (spec Part 3: a first-time sender "emits anyway with the one-shot
  result and a review flag"), and with no personas EVERY document is a first-time
  sender. review_flag is too coarse to route on: "we have no rules for this sender
  yet" is not "this document has a problem", and one queue for both would bury
  Federal Recycling's invisible overlays under every new vendor. Forcing now reads
  the closed §5 modifier enum instead — flattened_annotations ("forces review,
  unconditionally") and arith_balance_mismatch ("also raises review"). U-PAK
  therefore reaches `review` through EVIDENCE rather than a flag anyone could set,
  which means its lane correctly FAILS today and will pass when C5 gives it a
  persona. That is why the numerator went to 42 and not 43. The flag itself is
  still never cleared; there are tests for both halves.
PROCESS: STANDING RULE 9 EARNED ITS KEEP ON THE CLUSTER RIGHT AFTER IT WAS WRITTEN.
  Every link in the F3 chain had passing unit tests while the chain was broken;
  only running a real PDF through all eight stages showed it. GUARDRAIL 4
  (tests/test_f3_forced_review.py) now walks the whole chain in one module.
RULINGS on precedence, each tested: a systemic collapse OUTRANKS a forced review
  (both true, but `low` carries the actionable regen signal and review_flag is set
  either way); a forced review OUTRANKS an empty confidence map (a forcing reason
  is a fact about the DOCUMENT, not about whether extraction ran — without this
  Federal Recycling reads `low` today and the F3 chain stays untestable until C5);
  an empty confidence map NEVER raises regen ("there are no rules yet" is not "the
  rules are wrong", and this also protects ten passing regen_flag assertions from
  flipping for a reason that says nothing about the pipeline); audit sampling never
  fires outside `high` and never changes the lane (a document already going to a
  human does not need sampling, and marking it would corrupt the statistic the
  sample exists to produce).
CARRIED FORWARD TO C5, important: pack-supplied thresholds are accepted by
  ConfidenceGate and supplied by nothing, so every field uses the 0.90 default.
  A `draft` persona applies draft_rules (0.85) to EVERY field, so a draft persona
  can NEVER produce a `high` lane — and seven documents expect one. C5's personas
  must reach `active` status, or must ship thresholds below 0.85.
Cluster C4: COMPLETE (0 fix rounds). Full detail in task-c4-report.md.
Cluster C5a: EXECUTED INLINE. Delivers packs/registry.py, packs/store.py, the six
  Northstar pack modules (+conventions.py, a seventh), six authored personas, and
  the s3/s4/s7/cli wiring. 107 new tests, suite 1208/1208 in 6.9s, mypy strict
  clean over 18 files, ruff clean, gold 95 green.
  SCORECARD 42/339 -> 128/339. Per document: dtss 23/24, complete-beverage 21/30,
  veritiv 20/37, federal-recycling 19/29, upak 17/32, edco 16/35. The four Digital
  Direction documents stay at 3 (that is C5b). 0/10 green — no Northstar document
  is fully clean yet, and the gap is almost entirely address/case formatting.
CONTROLLER DECISION: a pack claims a document by the BILL-TO on the page, not by
  the sender and never by the filename. The sender decides which PERSONA applies
  (s4); the recipient decides which PACK applies (s3). Conflating them would mean a
  new vendor could not be processed until someone said which pack it belonged to.
  `resolve_pack` returning None is a real answer, tagged `unclaimed_document`: an
  invoice in the wrong AP inbox is a real event somebody needs to see.
CONTROLLER DECISION: the fingerprint is `<pack>|<canonical vendor>`, computed from
  PAGE TEXT at the beforePersonaLookup hook — not from an extracted vendor_name.
  s4 runs before s5, so no field exists yet, and that ordering is not an
  inconvenience to route around: the persona is what tells s5 how to extract, so
  the lookup key cannot depend on extraction having happened.
FEWER HOOKS THAN THE PACK SPEC LISTS, each absence deliberate and tabulated in
  hooks.py: detectFlattenedAnnotations/assignPageRoles are already generic core
  (s2, C1b); deriveAmountPayable/runArithmeticCrosschecks/inferCurrency are each
  persona `adjust` declarations run by s6 (a hook would DOUBLE-COUNT the confidence
  boosts); northstarThresholds became ConfidenceGate reading ctx.pack.thresholds;
  attachAllocationMetadata is already on the record. Four hooks remain, and they
  are the four that cannot be expressed any other way.
NEW PACK MODULE (7th, not in the plan): conventions.py. EDCO's `prior_balance_basis`
  is 'gross' and NO SELECTOR CAN SUPPLY IT — it is not printed anywhere. That
  BALANCE FORWARD is carried in full is a fact about how EDCO bills, and F1b
  refuses to guess it (a missing basis is a review flag). So it is a per-vendor
  table in the pack, applied at afterExtraction. DELIBERATELY NOT a grammar
  feature: adding a "literal value" selector kind would let a rule agent write
  arbitrary constants into any field, a far larger hole than one hand-maintained
  table. A wrong entry here is a reviewed code change; a wrong constant in a
  persona would be an agent write.
DESIGN FLAW FOUND IN MY OWN C3 (real, and it blocked the whole cluster): s6 applied
  EVERY modifier to EVERY field. `currency_inferred_weak` fires on 8 of 10 gold
  documents via the pack_default rung, so every field of every one of them scored
  1.0 x 0.90 = 0.90 against a 0.95 total_printed threshold — NO DOCUMENT COULD EVER
  REACH THE `high` LANE. §5 calls modifiers "multiplicative" without saying what
  they multiply, and some are plainly document-wide (ocr_source, draft_rules,
  soft_miss, handwriting_detected, flattened_annotations) while others are about
  ONE field (currency_inferred_weak, anchor_alt_used, ambiguous_anchor,
  pattern_timeout, scanline_mismatch). Added JobContext.field_modifiers and
  add_field_modifier; s6 multiplies document-wide ones into everything and scoped
  ones into their own field only. Scoped modifiers still reach the record, because
  the record listing every modifier that fired is what makes a confidence number
  auditable.
GRAMMAR EXTENSION (deliberate, reviewed, 24th op): `join_lines_comma`. Ten gold
  files carry bill_to_address and eight carry vendor_address, and every one is a
  multi-line block represented as a single comma-joined string. No §4.1 op produced
  that — collapse_internal_spaces flattens the newline to a space and loses the
  separator — so roughly eighteen assertions were unreachable by any LEGAL persona.
  §10 says a new op needs review and a reason rather than an agent's say-so; this is
  that reason. Pure formatting: moves no value between fields, makes no business
  decision.
REGION TWEAK: near-anchor now extends 12pt to the LEFT as well as 300pt right. §2
  says "within 300pt right of", but a value printed BELOW its label is left-aligned
  with it and layout jitter puts it a point or two further left — strict equality
  dropped `Northstar Recycling Company, LLC` from under its own `Bill To` label.
CONTRACT FIX: _serialize now handles the two structured results a named pattern can
  produce, duck-typed so core does not import grammar. A DateResult reaches the
  record whenever a persona uses `date` without normalize_date_iso, which is legal;
  an AccountNumber crosses as its PRINTED form because the joinable form is a
  separate field (F6). Before this the CLI raised a raw TypeError from json.
CORPUS FACT (measured, for C5b and beyond): gold's currency_basis vocabulary is
  `explicit_iso_code` / `tax_regime_marker` / `pack_default`, NOT the names C3
  invented. Renamed. Naming the rungs anything else would have made the field
  unassertable, so the scorecard would have silently stopped measuring the F14
  ladder it exists to check.
MEASURED signals now in the ladder: contra = every per-unit rate on the page is
  negative (`-40.00/ST`). The `/UNIT` suffix is what makes it a RATE, and it is the
  only corpus signal separating a contra from an invoice carrying a rebate line —
  U-PAK prints `-40.500` and Complete Beverage `-0.65`, negative unit prices with
  no suffix, and neither is a contra. Handwriting = OCR noise ratio >= 0.40 on a
  SUPPORTING page; measured 0.51/0.46 on Complete Beverage's handwritten BOL pages
  against 0.22/0.28 on its printed ones and 0.17 on Federal Recycling. Only
  supporting pages are examined, which removes the false-positive risk entirely:
  Federal Recycling carries a handwritten margin note but is single-page.
  past_due = a SHORT line (<=6 words) containing PAST DUE, or an aging header —
  Federal Recycling's terms print "PAST DUE AMOUNTS SUBJECT TO INTEREST..." on
  every invoice it sends and its gold is correctly not tagged.
REQUIRED FIELD SET narrowed to {vendor_name, total_printed, amount_payable,
  bill_to_name}, deliberately. invoice_number is omitted because three of ten corpus
  documents print none (F6) — that is the whole reason the identity ladder falls
  back to account+period, so requiring a selector would make the documents F6 was
  written for unwritable. invoice_date is omitted because EDCO prints a billing date
  and no invoice date. currency is omitted because the F14 ladder produces it.
TWO FIXTURE DEFECTS, both mine, both standing rule 7: (1) test_registry's _page
  hardcoded page_number=1, so a two-page fixture was two copies of page 1 and the
  supporting-page test passed for the WRONG REASON. (2) test_northstar_ladder's
  _page put every token on ONE visual line, which made _is_own_paperwork see the
  bill-to inside its 4-line letterhead window and made every PAST DUE banner look
  like prose — two tests failed against CORRECT code. Both helpers now build real
  lines.
DEFECT (mine, cost a round): an unbounded `\s+` in a DTSS persona regex made V4
  reject the whole persona, and a rejected persona does not error — it is a lookup
  MISS and the document falls silently back to vision. DTSS dropped 23 -> 14
  passing assertions and nothing but the scorecard noticed. GUARDRAIL 5
  (tests/packs/test_personas_validate.py) now validates every shipped persona.
KNOWN GAPS, all formatting rather than extraction (see task-c5a-report.md):
  EDCO's gold title-cases an ALL-CAPS document throughout and no §4.1 op produces
  title case; several addresses span more lines than near-anchor's 40pt reaches;
  a persona cannot capture its own anchor text as a value, which is what
  bill_to_name needs when the label IS the value.
Cluster C5a: COMPLETE (0 fix rounds). Full detail in task-c5a-report.md.

## Cluster C6 — the real vision adapter, with cassettes

RULING (mine, and the important one): the plan's C6 exit criterion — "replay-gold
  reaches 10/10", via cassettes "hand-authored from the gold files" — is NOT MET and
  should not be. Two reasons, and the second dominates. (1) No corpus document
  reaches Stage 5b: all ten extract through 5a_cached and none collapses, so a
  cassette would never be consulted. (2) A cassette authored FROM gold and then
  scored AGAINST that same gold file is circular. The run would go green and measure
  nothing — and a green replay-gold would become indistinguishable from a working
  one. replay-gold is the only instrument this project trusts; inflating it is the
  most expensive available shortcut. corpus.json therefore ships EMPTY and
  GUARDRAIL 8 fails on any entry not marked provenance: recorded. Authoring one
  stays available — author it, change the test, write down why. Same rule as gold.
DESIGN: the vision response is a PRIVILEGE BOUNDARY, and adapters/vision/policy.py
  is to the vision path what grammar/validator.py is to the persona path. A
  VisionResult is not inert: s5b writes its fields into ExtractedFields and its
  irregularities into the modifier/tag lists, and s7 routes lanes off those lists.
  VISION_OBSERVABLE = {handwriting_detected, high_skew} — properties of the IMAGE,
  where a vision model is the best available witness. Everything else is excluded on
  principle: the arith_*/scanline/filename modifiers are computed by ops doing real
  comparisons (delegating them replaces arithmetic with an opinion), and
  flattened_annotations is excluded because s6 already detects it structurally AND it
  is one of the two FORCING_MODIFIERS. The property that buys: NEITHER surviving name
  can force review, so no vision response can route a lane by itself. GUARDRAIL 7
  asserts VISION_OBSERVABLE & FORCING_MODIFIERS == {} so nobody widens it silently.
  sanitize() runs on BOTH the live response and cassette replay — a cassette is a
  JSON file a human edits, which makes it untrusted in exactly the same way.
SPEC/PLAN DEVIATION 1: send the PDF as a base64 document block rather than "rendering
  pages to PNG". Rasterizing would add a pdfium/poppler dependency to produce a
  strictly WORSE input — a re-render can drop the flattened annotation overlays F3 is
  entirely about, page indices would have to be re-derived and kept in step with
  page_meta, and any resampling choice would silently become part of extraction
  accuracy. Guarded at 20MB raw (base64 inflates 4/3 vs the API's 32MB ceiling).
SPEC/PLAN DEVIATION 2: the port gained `source_path` (keyword-only, optional).
  PageText is the TEXT LAYER, and on the two documents that most need vision it is
  OCR output — the very thing we are checking. An adapter handed only PageText would
  be doing a text call and calling it vision. AnthropicVision has NO text-layer
  fallback: a missing source is a PermanentError, because falling back would return a
  plausible VisionResult from a model that never saw the page.
SPEC/PLAN DEVIATION 3: module named anthropic_adapter.py (the plan's file list says
  anthropic.py; its interface list says anthropic_adapter). A module named
  anthropic.py inside the package self-shadows the moment anyone runs the file
  directly. Not worth the trap.
DESIGN: cassette keys follow the document's CONTENT, not its path — same lesson as
  C1a's cache-key fix. A cassette survives the corpus moving and goes stale, as a
  loud miss, the moment the PDF changes. Source-byte and text-layer keys are
  domain-separated so they can never collide.
DESIGN: a replay miss RAISES. The tempting alternative — an empty VisionResult — is
  the silent-degradation pattern this project keeps removing (C1a's dead cache
  bypass; the rejected persona that became a silent vision fallback). An empty result
  makes "vision ran and found nothing" indistinguishable from "vision never ran". The
  Runner's emit-always guarantee is what makes raising affordable: one dead letter
  with an actionable reason, and count(intaken) == count(emitted) still holds.
FIX (pre-existing, found here): s5b filed vision irregularities as TAGS. Filing
  handwriting_detected as a tag puts the observation on the emitted record and leaves
  every field's confidence untouched — honoured in appearance only. Names in the
  section 5 enum now go to add_modifier; anything else stays a tag.
GOTCHA: mypy's per-module `ignore_missing_imports = true` is DEFEATED by
  `follow_untyped_imports = true` in the same override block. Cost a few minutes.
NOT VERIFIED: the live request shape. anthropic is not installed and no key exists,
  so every test injects a fake client. Pinned: the request we build and what we do
  with each response shape (refusal checked BEFORE reading content, max_tokens
  truncation, non-JSON, missing text block, invented fields). Not pinned: that the
  SDK accepts that request. First live call should be `--vision record` on one doc.
Cluster C6: COMPLETE (0 fix rounds). Full detail in task-c6-report.md.

## Printed-fields-only — narrowing extraction to what the page prints (2026-07-28/29)

Spec: specs/2026-07-28-printed-fields-only-design.md. Plan:
plans/2026-07-28-printed-fields-only.md. Six tasks, commits 367d126..HEAD.

THE NARROWING: both packs now extract only values printed on the document.
  Anything computed - amount_payable and its basis, the carried balance, the F14
  currency ladder, prior_balance_basis, carrier_canonical, the *_normalized forms
  - left FIELDS, left every persona's `adjust` list, and left the scorecard's
  numerator AND denominator. Nothing was deleted: every module and unit test is
  on disk, gold still records the derived answers, and re-enabling is a wiring
  change. GUARDRAILs 2 and 6 are `skip`ped with the deferral reason as the skip
  message rather than removed, so the un-skip is the reminder.
DESIGN: `REQUIRED` could not stay a flat set. The field spec says "any parseable
  date" and "at least one money amount"; V13 checks set membership. Encoding the
  literal names would have made EDCO (bill date, no invoice date) and every
  vendor that prints no total unwritable. `REQUIRED_ANY_OF:
  tuple[frozenset[str], ...]` plus one V13 clause is the minimum change that lets
  the spec's own wording be expressed.
DESIGN: `derive_document_identity` is the one derived thing that stays.
  core/contract.py requires the PRESENCE of document_identity and identity_basis
  - None is a valid value, absence is not - so dropping them would have broken
  count(intaken) == count(emitted), the one invariant this project refuses to
  bend. Pinned end to end in tests/test_printed_fields_only_path.py.

SPEC ERRATUM 1 (found in planning): the derived work does not live in hooks, as
  the spec's §5 framing implied. It lives in each persona's `adjust` list. Two
  hooks did come out, but the bulk of the unwiring was per-persona JSON.
SPEC ERRATUM 2 (found in planning): GOLD_ASSERTION_COVERAGE already carried a
  `deferred:<why>` verdict. No new mechanism was needed to retire the derived
  assertions - only a new reason string, DEFERRED_REASON.
FINDING (found in planning, and the one that changed the shape of the work):
  FOUR of the field spec's eight "Required" Digital Direction fields are not
  printed values at all. Three are closed-list row classifications
  (service_type, charge_type, the row-type flag) and one is envelope metadata
  (invoice_file_name). They are derivations wearing field names. The spec's
  "Required" level had been read as a printed-field list for the whole project.

PLAN DEFECT 1 (corrected mid-run, Task 2): the plan gave Task 2 a score
  expectation of 175-200/~230. That is the spec's END-STATE prediction, applied
  to a single task by mistake. The implementer refused to over-defer to hit it
  and was right to. Plan Step 6 was rewritten: at Task 2 the numerator drop must
  EQUAL the denominator drop, because every assertion being retired was passing.
  Measured 274/339 -> 239/304, exactly 35 and 35.
PLAN DEFECT 2 (corrected mid-run, Task 2): nothing in the plan told Tasks 3 or 4
  what to do with CHECKED_FIELDS. Narrowing FIELDS without narrowing
  CHECKED_FIELDS leaves GUARDRAIL 3 red. Assigned to a new Task 4 Step 6b, once
  both packs were narrowed, with a DEFERRED_FIELDS mechanism mirroring Task 2's
  DEFERRED_DERIVED_KEYS.

DEVIATION UPHELD (Task 4): the brief instructed the implementer to use
  AccountNumber.normalized for the Comcast reference hit. It refused, because
  .normalized strips hyphens (patterns.py:140, re.sub(r"[\s\-]")) and Lumen's
  gold hit 5-QXH7QKM7 keeps its hyphen - the instruction would have fixed Comcast
  and silently broken Lumen. Used strip_internal_whitespace instead. The
  re-reviewer patched .normalized back in and independently confirmed it
  hard-fails Lumen. The instruction was wrong.
CORRECTION (Task 4, and the accounting distinction that matters most): the first
  DEFERRED_FIELDS conflated three different things behind one name. Split into
  DEFERRED_DERIVED_FIELDS (5 - not printed, cannot come back without derivation),
  DEFERRED_PRINTED_FIELDS (6 - printed, had a working selector, left for
  deliverability; the list that shrinks first when scope widens) and
  EXTRACTION_DEBT (2 - tax_id and vendor_parent_reference: printed, gold-labelled,
  and never given a selector by ANY persona, before this spec or after). The last
  two went back into CHECKED_FIELDS (44 -> 46) and are still failing, which is
  correct. Deferring them would have deleted a pre-existing coverage gap from the
  denominator and called it a spec decision - raising the rate by measuring less.
  Rate went 73.8% -> 73.7%, the honest direction. vendor_parent_reference was
  re-verified as literal printed text on Lumen page 1.
FINDING (Task 5): the aggregator branch is structurally unreachable on this
  corpus - FilesystemIntake never sets sender_email. Scored zero change, as
  predicted, and is guarded by tests rather than by the gold set. Only two sender
  domains map to a vendor (cbd-usa.com, lumen.com), both backed by a printed
  vendor_email in gold; every other vendor honestly returns None. The reviewer
  tried bill.com.evil.com, xbill.com, bill.comx and ariba.com.attacker.net and
  could not construct a miss.

DOC FIX (Task 6): packs/digitaldirection/references.py's first paragraph still
  claimed field promotion was "the only way to get the right value on Comcast"
  and that "a text scan would capture the printed spacing and fail to join".
  Task 4 replaced that mechanism with whitespace-stripping in `_first`; correct
  paragraphs were appended after the stale one rather than replacing it, so the
  docstring contradicted itself. Rewritten to say one true thing: promotion is
  what the pack SHAPE asks for (the keys are printed plainly and already
  extracted), and the joinable form is a separate job done in `_first`.
DOC FIX (Task 6): core/senders.py said "a domain earns a place here only when a
  real document has arrived through it" while listing five domains, none of which
  any corpus document arrives from. Policy restated to match reality: three are
  named by pipeline-v2.md:169, the other two (intuit.com, coupahost.com) are
  category inferences and are now marked inline as such.

SCORE, measured rather than predicted: 274/339 with 1/10 green before, 193/262
  with 1/10 green after. The spec predicted 175-200 of ~230 and said 10/10 would
  become reachable. BOTH PREDICTIONS WERE WRONG and the measured numbers are the
  ones to trust. The denominator landed 32 above forecast because two review
  rounds refused to over-defer. 10/10 is not close: nine documents each still
  miss 2-15 assertions. Per document - Centracom 25/29, Comcast 25/29, Lumen
  24/29, Windstream 24/27, DTSS 19/19 PASS, EDCO 17/26, Complete Beverage 17/24,
  Veritiv 16/31, Federal Recycling 14/23, U-PAK 12/25.
WHOLE-PATH TEST (standing rule 10): tests/test_printed_fields_only_path.py, one
  real PDF per pack to a validated Stage 8 record. Asserts no DERIVED_ONLY name
  reaches either record, that both identity contract keys still do, and - the
  point of the file - that Centracom emits the PRINTED 33,876.40 and carries no
  amount_payable. That is the consequence this design accepts: extraction
  transcribes, downstream interprets, and the $20,123.80 gap is downstream's to
  catch. If the assertion ever flips, derivation was re-enabled without
  guardrails 2 and 6.
NEW STANDING RULE 11: retire expectations before capabilities. Narrowing FIELDS
  before re-verdicting the scorecard leaves the tree red for two tasks and, worse,
  V1 rejects the personas - and a rejected persona is a lookup MISS, so all ten
  documents fall back to vision silently. This plan was ordered scorecard, then
  field sets, then personas in the same commit as their field set, specifically
  to avoid that.
Printed-fields-only: COMPLETE. Six tasks, two fix rounds (Tasks 3 and 4).
