# Task 4 Report: populate `possible_duplicate_of` within a run

## What I implemented

1. **`src/docintel/core/duplicates.py`** (new) — `IdentityIndex`, an in-memory
   first-sighting map from `document_identity` to the `document_id` that first
   reported it. `see(document_id, identity)` returns `None` for the first
   sighting of an identity, for an unidentifiable document (`identity is
   None`), and for a document re-seen under its own `document_id` (replay).
   Otherwise it returns the `document_id` first seen with that identity. The
   module docstring states the within-run-only scope explicitly and why
   (cluster C7's persona store + an undecided retention policy).

2. **`src/docintel/pipeline/runner.py`** (modified) —
   - `Runner.__init__` now constructs one `self._identity_index =
     IdentityIndex()` per `Runner` instance.
   - `Runner._emit` sets `ctx.possible_duplicate_of =
     self._identity_index.see(ctx.document_id,
     ctx.derived.get("document_identity"))` immediately after the
     `beforeEmit` hook and before `build_record(ctx)` is called.
   - `Runner._minimal_dead_letter` is unchanged (see judgement call 1 below).

3. **`tests/core/test_duplicates.py`** (new) — the four unit tests specified
   in the brief, verbatim.

4. **`tests/test_printed_fields_only_path.py`** (modified) — one whole-path
   test, `test_the_same_invoice_processed_twice_reports_the_first_document`,
   satisfying standing rule 10. Adapted from the brief's snippet (see
   "Substitutions" below): builds one `Runner` via `build_pipeline
   (FakeVision())`, then calls `.process()` twice on that same runner with the
   real Veritiv invoice PDF (`northstar-veritiv-715-33905296`'s `source_file`)
   under two different `document_id`s, and asserts the first record's
   `possible_duplicate_of` is `None` and the second's is `"first"`.

## Substitutions from the brief's literal snippets

- **Step 1 test file**: used verbatim, no changes needed — it type-checked
  and ran correctly against a plain `IdentityIndex` with no other
  dependencies.
- **Step 3 implementation**: used verbatim, with one edit — restored the
  original cluster references ("C2b", "cluster C7") that the brief's snippet
  had slightly reworded, because those exact tokens are used consistently
  elsewhere in this codebase's own docs (`docs/superpowers/RESUME.md`,
  `docs/superpowers/plans/2026-07-29-weakness-remediation.md`) and are
  accurate here, so I kept the codebase's own vocabulary.
  Everything else — the file, the class, and the `see` method — matched the
  real repo (`derive_document_identity` in `src/docintel/grammar/ops/
  derive.py` truly is unconditional and truly stores under the key
  `"document_identity"` on `ctx.derived`, a `DerivedFields` with a `.get`
  method).
- **Step 5 wiring**: the brief's snippet said to consult `self._index` — the
  real attribute is `self._identity_index` (there was no naming collision to
  resolve, I just picked an explicit name; `_index` would also have worked,
  but `_identity_index` reads better next to `IdentityIndex`).
- **Step 5 whole-path test**: the brief's snippet referenced a `_runner()`
  helper function and a `VERITIV_PDF` constant. **Neither exists in
  `tests/test_printed_fields_only_path.py`** — that file's actual helper is
  `_run(gold_id)`, which builds a *fresh* runner per call (by design — see
  its module docstring, which already explicitly says "a shared runner
  carries duplicate-detection state from one document into the next", i.e.
  it was written anticipating this exact task). Since the whole point of this
  test is to *share* one runner across two `.process()` calls, I could not
  reuse `_run`. I wrote the test using the file's real conventions instead:
  read the Veritiv gold JSON directly (`gold_id`/`source_file`, same as
  every other test in the file), build one `Runner` with
  `build_pipeline(FakeVision())`, and call `.process()` on it twice with
  document ids `"first"` and `"second"`. This is a substitution of test
  scaffolding only — the assertion (`second["possible_duplicate_of"] ==
  "first"`) is unchanged from the brief.

## What I tested and the results

### TDD Evidence

