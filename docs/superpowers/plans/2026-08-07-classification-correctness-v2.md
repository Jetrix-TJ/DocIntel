# Classification Correctness Implementation Plan — v2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Supersedes** `2026-08-07-classification-correctness.md`, which did not survive review.
The nine blocking defects and the reasoning for this reordering are recorded in
`2026-08-07-classification-correctness-REVIEW.md`; that document is required reading
before touching any task here.

**Goal:** Eliminate every verified-wrong claim and tag in the classification layer,
make the wrong ones *visible* to the scorecard so they cannot silently return, and
prove the result across all 111 real second-sample documents rather than the 11 gold
ones.

**Architecture:** Cheapest-highest-value first, because two review findings inverted
v1's order: the `no_invoice_number` work is nearly free (Lumen's selector already
exists and passes), and the pack over-claim is a live defect rather than the
measurement exercise v1 assumed. The shared-signal module is deferred until it has a
genuine second caller. The plan ends with a whole-corpus sweep — the defense that
actually caught the 2026-08-06 phantom fix, and the one v1 dropped.

**Tech Stack:** Python 3.12+, pytest, ruff. No new dependencies.

## Global Constraints

- **Never read the filename** (`s3_classify.py:11`).
- **Real-document tests use `assert os.path.exists(p), p`, never `skipif`.** A wrong
  path or a broken checkout must fail loudly. `RESUME.md:18` records that all 12
  existing skips are accounted for; no task may add an unexplained one.
- **Resolve corpus paths from the test file**, not the CWD:
  `pathlib.Path(__file__).resolve().parents[2] / "docs" / …`.
- **Confirm every corpus filename against the gold JSON's `source_file`** before
  writing it into a test. v1 got two wrong and would have skipped silently.
- **Printed fields only.** No task reintroduces an inferred field.
- **No gold label may be changed.** Adding the new `forbidden_tags` key is not a label
  change; editing `tags`, `fields` or `expected_routing` is, and is out of scope.
- **`mypy` does not cover `src/docintel/packs` or `scorecard.py`** (`pyproject.toml:35-42`).
  Do not claim type coverage for work in those files.
- **A task that changes a pack-wide rule must update the pack spec row** it changes,
  following `a5de1fd`'s pattern of touching only the named row.
- Per-task verification:
  `python3 -m pytest -q && ruff check src tests && python3 docs/corpus/validate_gold.py`
- Baseline, verified 2026-08-07: **1720 tests**, `replay-gold` **1/11 green**,
  255/310 assertions.

  | doc | score | | doc | score |
  |---|---|---|---|---|
  | centracom | 28/31 | | complete-beverage | 21/27 |
  | comcast | 28/31 | | edco-077087 | 21/28 |
  | lumen | 28/31 | | edco-819387 | 20/26 |
  | windstream | 26/29 | | federal-recycling | 19/25 |
  | dtss | 21/21 PASS | | upak | 19/28 |
  | | | | veritiv | 24/33 |

## Scope

**In:** claim precision, the two false-positive tags, the two missing tags, the
shared-signal module, and a whole-corpus sweep.

**Deferred, with reasons** (unchanged from v1, plus one the reviewers named):

- **The (0.90, 0.99) confidence dead band.** `RESUME.md` calls it "the thing to fix
  next in the gate"; it causes 4 of EDCO's 9 residual review flags and affects two
  assertions per document. **After this plan, this outranks further classification
  work** — say so in the next planning round rather than writing Classification
  Correctness III.
- **EDCO's missing `line_items` selector** — the most credible route to a second green
  document.
- Evidence-bearing signals / calibrated confidence; classification escalation;
  review-outcome feedback loop.

---

### Task 0: Capture the pre-plan baseline

The sweep in Task 9 is worthless without a before-picture, and the OCR run is slow
enough that it must not sit on the critical path.

- [ ] **Step 1: Run the full batch and store it**

```bash
find all-docs/second-samples -name "*.pdf" -print0 \
  | xargs -0 python3 -m docintel.cli process --vision fake --json \
  > var/baseline-111-preplan.json
```

- [ ] **Step 2: Record the counts that Task 9 will diff**

Tag counts, `doc_type` counts, `unclaimed_document` count, per-pack claim counts, and
`review_flag` totals. Commit the JSON under `var/` and the summary table into this
plan's ledger.