**RED** — `python3 -m pytest tests/core/test_duplicates.py -q`
```
ImportError while importing test module '.../tests/core/test_duplicates.py'.
tests/core/test_duplicates.py:1: in <module>
    from docintel.core.duplicates import IdentityIndex
E   ModuleNotFoundError: No module named 'docintel.core.duplicates'
1 error in 0.09s
```
Expected failure: `docintel/core/duplicates.py` did not exist yet. Matches the
brief's predicted failure exactly.

**GREEN** — `python3 -m pytest tests/core/test_duplicates.py -q`
```
....                                                                     [100%]
4 passed in 0.01s
```

**GREEN (wiring + whole-path)** — `python3 -m pytest tests/core/test_duplicates.py tests/test_printed_fields_only_path.py -q`
```
.............                                                            [100%]
13 passed in 1.99s
```

### Full verification

- `python3 -m pytest -q` → `1495 passed, 12 skipped` (the 12 skips are
  pre-existing, unrelated to this task — deferred `derive_amount_payable`
  guardrails per `docs/superpowers/specs/2026-07-28-printed-fields-only-design.md`).
- `python3 -m mypy` → `Success: no issues found in 27 source files`
- `ruff check src tests` → `All checks passed!`
- `python3 docs/corpus/validate_gold.py` → `gold documents: 10, checks run:
  95, failures: 0` — gold files are byte-identical (only `git status`/`git
  diff` on `docs/corpus/gold/` was empty throughout; I never touched them).
- `python3 -m docintel.cli replay-gold` → exit code `1` (expected — documents
  fail on pre-existing, unrelated criteria, not a broken build):
```
FAIL  digitaldirection-centracom-0384043574  (26/29)
FAIL  digitaldirection-comcast-8495444620365242  (25/29)
FAIL  digitaldirection-lumen-5-QXH7QKM7  (26/29)
FAIL  digitaldirection-windstream-041069076  (24/27)
FAIL  northstar-complete-beverage-32930  (19/25)
PASS  northstar-dtss-6060  (19/19)
FAIL  northstar-edco-077087  (16/26)
FAIL  northstar-federal-recycling-1330123  (16/23)
FAIL  northstar-upak-4378107  (12/25)
FAIL  northstar-veritiv-715-33905296  (19/31)

1/10 documents green
```
Sum: 26+25+26+24+19+19+16+16+12+19 = **202** / (29+29+29+27+25+19+26+23+25+31
= **263**). **202/263, 1/10 green — exactly the stated baseline, unchanged.**
No corpus document flagged itself as a duplicate of another: I confirmed
`scorecard.replay_gold` (`src/docintel/scorecard.py:693`) calls
`runner = runner_factory()` **inside** its per-document loop, so each of the
10 gold documents gets its own fresh `Runner` and thus its own
`IdentityIndex` — there is no shared index across gold documents for this
CLI path. This matches the pre-existing docstring already in
`tests/test_printed_fields_only_path.py` ("a shared runner carries
duplicate-detection state from one document into the next"), so nothing here
is a new risk to the corpus scorecard. **No cross-document identity
collision was observed or needed working around** — the ten gold `gold_id`s
each get an independent index, so this is not a finding.

## Judgement calls

### 1. Is a dead-lettered document still a "sighting"?

**Ruling: yes, for the path where a record can still be built at all; no,
for `_minimal_dead_letter`'s fallback record — and in practice these are the
same answer, because `_minimal_dead_letter` never has a real identity to
offer.**

Concretely: `_emit()`'s main path calls `self._identity_index.see(...)`
using whatever `ctx` was handed to `_emit` — which may already carry
`disposition == "dead_letter"` if an earlier stage raised and `process()`'s
catch-all set it (`runner.py:74-80`). That `ctx` may or may not have a real
`derived.document_identity`, depending on how far the pipeline got before it
failed (it's computed unconditionally inside `s6_capture.CaptureFields.run`,
so a document that got past Stage 6 before later failing still has it). I
treat this as a legitimate sighting: the identity, when present, was
genuinely computed by the pipeline from the page — the fact that a *later*,
unrelated stage failed doesn't make the identity false.

`_minimal_dead_letter` (the fallback invoked when `build_record` or
`validate_record` themselves raise) is a different matter: it builds a
**brand-new fresh `JobContext`** via `new_context(document_id=..., 
source_path="")` (`runner.py:120-125`), which has never run any stage, so
its `derived` is the default empty `DerivedFields()` — `document_identity`
is simply absent, and `ctx.derived.get("document_identity")` would return
`None` even if I called `see()` there. Recording a sighting with identity
`None` is a no-op by `IdentityIndex.see`'s own design (`None` in, `None` out,
nothing stored). So there is genuinely nothing to gain by wiring the index
into `_minimal_dead_letter`, and doing so would require either making it a
non-static method (widening its contract for no behavioural benefit) or
threading the index through as a parameter — both are complexity the brief's
YAGNI constraint rules out. I left `_minimal_dead_letter` untouched.

### 2. Runner lifetime — is "one `Runner` instance" really "one run"?

**Confirmed, with one caveat worth flagging.** I checked every call site
(`grep -rn "Runner(" src/ tests/`): every production path
(`pipeline/stages/__init__.py:build_pipeline`) and every test constructs a
**new** `Runner` per logical run. Critically, `scorecard.replay_gold`
(`src/docintel/scorecard.py:693`) calls `runner_factory()` **inside its
per-document loop** — so even though `replay_gold` processes all 10 gold
documents in one CLI invocation, each document gets its own fresh `Runner`
and thus its own `IdentityIndex`. That means "one run" in this codebase's
actual usage is **one document**, not "one `replay-gold` invocation" — which
is why no gold document could ever be flagged as a duplicate of another
under the current CLI, and why the 202/263 baseline holds exactly. This is
already the behavior the codebase's own test docstring
(`tests/test_printed_fields_only_path.py`, pre-existing) anticipated and
documented before I touched it. The caveat: if a future caller wanted
duplicate detection to span an entire multi-document batch (e.g. a
directory of invoices dropped in together), they would need to construct one
`Runner` and call `.process()` on it repeatedly themselves — `replay-gold`
does not do this today, and I did not change it, since the brief's scope is
strictly "one index per Runner instance" and does not ask me to change how
many runners the CLI builds.

## The emit-path safety argument

`count(intaken) == count(emitted)` cannot break because:

- `IdentityIndex.see(document_id: str, identity: str | None) -> str | None`
  is a pure function over two already-typed, already-in-hand values: a
  `dict.setdefault` call and an equality check. It performs no I/O, no
  parsing, no external calls, and raises nothing that Python's own dict
  implementation wouldn't raise for a hashable-string key (which
  `document_id: str` and `identity: str | None` always are, by the type
  signature `_emit` already enforces via `ctx.document_id: str` and
  `ctx.derived.get(...)` which returns `Any` but is always fed a `str |
  None` in practice here).
- The call sits inside `_emit`'s existing `try/except Exception` block
  (`runner.py:100-118`), so even in the hypothetical case where it raised,
  the pre-existing catch-all would degrade to `_minimal_dead_letter` exactly
  as it does for `build_record`/`validate_record` failures today — the
  invariant's existing protection, unchanged.
- I did not touch `process()`'s intake counter, the stage loop, or the
  dead-letter path in `process()`'s except-block; `_emitted` is still
  incremented unconditionally after `_emit` returns
  (`runner.py:86-88`), and `_emit` still always returns a `dict[str, Any]`
  on every code path.
- Full suite evidence: `tests/test_invariant.py` (which specifically
  exercises injected failures at every stage to assert `count(intaken) ==
  count(emitted)`) passed unchanged as part of the 1495-pass full run above.

## Scorecard: before and after

Both **before and after**: **202/263 assertions, 1/10 documents green.**
(Task 4 is additive to the contract's meaning, not to any gold assertion —
`replay-gold` gives each document a distinct `gold_id`, so no document's
`possible_duplicate_of` field flips from `None` to a real value under the
current gold corpus, and none did.)

## Files changed

- `src/docintel/core/duplicates.py` (new)
- `src/docintel/pipeline/runner.py` (modified: import + `__init__` +
  `_emit`)
- `tests/core/test_duplicates.py` (new)
- `tests/test_printed_fields_only_path.py` (modified: one new whole-path
  test + a `VERITIV_GOLD` constant)

Commit: `27ee8e0` — `feat(core): populate possible_duplicate_of within a run`