- [ ] **Step 3: Commit**

```bash
git add var/baseline-111-preplan.json
git commit -m "chore: capture pre-plan 111-document baseline for the Task 9 sweep"
```

---

### Task 1: Claim precision — measure, then fix

**The top-priority defect in this plan.** Verified against the real `resolve_pack`:
3 of 6 out-of-domain documents are claimed by the wrong pack.

```
different_company_same_zip   → CLAIMED by northstar
ship_to_only_at_marker_zip   → CLAIMED by northstar         (ZIP only in a SHIP-TO block)
managed_client_as_line_item  → CLAIMED by digitaldirection  (client named in a line item)
```

The codebase's own ranking, from `registry.py:117`: an unclaimed document is emitted
and flagged for a human, while a wrongly-claimed one runs a whole rulebook of another
organization's assumptions. This outranks every tag in this plan.

**Files:**
- Create: `tests/packs/test_claim_precision.py` (fixtures defined **inline** — this
  repo has zero cross-test imports and `from tests.packs...` does not resolve)
- Modify: `src/docintel/packs/northstar/__init__.py` (`BILL_TO_MARKERS` / `claims`)
- Modify: `src/docintel/packs/digitaldirection/__init__.py` (`claims`)
- Modify: `docs/packs/northstar-recycling.md`, `docs/packs/digital-direction.md` (claim rows)

**Interfaces:** no new public names; `claims(ctx) -> bool` keeps its signature.

- [ ] **Step 1: Write the failing test, with the 3 known failures stated up front**

Inline `OUT_OF_DOMAIN` in the test module. Six fixtures minimum, each with a comment
naming the over-claim it probes; do not pad with documents no marker could ever claim.
Assert `resolve_pack(ctx, load_packs()) is None` for every one.

- [ ] **Step 2: Run it — expect exactly 3 failures**

Run: `python3 -m pytest tests/packs/test_claim_precision.py -v`
Expected: the three named above FAIL; the other three PASS. If the count differs, stop
and re-measure before changing any marker.

- [ ] **Step 3: Establish what the ZIP marker must still rescue**

`"ma 01028"` exists because 4 real EDCO second-samples print a typo'd company name.
Before tightening, measure what those 4 documents actually print:

```bash
python3 - <<'PY'
from docintel.extract import normalize
from docintel.packs.registry import normalize_name
import glob
for f in sorted(glob.glob('all-docs/second-samples/edco/*.pdf')):
    pages, meta, _ = normalize.load_document(f)
    n = normalize_name("\n".join(p.text for p in pages))
    print(f.split('/')[-1][:28], '| northst:', 'northst' in n, '| ma 01028:', 'ma 01028' in n)
PY
```

Record the result in the ledger. **The tightening must be derived from this
measurement, not chosen first and justified after.**

- [ ] **Step 4: Tighten the Northstar guard**

The likely shape, to be confirmed by Step 3: the bare ZIP alone no longer claims —
it must co-occur with a token shared by every real rendering of the company name
(`NORTHSTART`, `NORTHSTRAY`, `NORTHSTAR RECY` all share the prefix `northst`). Write
the measured evidence into the marker's comment, naming the four files.

If Step 3 shows any of the 4 documents lacks the shared token, that shape is wrong —
report and stop rather than forcing a fit.

- [ ] **Step 5: Tighten the Digital Direction guard**

The managed-client half of `claims` is documented as "a secondary signal, not the
claim" (`digitaldirection/__init__.py`), yet it currently claims on a bare substring
anywhere in the primary text. Before choosing a fix, measure whether any real document
needs it at all:

```bash
# How many of the 111 are claimed by DD via the managed-client fallback ALONE
# (i.e. aliases.canonical(text) is None but a client name appears)?
```

If the answer is zero, the honest fix is to require the client name on a short line
in a bill-to context rather than anywhere in the text. Record the measurement.

- [ ] **Step 6: Re-run the precision suite and the gold corpus**

Run: `python3 -m pytest tests/packs/test_claim_precision.py -v && python3 -m docintel.cli replay-gold`
Expected: all 6 precision cases pass; **`replay-gold` unchanged at 1/11 with every
per-document score identical**. A claim change that moves a gold score means a real
document lost its pack — stop and investigate.

- [ ] **Step 7: Re-run the 111-document batch and diff claims**