## Self-review

- **Completeness**: brief's 7 steps all done — failing test, confirmed
  failure, implementation, confirmed pass, runner wiring, full suite +
  scorecard, commit.
- **Naming**: `IdentityIndex`, `see`, `_identity_index` all match the
  brief's public interface exactly (`core.duplicates.IdentityIndex` with
  `see(document_id: str, identity: str | None) -> str | None`).
- **YAGNI**: no persistence, no database, no configuration, no cross-run
  index, no options on `IdentityIndex.__init__`. `_minimal_dead_letter` was
  deliberately left untouched rather than "future-proofed" — see judgement
  call 1.
- **Test quality**: the four unit tests are the brief's own (verbatim); the
  whole-path test uses a real PDF and a real gold-file-sourced path rather
  than a synthetic fixture, per standing rule 10 and this codebase's own
  "standing rule 7" (don't trust a fixture's comment over its measured
  behaviour) — I ran it and read its actual output rather than assuming the
  Veritiv invoice number was stable without checking (confirmed via
  `docs/corpus/gold/northstar-veritiv-715-33905296.json`:
  `fields.invoice_number == "715-33905296"`).
- **Pristine output**: `mypy` clean, `ruff` clean, no new skips, no new
  warnings introduced, gold files byte-identical (untouched).

## Issues or concerns

None. Both judgement calls resolved cleanly with evidence from the existing
code (in particular, `tests/test_printed_fields_only_path.py`'s pre-existing
docstring already anticipated and documented the "one runner per document"
design this task formalizes). No corpus document flagged itself as a
duplicate — not a finding, since `replay_gold` already builds one `Runner`
per document by construction, and each of the 10 documents has a
sufficiently distinct `document_identity` in the gold corpus.

---

# Fix Report (review round 1)

## The finding

Review came back **Spec ❌ / Needs fixes**, one Important finding (risk 1),
one Minor. Risks 2 and 3 (invariant safety, `_minimal_dead_letter`'s
fresh-context factual claim) were confirmed correct on direct inspection and
required no change.

**Risk 1, verbatim summary:** `Runner._emit` called the original mutating
`IdentityIndex.see(...)` *before* `build_record`/`validate_record` ran. If
those raised, the `except` branch discarded `ctx` and rebuilt the record from
a **fresh, empty** context via `_minimal_dead_letter` — which carries no
`document_identity` and no `possible_duplicate_of` (both default/absent on a
brand-new `JobContext`). But the mutating `see()` call had already,
irrevocably, registered this document as the first sighting of that
identity. A later, successfully-processed document B with the same identity
would then report `possible_duplicate_of: "A"` — pointing a reviewer at A's
record, which contains zero evidence (no identity, no claim) to corroborate
that pointer. Exactly the false-confidence failure mode Task 4 exists to
remove, reintroduced at the emit-failure edge.

## Which fix I chose, and why

The finding offered two options: (a) only commit the index mutation once
`build_record`/`validate_record` succeed, or (b) have `_minimal_dead_letter`
preserve the already-computed identity/`possible_duplicate_of` instead of
discarding it via a from-scratch context.

**I chose (a).** Reasoning:

- `_minimal_dead_letter`'s fresh-context design is itself deliberate and
  documented: *"Built from a fresh context so no field polluted by a
  partially-run pipeline can make it fail validation too."* Option (b) would
  mean selectively re-introducing fields from the very ctx whose
  build/validate just failed, back into the context designed specifically to
  be immune from that ctx's problems — undermining the reason that design
  exists (Chesterton's fence).
- Option (a) is a direct structural guarantee rather than a copy-some-fields
  patch: a document's identity claim becomes permanent in the index if and
  only if the record it belongs to is proven buildable and valid. There's no
  question of "did I preserve the right fields" — the commit literally
  cannot happen before validation succeeds.
- It satisfies the stated constraint that option (a) "has to keep working
  when `see()` is called on a document that later dead-letters for a
  *different* reason (a stage raising before `_emit` is even reached)": for
  that path, `ctx` already carries `disposition == "dead_letter"` from
  `process()`'s catch-all, but `_emit` still runs `build_record`/
  `validate_record` on the real (non-fresh) `ctx` and those normally succeed
  (dead-letter records don't require `document_identity` presence, and
  `build_record` serializes `ctx.derived.values` unconditionally regardless
  of disposition). So the commit still fires, and the shipped record still
  carries the identity — the claim stays corroborable. Verified by the new
  regression test below, which specifically exercises the *other* case
  (identity computed, but `_emit` itself fails) to pin the boundary.

## What I changed

1. **`src/docintel/core/duplicates.py`** — split `IdentityIndex.see` into:
   - `peek(identity) -> str | None`: non-mutating lookup of the current
     first-sighting document_id for an identity.
   - `commit(document_id, identity) -> None`: registers `document_id` as
     first-seen for `identity` if no one already holds that slot; a no-op
     for `identity is None` or an already-claimed identity.
   - `see(document_id, identity) -> str | None`: now implemented as
     `peek` immediately followed by `commit` — kept byte-for-byte behaviorally
     identical (verified: all four original unit tests pass unchanged) for
     callers that don't need the split.
   Added class docstring explaining why the split exists (the review
   finding), and three new unit tests: `peek` doesn't mutate,
   `commit` is a no-op for an unidentifiable document, and — the exact bug
   this split prevents — a peeked-but-never-committed identity is still
   unclaimed for the next document.

2. **`src/docintel/pipeline/runner.py`** — `_emit` now:
   - Computes `identity = ctx.derived.get("document_identity")` once.
   - Sets `ctx.possible_duplicate_of = self._identity_index.peek(identity)`
     — non-mutating, so the candidate record can carry an answer without
     yet reserving anything.
   - Calls `build_record(ctx)` then `validate_record(record)` as before.
   - **Only after both succeed**, calls
     `self._identity_index.commit(ctx.document_id, identity)` — the
     one-line change that closes the finding.
   - Rewrote the inline comments to state precisely what "cannot raise"
     does and does not guarantee (addresses the Minor finding too: the old
     comment conflated "cannot raise" with "cannot produce a stale/incorrect
     result" — the new comments separate the invariant-safety claim
     (`peek` is a plain dict `.get`, cannot raise) from the correctness
     claim (the answer is only made permanent once proven to belong to a
     shipped record).

3. **`tests/pipeline/test_runner.py`** — added
   `test_an_identity_seen_before_a_build_failure_does_not_claim_the_slot`,
   the test the reviewer said was missing. A `FlakyIdentity` stage sets a
   real `document_identity` ("shared-identity") on every call, and on its
   *first* call also sets an illegal confidence value
   (`ctx.confidence["x"] = 99.0`, outside `[0, 0.99]`) so `validate_record`
   raises inside `_emit` and the document degrades to
   `_minimal_dead_letter`. Asserts:
   - `d1` (the failing document) dead-letters, its record has no
     `document_identity` in `derived`, and its own
     `possible_duplicate_of` is `None` (as before).
   - `d2`, processed next on the **same runner** with the same identity,
     comes back `processed` with `possible_duplicate_of is None` — i.e. it
     is free to claim the slot d1 never got to keep, rather than being told
     (falsely, with nothing to back it) that it duplicates d1.
   Without the fix this test fails: `d2["possible_duplicate_of"]` would be
   `"d1"`.

4. **`tests/core/test_duplicates.py`** — added three unit tests for the new
   `peek`/`commit` split (listed above under item 1).

## Covering tests, commands, and output

**Focused (the amended files' own tests):**
```
python3 -m pytest tests/core/test_duplicates.py tests/pipeline/test_runner.py tests/test_printed_fields_only_path.py -q
```
```
..............................                                           [100%]
30 passed in 2.24s
```

**Full suite:**
```
python3 -m pytest -q
```
```
1499 passed, 12 skipped in 11.23s
```
(1495 → 1499: +4 new tests — 1 in `test_runner.py`, 3 in `test_duplicates.py`.
 The 12 skips are the same pre-existing, unrelated `derive_amount_payable`
 guardrail skips as before.)

**mypy:**
```
python3 -m mypy
```
```
Success: no issues found in 27 source files
```

**ruff:**
```
ruff check src tests
```
```
All checks passed!
```

**Gold byte-compare:**
```
python3 docs/corpus/validate_gold.py
```
```
gold documents : 10
checks run     : 95
failures       : 0

all gold labels are internally consistent ✓
```
`git status --porcelain docs/corpus/gold/` — empty, confirmed untouched.

**Scorecard:**
```
python3 -m docintel.cli replay-gold
```
```
FAIL  digitaldirection-centracom-0384043574  (26/29)
FAIL  digitaldirection-comcast-8495444620365242  (25/29)
FAIL  digitaldirection-lumen-5-QXH7QKM7  (26/29)
FAIL  digitaldirection-windstream-041069076  (24/27)
FAIL  northstar-complete-beverage-32930  (19/25)
PASS  northstar-dtss-6060  (19/19)
FAIL  northstar-edco-077087  (16/26)
FAIL  northstar-federal-recycling-1330123  (16/23)
FAIL  northstar-upak-4378107  (12/25)
FAIL  northstar-veritiv-715-33905296  (19/31)

1/10 documents green
```
Exit code: `1` (expected — documents fail on pre-existing, unrelated
criteria; not a broken build). Sum: 26+25+26+24+19+19+16+16+12+19 =
**202** / 263. **Scorecard confirmed unchanged: 202/263, 1/10 green.**

## Files changed (this fix round)

- `src/docintel/core/duplicates.py` (modified: `see` split into `peek` +
  `commit`)
- `src/docintel/pipeline/runner.py` (modified: `_emit` peeks before
  build/validate, commits only after)
- `tests/core/test_duplicates.py` (modified: +3 tests for `peek`/`commit`)
- `tests/pipeline/test_runner.py` (modified: +1 regression test, the one the
  review required)

Commit: `4d3ff14` — `fix(core): don't let a failed emit claim a
duplicate-identity slot`

## Self-review of the fix

- The original four `IdentityIndex.see` unit tests were **not modified** and
  still pass, confirming `see`'s externally-observable behavior is
  unchanged — this fix only changes *when* the mutation the runner triggers
  becomes permanent, not what `see()` itself does for direct callers.
- No new persistence, configuration, or cross-run state was introduced —
  `peek`/`commit` are still backed by the same single in-memory `dict`,
  scoped to one `Runner` instance.
- The Minor finding (the "cannot raise" comment conflating invariant-safety
  with correctness) is addressed by splitting the two claims into separate,
  precise comments at the `peek` and `commit` call sites in `_emit`.

---

# Fix Report (review round 2)

## The finding

Both round-1 findings were confirmed **ADDRESSED** by re-review: the
peek/commit split closes the uncorroborable-claim hole, `commit` runs after
`validate_record` inside the same `try` so `except` fires before `commit` is
ever reached, and `test_an_identity_seen_before_a_build_failure_does_not_claim_the_slot`
genuinely exercises the required scenario.

But the round-1 fix introduced a new regression, caught by the coordinator's
own direct verification before sending the finding:

**`peek(identity)` took only `identity`, not `document_id`, so it could not
exclude a self-match.** The old, single-call `see(document_id, identity)`
always excluded "the document on file is THIS document" via
`None if first == document_id else first`. When `_emit` was rewritten to
call `peek` (to look up without mutating) followed by `commit` (to mutate
only after validation), that self-exclusion logic was left behind inside
`see` — which nothing in the pipeline calls anymore. Concretely, on one
`Runner` instance:

```
peek("X")            -> None        # first call, d1
commit("d1", "X")
peek("X")            -> "d1"        # d1 REPROCESSED under its own id
_emit sets ctx.possible_duplicate_of = "d1"   # for d1 itself - wrong
```

The four `IdentityIndex` unit tests (including the brief's own
`test_the_same_document_id_twice_is_a_replay_not_a_duplicate`) kept passing
throughout, because they all call `see()`, and `see()`'s self-exclusion
logic was untouched — they were asserting a guarantee on a code path the
runner no longer uses. That mismatch (tests cover `see`, runner calls
`peek`+`commit`) is exactly why the regression shipped undetected.

## The fix

Gave `peek` the same `document_id` parameter `commit` already has, and moved
the self-exclusion check into `peek` itself:

```python
def peek(self, document_id: str, identity: str | None) -> str | None:
    if identity is None:
        return None
    first = self._first.get(identity)
    if first is None or first == document_id:
        return None
    return first
```

`see` is now defined purely as `peek(document_id, identity)` followed by
`commit(document_id, identity)`, returning `peek`'s answer directly (no
separate self-check duplicated in `see` anymore) — so `see`'s behavior
literally **cannot drift** from what `_emit` gets, because `_emit` calls the
exact same `peek` that backs `see`. Verified all four original `see` unit
tests still pass unchanged with this composition (same four assertions, same
inputs, same expected outputs — I traced each by hand against the new
`peek`/`commit` bodies before running them, and confirmed by running them).

`Runner._emit` now calls `self._identity_index.peek(ctx.document_id, identity)`
instead of `self._identity_index.peek(identity)` — the one-line call-site
change that closes the finding, plus an inline comment explaining why
`document_id` has to be passed through.

I considered the alternative the finding offered (compare against
`ctx.document_id` in `_emit` itself, leaving `peek`'s signature alone) and
rejected it: it would leave `peek` and `commit` with mismatched parameter
lists (one taking `document_id`, one not) for no structural reason, and
would leave the exact bug class open to recurrence anywhere else `peek` is
ever called directly (there's currently only one call site, but "the fix
only works because of an extra line at the one call site that remembers to
add it" is a weaker invariant than "the self-exclusion is inside the
primitive itself"). Passing `document_id` to `peek` closes the class of bug,
not just this instance of it, and it's what restores `see`'s two composed
primitives to actually being decomposed-and-recomposable without behavior
loss — which the coordinator's message flagged as the property to protect
("the behaviour asserted by the unit tests is the behaviour the runner
actually gets").

## What I changed

1. **`src/docintel/core/duplicates.py`**:
   - `peek(self, identity)` → `peek(self, document_id, identity)`, now
     excluding `document_id` itself as a "first sighting" (mirrors the
     self-exclusion `see` always had).
   - `see` simplified to `first = self.peek(document_id, identity); self.commit(document_id, identity); return first` — no more separate self-check, since `peek` now owns it.
   - Updated the class docstring to explain why `peek` takes `document_id`
     and to record this as the second review finding.

2. **`src/docintel/pipeline/runner.py`** — `_emit` now calls
   `self._identity_index.peek(ctx.document_id, identity)` (was
   `peek(identity)`); updated the surrounding comment to explain the
   self-exclusion this passes through.

3. **`tests/core/test_duplicates.py`**:
   - Updated `test_peek_reports_the_first_sighting_without_mutating` and
     `test_commit_is_a_no_op_for_an_unidentifiable_document` to call `peek`
     with a *different* `document_id` than the one committed (so they still
     test what they claim — peeking from another document's perspective —
     rather than accidentally exercising the self-exclusion path).
   - Added `test_peek_excludes_a_replay_of_the_first_sighting_itself`,
     pinning the exact regression at the `IdentityIndex` unit level: after
     `idx.commit("doc-1", "x")`, `idx.peek("doc-1", "x")` must be `None`.
   - Updated `test_a_peeked_but_never_committed_identity_is_still_unclaimed`'s
     `peek` call to the two-argument form.

4. **`tests/pipeline/test_runner.py`** — added
   `test_reprocessing_one_document_id_is_a_replay_not_a_duplicate_of_itself`,
   the test the review **required**, placed here (not in
   `tests/core/test_duplicates.py` alone, per the explicit instruction, since
   that file's tests exercise `see()`, the layer that already passed while
   the bug shipped). It builds one `Runner`, calls `.process("d1", ...)`
   twice with the same `document_id` on a stage that sets a real
   `document_identity` ("shared-identity") each time, and asserts both
   records' `possible_duplicate_of` is `None` — the second call is the one
   that would have failed under the round-1 bug.

## Proof the new test actually catches the regression

Before restoring the fix, I mechanically reproduced the exact round-2 bug
(reverted `peek` to the single-argument form and the `_emit` call site to
match) with the new test present, and ran it:

```
python3 -m pytest tests/pipeline/test_runner.py -q -k "reprocessing_one_document_id"
```
```
FAILED tests/pipeline/test_runner.py::test_reprocessing_one_document_id_is_a_replay_not_a_duplicate_of_itself
AssertionError: d1 replayed under its own document_id must never be told it duplicates itself
assert 'd1' is None
```
This is the literal bug from the finding: `second["possible_duplicate_of"]`
came back `"d1"` — a document told it duplicates itself. I then restored the
fixed `peek`/`commit`/`_emit` exactly (confirmed via `git diff` showing only
the intended changes, no leftover verification code) before re-running
everything below.

## Covering tests, commands, and output (after restoring the fix)

**Focused (the amended files):**
```
python3 -m pytest tests/core/test_duplicates.py tests/pipeline/test_runner.py tests/test_printed_fields_only_path.py -q
```
```
................................                                           [100%]
32 passed in 2.04s
```
(30 → 32: +1 `IdentityIndex`-level test (`test_peek_excludes_a_replay_of_the_first_sighting_itself`), +1 runner-level test (`test_reprocessing_one_document_id_is_a_replay_not_a_duplicate_of_itself`).)

**Full suite:**
```
python3 -m pytest -q
```
```
1501 passed, 12 skipped
```
(1499 → 1501, the same 12 pre-existing, unrelated skips as every prior run.)

**mypy:**
```
python3 -m mypy
```
```
Success: no issues found in 27 source files
```

**ruff:**
```
ruff check src tests
```
```
All checks passed!
```

**Gold byte-compare:**
```
python3 docs/corpus/validate_gold.py
```
```
gold documents : 10
checks run     : 95
failures       : 0

all gold labels are internally consistent ✓
```
`git status --porcelain docs/corpus/gold/` — empty, confirmed untouched.

**Scorecard:**
```
python3 -m docintel.cli replay-gold
```
```
FAIL  digitaldirection-centracom-0384043574  (26/29)
FAIL  digitaldirection-comcast-8495444620365242  (25/29)
FAIL  digitaldirection-lumen-5-QXH7QKM7  (26/29)
FAIL  digitaldirection-windstream-041069076  (24/27)
FAIL  northstar-complete-beverage-32930  (19/25)
PASS  northstar-dtss-6060  (19/19)
FAIL  northstar-edco-077087  (16/26)
FAIL  northstar-federal-recycling-1330123  (16/23)
FAIL  northstar-upak-4378107  (12/25)
FAIL  northstar-veritiv-715-33905296  (19/31)

1/10 documents green
```
Exit code `1` (expected). Sum: 26+25+26+24+19+19+16+16+12+19 = **202** / 263.
**Scorecard confirmed unchanged: 202/263, 1/10 green.**

## Files changed (this fix round)

- `src/docintel/core/duplicates.py` (modified: `peek` gains `document_id`
  and its own self-exclusion; `see` simplified to compose `peek`+`commit`
  with no separate check)
- `src/docintel/pipeline/runner.py` (modified: `_emit`'s `peek` call passes
  `ctx.document_id`)
- `tests/core/test_duplicates.py` (modified: fixed two existing tests'
  `peek` calls to the two-argument form; added one test pinning the
  self-exclusion)
- `tests/pipeline/test_runner.py` (modified: added the required
  runner-level self-replay regression test)

Commit: `0dad48a` — `fix(core): stop peek from calling a replay a duplicate
of itself`

## Self-review of this round

- The required test lives in `tests/pipeline/test_runner.py`, not
  `tests/core/test_duplicates.py` alone, per the explicit instruction — it
  drives a real `Runner` through `.process()` twice, so it exercises the
  exact `_emit` → `peek`/`commit` path the bug was in, not just the
  `IdentityIndex` object in isolation.
- Confirmed by direct reproduction (not just reasoning) that the new
  runner-level test fails against the round-2 bug and passes against the
  fix — evidence above, not assertion.
- `see`'s four original unit tests were not weakened or deleted; they still
  pass, and now they are true statements about the runner's behavior too
  (since `see` is defined in terms of the same `peek` `_emit` calls),
  closing the "tests cover a dead path" gap the coordinator flagged.
- No new persistence, configuration, or cross-run state introduced in this
  round either.