Compare `unclaimed_document` and per-pack claim counts against `var/baseline-111-preplan.json`.
**Expected: zero change.** Any real document that becomes unclaimed must be opened and
read before proceeding — that is a false negative traded for a false positive, and it
needs its own decision.

- [ ] **Step 8: Update both pack spec claim rows, then commit**

---

### Task 2: `no_invoice_number` — the retag hook only

Lumen's selector **already exists** (`personas/lumen.json`) and already passes gold
(`fields.invoice_number` = `752233001`, `derived.identity_basis` = `invoice_number`).
`invoice_number` is already registered at `fields.py:29`. Only the hook is missing
(`grep -rn no_invoice_number src/` → 0 hits). This is 3 of the 4 failing gold tag
assertions for roughly an hour of work.

**Files:**
- Modify: `src/docintel/packs/digitaldirection/ladder.py` (add `retag_missing_invoice_number`)
- Modify: `src/docintel/packs/digitaldirection/hooks.py` (register)
- Test: `tests/packs/test_digitaldirection_no_invoice_number.py` (create)

- [ ] **Step 1: Write the failing tests — including the wiring test**

Four unit tests (missing → tagged; present → not tagged; empty string → tagged;
idempotent) **plus** a registration test. The wiring test is not optional:
`test_digitaldirection_ladder.py:147` is `test_the_refinement_is_actually_wired_into_the_pipeline`,
written because `retag_prior_balance` "was correct code the whole time it was
unregistered." This is the same shape at the same socket.

- [ ] **Step 2: Run — expect ImportError**
- [ ] **Step 3: Implement `retag_missing_invoice_number`**

Mirror `retag_prior_balance`'s docstring standard: why this socket and not
`afterExtraction` (a value op on `invoice_number` must be seen), and why empty-string
counts as missing.

**Do not repeat v1's ordering claim.** `references.collect` never reads `ctx.tags`
(verified) — there is no dependency on registering before it, and fossilizing a false
rationale is worse than none.

- [ ] **Step 4: Run — expect PASS (5)**
- [ ] **Step 5: Verify against gold**

Expected: comcast 28/31 → **29/31**, windstream 26/29 → **27/29**,
centracom **28/31 unchanged** (its `tags` assertion also needs `past_due`, which is
out of this plan). Lumen must NOT gain the tag.

- [ ] **Step 6: Update `docs/packs/digital-direction.md:58`, then commit**

---

### Task 3: `count_printed_names` counts brands, not alias phrases

Comcast is tagged `multi_brand_sender` against gold because `comcast` is a substring
of `comcast business`.

**v1's outermost-only rule is wrong** and must not be implemented: `LITERAL_ALIASES`
also contains the composite `"kinetic business by windstream"`, which swallows both
`kinetic business` and `windstream`, returning **1** for a genuinely two-brand page.
The real Windstream bill escapes only because its text layer breaks the brand across
a line — an accident of one scan, not a property of the rule.

**Files:**
- Modify: `src/docintel/packs/digitaldirection/aliases.py:133-145`
- Test: `tests/packs/test_count_printed_names.py` (create)
- Modify: `docs/packs/digital-direction.md:57`

- [ ] **Step 1: Decide the rule from the alias table, not from one document**

Two candidate rules, both to be measured against all four real PDFs **and** against a
synthetic contiguous `"KINETIC BUSINESS BY WINDSTREAM"`:

1. Count maximal **non-overlapping character spans** in the normalized text.
2. Exclude composite aliases whose constituents are themselves aliases from the
   counting set (they exist for `canonical()`'s exact-lookup rung, not for counting),
   then apply outermost-only.

Rule 2 is simpler and directly addresses why the composite exists. Confirm it gives
Comcast 1, Lumen 3, Windstream 2, Centracom 1 on the real documents **and** Windstream 2
on the contiguous synthetic — that last case is the one v1 got wrong.

- [ ] **Step 2: Write the failing tests, including the contiguous-composite case**
- [ ] **Step 3: Run — expect the Comcast cases and the composite case to fail**
- [ ] **Step 4: Implement, documenting why canonical-counting is NOT the fix** (Lumen's
  three printed names share one canonical)
- [ ] **Step 5: Run — expect PASS**
- [ ] **Step 6: `replay-gold` — Lumen must keep `multi_brand_sender`**; Comcast's extra
  tag disappears but is invisible until Task 4. Note that in the commit message.
- [ ] **Step 7: Update the spec row, then commit**

---

### Task 4: `forbidden_tags` — make false-positive tags visible

Deliberately **after** Tasks 1-3, reversing v1: those fixes are verifiable by direct
measurement, and this task is the more delicate one. It exists so the fixes cannot
silently regress.

**The v1 design is unusable on two counts** (see REVIEW B1, B2) and must be rewritten:

1. The API is `assertions_for(gold) -> list[Assertion]` — one argument, no `add()`
   helper, and `Assertion` has no `.passed`. Tests must call
   `matches(a.expected, a.getter(record), a.kind)` themselves, and the gold fixture
   must carry `doc_type`, `text_source`, `page_roles`, `page_count` and
   `expected_routing` or `assertions_for` raises `KeyError`.
2. A bare `disjoint` assertion **passes on an empty record**, breaking GUARDRAIL 3
   (`test_scorecard_coverage.py:563`). Do **not** solve this with a
   `VACUOUS_BY_CONSTRUCTION` entry — standing rule 9 exists to stop exactly this.
   Make the assertion non-vacuous: it must require that the record produced tags at
   all AND that none is forbidden, e.g. expected `(True, [])` against
   `(bool(r.get("tags")), sorted(set(r.get("tags", [])) & set(forbidden)))`. A
   do-nothing pipeline then fails it.

**Files:**
- Modify: `src/docintel/scorecard.py` (new assertion + `matches` dispatch + the stale
  `kind` comment at line 28 and the `matches` docstring at 32-49)
- Modify: `docs/corpus/gold/digitaldirection-comcast-…json`, `…windstream-…json`
- Modify: `docs/corpus/validate_gold.py` (self-contradiction check, placed **before**
  the early `return` at line 114)
- Modify: `docs/corpus/README.md:47` (the `classification` schema block)
- Test: `tests/test_scorecard_forbidden_tags.py` (create)

- [ ] **Step 1: Read `scorecard.py:24-49, 560-620, 730-745` before writing anything**
- [ ] **Step 2-6: TDD the assertion, including a test that it FAILS on an empty record**
- [ ] **Step 7: Add the two verified entries with evidence notes**
- [ ] **Step 8: Confirm GUARDRAIL 3 is green**

Run: `python3 -m pytest tests/test_scorecard_coverage.py -v`

- [ ] **Step 9: Confirm the Task 3 fix is now visible**

Comcast gains an assertion and passes it: 29/31 → **30/32**. Windstream gains one and
**fails** it until Task 6: 27/29 → 27/30.

- [ ] **Step 10: Commit**

---

### Task 5: `packs/signals.py` + Northstar migration (merged)

Merged because v1's Task 3 was a pure refactor with no user-visible change — not worth
its own review cycle — and because the module has one genuine caller until Task 6.

**Correct v1's motivating claim:** Digital Direction has **no `has_tax` tag at all**.
The real duplication is one copied function (`_short_line_has`, 6 vs 8 words).
`title_near_top` and `label_with_corroborating_value` have a single caller pack until
Tasks 6 and 7. Say so in the module docstring rather than overselling it.

**Files:** create `src/docintel/packs/signals.py`, `tests/packs/test_signals.py`;
modify `src/docintel/packs/northstar/ladder.py`, `src/docintel/packs/registry.py`.

- [ ] **Step 1: Write `test_signals.py` — 12 tests plus the boundary pairs v1 omitted**

For **both** `title_near_top` and `short_label_line`: a match at `max_line_index - 1`
(passes) and at `max_line_index` (fails); a `max_words`-word line (passes) and a
`max_words + 1`-word line (fails). Without these, `max_line_index` can be changed to
anything in [6, 25] and every test still passes. Also cover **both** of
`title_near_top`'s constraints — v1's fixtures were all 2-3 words, so deleting its
length check left the module's own tests green.

- [ ] **Step 2-4: Implement, single-sourcing `primary_pages`**

`registry.primary_text` (`registry.py:182-197`) already implements the primary-page
set. Do not reimplement it with a docstring promising it "mirrors" the original —
that is the copy this module exists to delete. Put `primary_pages` in `signals.py` and
rewrite `registry.primary_text` as
`"\n".join(p.text for p in signals.primary_pages(ctx))` (registry → signals → core,
still acyclic; `packs/__init__.py` has no imports, so there is no cycle).

Type `line_text(line: list[Word]) -> str` and delete the `# type: ignore`.

- [ ] **Step 5: Migrate the Northstar call sites**

Preserve every page scope exactly, including `primary_only=False` on the past-due
banner and the aging corroboration. Keep each docstring's *evidence* and rewrite its
*mechanism* references — `northstar/ladder.py:131` and `:192` name `_short_line_has`,
which Task 5 deletes.

- [ ] **Step 6: Pin the deliberate widening — the test v1 lacked**

A two-page ctx: page 1 primary and ordinary, page 2 supporting with a bare `PAST DUE`
banner. Asserts `past_due` **is** tagged, docstring naming Federal Recycling's T&C
page. Without this, the single most-emphasized instruction in v1 had zero enforcement:
flipping `primary_only` leaves the suite green and `replay-gold` byte-identical.

- [ ] **Step 7: Prove byte-identical `replay-gold`**

```bash
python3 -m docintel.cli replay-gold --json > /tmp/after-task5.json
diff /tmp/before-task5.json /tmp/after-task5.json && echo IDENTICAL
```

**The gate is strict.** Any diff stops the task and is reported. It is never resolved
by loosening the gate or editing a test.

- [ ] **Step 8: Commit**

---

### Task 6: DD `past_due` — narrow scope, and keep it firing

**Files:** `src/docintel/packs/digitaldirection/ladder.py`,
`tests/packs/test_digitaldirection_past_due.py`, `docs/packs/digital-direction.md:56`.

- [ ] **Step 1: Write the tests — negative AND positive**

v1 had only negatives, so `return False` passed its whole suite and
`test_digitaldirection_ladder.py` has no `past_due` test at all. Required:

1. Real `Windstream_041069076` is **not** tagged (`assert os.path.exists`, no skipif).
2. The fragment really is on a supporting page (pins the premise; keep the
   `assert found` guard or the subset check passes vacuously).
3. **A standalone `PAST DUE` banner on a DD primary page IS tagged.**
4. **An aging header + non-zero bucket row on a primary page IS tagged**; header +
   all-zero row is not — mirroring `test_northstar_ladder.py:252-275`.

- [ ] **Step 2-4: Narrow to primary pages via `signals.short_label_line`**

**Delete v1's rationale for `_AGING_COLUMNS`.** It claimed `.*` could span pages in
`re.search(r"\b30 DAYS\b.*\b60 DAYS\b", everything)`. Verified false: without `re.S`,
`.` does not cross `\n`, and both `page.text` and `all_text` join with `\n`. If the
line-scoped form is kept, justify it as consistency with `short_label_line`, not as a
bug fix. Note that `_AGING` already contains `30 days\b.*\b60 days`, so the only real
delta is the word cutoff.

- [ ] **Step 5: State the consequence v1 hid**

After this task, `past_due` fires on **0 of 11** available DD documents (4 gold + 7
second-samples) — every telecom `past due` hit is supporting-page boilerplate, and
Centracom's is a 10-word primary prose line already rejected. The branch is correct
but has no real-document positive. Write that into the code comment and the ledger so
the next person does not read the silence as breakage.

- [ ] **Step 6: Windstream's `forbidden_tags` assertion flips to passing** — 27/30 → 28/30
- [ ] **Step 7: Update the spec row, then commit**

---

### Task 7: `foreign_currency` from a printed Canadian postal code

The signal survived adversarial review intact: **1/11 on gold** (U-PAK only) and
**zero false positives across all 111 second-samples** — 77 text-layer and 34 OCR,
including 27 handwriting-heavy scans. This was the claim expected to break.

**Files:** `src/docintel/packs/northstar/ladder.py`,
`tests/packs/test_northstar_foreign_currency.py`,
`docs/corpus/gold/northstar-dtss-6060.json` + `…veritiv…json` (forbidden entries),
`docs/packs/northstar-recycling.md:40`.

- [ ] **Step 1: Use the REAL filenames**

```
docs/CANADIAN WITHOUT NOTES U- PAK 4378107 (1).pdf         (positive)
docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf   (negative)
```

v1 named two files that do not exist and guarded them with `skipif`, so it would have
reported green having opened no PDF. Use `assert os.path.exists(p), p`.

- [ ] **Step 2-5: TDD the signal, primary-scoped**
- [ ] **Step 6: Use the machinery Task 4 shipped**

v1 wrote "no other document may gain `foreign_currency`" as an instruction to eyeball
`replay-gold`. Add `"forbidden_tags": ["foreign_currency"]` to the dtss and veritiv
gold files instead — one line each, and it converts a manual check into a failing
assertion.

- [ ] **Step 7: Resolve the spec conflict**

`northstar-recycling.md:40` defines `foreign_currency` as **`currency != USD`**. This
implements "a printed foreign address." That is a spec change, not a docstring aside —
update the row to say what is actually detected, and note the limitation (a EUR or GBP
invoice will not fire).

- [ ] **Step 8: upak 19/28 → 20/28. Commit.**

---

### Task 8: DD `credit_memo` rung checks for a title

Latent: **0 of 7** telecom second-samples print the wording. Fixed because a wrong
`doc_type` on this pack loads the wrong persona.

- [ ] **Step 1-5: TDD via `signals.title_near_top`**
- [ ] **Step 6: Do not borrow Northstar's evidence**

v1 copied `_MAX_CREDIT_MEMO_LINE_WORDS = 7` / `_MAX_CREDIT_MEMO_LINE_INDEX = 10` into
DD and justified them with "the same real-document evidence as
`northstar.ladder._credit_memo_title_present`" — i.e. Complete Beverage, a *Northstar*
vendor. The constants are unvalidated on this pack. Say so in the docstring rather
than importing another pack's fitted numbers under a borrowed justification.

Also consider the sibling defect v1 left unnamed: `disconnect_notice` (`ladder.py:67`)
is the same bare-search shape one rung below. It has a real second guard (absence of a
current-charges block), so it is weaker — but if this task is worth doing on zero
evidence, say explicitly why that one is not.

- [ ] **Step 7: Add a `forbidden_tags: ["credit_memo"]`-shaped guard** where a DD gold
  document can carry one, making the latent defect non-latent.
- [ ] **Step 8: Update the spec row, then commit**

---

### Task 9: Whole-corpus regression sweep

**Non-negotiable, and the task v1 dropped.** The 2026-08-06 plan's equivalent is what
caught the phantom fix after all ten of its tasks reported done.

- [ ] **Step 1: Re-run all 111 second-samples**
- [ ] **Step 2: Diff every count against `var/baseline-111-preplan.json`**

`unclaimed_document`, per-pack claims, every tag, every `doc_type`, `review_flag`.

- [ ] **Step 3: Explain every delta, by document**

An unexplained delta is a defect, not noise. Open the PDF.

- [ ] **Step 4: Verify each fix on a real document end-to-end**, not by count. The
  2026-08-06 `credit_memo` defect hid *because the count moved the way a correct fix
  would move it.*
- [ ] **Step 5: Update `docs/classification-audit-2026-08-06.md` with the new numbers**
- [ ] **Step 6: Record in the ledger that the confidence dead band and EDCO's
  `line_items` selector now outrank further classification work**
- [ ] **Step 7: Commit**

---

## Expected end state

Corrected from v1, whose Centracom row was arithmetically impossible.

| | baseline | after Tasks 0-9 |
|---|---|---|
| tests | 1720 | ~1775 |
| `replay-gold` green | 1/11 | 1/11 |
| centracom | 28/31 | **28/31 (unchanged — needs `past_due`, out of scope)** |
| comcast | 28/31 | **30/32** |
| windstream | 26/29 | **28/30** |
| upak | 19/28 | **20/28** |
| verified false-positive tags | 2, invisible | **0, and visible** |
| out-of-domain documents wrongly claimed | **3 of 6** | **0 of 6** |
| pack-wide changes proven on 111 docs | no | **yes** |

**No document flips to green,** and the plan must not be judged on that. Every
remaining failure on these documents is address, reference, line-item or
confidence-threshold work — separate subsystems, separately tracked.

## Ledger

| task | status | measured result |
|---|---|---|
| 0 | | |
| 1 | | |
| 2 | | |
| 3 | | |
| 4 | | |
| 5 | | |
| 6 | | |
| 7 | | |
| 8 | | |
| 9 | | |
