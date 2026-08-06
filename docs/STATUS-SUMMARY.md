# Document Intelligence POC — Status Summary

**As of 2026-08-05** · branch `dev` · every figure below was produced by running
the code on this commit (`python3 -m pytest`, `ruff check`, `mypy`, and
`python3 -m docintel.cli replay-gold`, all re-executed while writing this
revision), not read from project documentation or from `.loop/scorecard.json`
(stale, do not trust it)

> **Update, this revision — six days of real engineering work, most of it closing
> exactly the risks the last revision flagged, plus the first real second-sample
> data has arrived and immediately paid for itself by finding seven new issues.**
>
> * **§4.5** (geometry with no safety margin, including the "accidental passes"
>   bug), **§4.6** (OCR threshold calibrated on the wrong statistic), and both
>   **§4.7** items (gate's wrong reason, identity captured pre-hook) are **fixed
>   and committed** — verified below, not just claimed.
> * **§4.1 (wrong-inbox guard) is closed structurally.** The one reproduced
>   failure mode — a routing-line mention getting promoted to `bill_to_name` — is
>   fixed, and the five personas that declared **zero `bill_to_name` selectors**
>   (`comcast`, `windstream`, `edco`, `upak`, `veritiv`) now all declare one, so
>   `bill_to_mismatch` can structurally fire for every persona in both packs —
>   verified firing on real Windstream and real Edco second samples. The
>   whole-branch review found two selector-*quality* defects behind that: U-Pak's
>   (3 of 12 real samples) is **fixed**, via a one-key grammar extension
>   (`scope: "block"`); Edco's (1 of 28) is an **accepted tradeoff**, documented
>   rather than fixed. Both fail safe. See §4.1.
> * **The business delivered second-period samples**: 111 real documents across 7
>   of 10 vendors, in `all-docs/second-samples/`. This is the #1 ask from the
>   previous revision. Running a sample of them (not yet formal, no gold labels),
>   plus a follow-up blind persona-regeneration exercise, surfaced **seven
>   findings this revision, and every confirmed bug is now fixed**: six
>   hardcoded-pattern/template bugs (Veritiv ×2, Edco, U-Pak, and — the most
>   serious one — Windstream's near-total extraction collapse, root-caused as
>   two disjoint bill templates sharing one persona), plus one re-measured and
>   closed as not-a-bug (an Edco arithmetic anomaly). See §4.9. Exactly **one**
>   vendor (Edco) has been turned into a formal, gold-labelled, scored document
>   so far; a blind-authored DTSS persona scored 17/19 against the hand-tuned
>   one's 19/19 — see §4.9.
> * **Confidence miscalibration (§4.2/4.3) is still open.** The $6,621.41 U-Pak
>   payable-amount error from the last revision is **still unfixed**, still at
>   maximum confidence.
> * A local web UI (`docintel serve`) shipped — a review surface on the existing
>   pipeline, not a new extraction path. See §2.
> * **The defensible accuracy figure is 71.4% (was 71.5%) — flat, not a gain.** An
>   earlier draft of this section computed 76.5% by shrinking the assertion
>   denominator along with the numerator when excluding non-discriminating
>   assertions; that silently dropped 3 real routing failures from the count. That
>   was a genuine arithmetic error, caught and corrected while preparing this
>   revision — see §3.

---

## 1. What it does

Reads vendor invoices and telecom bills as PDFs and emits one structured record per
document — vendor, invoice number, dates, amounts, line items, remittance details —
then routes each document to a processing lane (auto-approve, review, or reject)
based on how confident it is.

The extraction logic is **configuration, not code**: each vendor gets a small JSON
rule file describing where on the page to look and what shape each value has, and a
single generic engine interprets those files. Adding a vendor means adding a JSON
file. **No AI model runs in the extraction path** — confirmed again this revision:
every scored run and the new web UI both wire up `FakeVision`, never a live model.

---

## 2. What is built

| Area | Status |
|---|---|
| 8-stage pipeline, intake → emit | Complete. Every intaken document emits exactly one record, enforced under injected failures |
| PDF text extraction | Complete (pdfplumber, word-level coordinates) |
| OCR fallback for scanned documents | Complete and automatic (Tesseract), decided per page; per-page threshold recalibrated this revision (§4.6, closed) |
| Document classification and vendor identification | Complete; 4 document types observed |
| Per-vendor rule engine | Complete — 10 vendor rule sets, validated by static rules (V13/V14 among them) |
| Table / line-item extraction | Complete; correct row counts on 4 of the 5 documents that have tables |
| Confidence scoring and lane routing | Complete. Routes on two dimensions — per-field confidence and extraction completeness. Confidence itself is miscalibrated (§4.2/4.3, still open) |
| Output contract validation | Complete; 23 required keys, type- and range-checked |
| Duplicate detection | Populated **within one run**, keyed on document identity. Cross-run detection still needs a persistent store that does not exist yet |
| **Local web UI (`docintel serve`)** — new this revision | Complete. Single-PDF upload, runs the same `Runner`/`build_pipeline` the CLI uses (no parallel extraction logic), shows per-field values with confidence, surfaces `confidence_modifiers` (e.g. `bill_to_mismatch`) and possible-duplicate warnings, client-side-only JSON export |
| Vision/LLM fallback | Built, but unreachable in practice and **not currently needed** |

**Engineering quality, re-verified fresh for this revision:** 1,615 automated
tests passing, 12 deliberately skipped with recorded reasons (all gated on
re-registering the deferred arithmetic checks — see §5). `ruff check src tests`
clean. `mypy` clean on its checked scope. Gold labels self-consistent
(`docs/corpus/validate_gold.py`, 11 documents). 10+ "guardrail" test suites exist
specifically to stop known classes of silent failure recurring.

One honest gap remains here: **type checking covers 28 of 78 source files** —
`core`, `grammar`, and the vision-adapter boundary are checked; the pipeline,
packs, and the new web UI are not.

---

## 3. Accuracy

Measured against **11** hand-labelled documents (was 10 — Edco's second sample was
added this revision, see §4.9/§6) with **287** individual assertions (was 263).

| Measure | Result |
|---|---|
| **Field-level accuracy** | **221 / 287 = 77.0%** |
| **Documents fully correct** | **1 / 11 = 9.1%** |

**Both are true and they are not in conflict**, same as every prior revision: a
document counts as "fully correct" only if *every* assertion on it passes.
Distance from fully-correct, per document: `0, 3, 3, 3, 4, 6, 7, 7, 9, 11, 13` —
five of eleven are within four assertions, essentially the same shape as last
revision; the new Edco document (distance 7) slots into the existing spread
rather than changing it.

### The number to quote internally: 71.4%

Of the 287 assertions, 19 (was 15) are `review_flag`/`regen_flag` checks whose
expected value is `False` — satisfied by an empty record as readily as a correct
one, so a pass there is not evidence the system read the document. 16 of those 19
pass; **the other 3 fail**, and all 3 are real signal (a document that should have
auto-approved is instead being forced to review). **Excluding the 16
non-discriminating passes, and keeping the full 287-assertion denominator: 205 /
287 = 71.4%.**

An earlier draft of this section reported **76.5%**, arrived at by shrinking the
denominator to 268 (287 minus all 19) as well as the numerator — the same
operation applied to a passing assertion and a failing one, which are not the same
thing. That is a real arithmetic error, not a rounding choice: it silently removed
3 real routing failures from the count. It was caught and corrected before this
revision shipped. Recorded here so the same mistake isn't repeated next time this
section is updated — the rule going forward: **exclude non-discriminating passes
from the numerator only; the denominator never shrinks.**

**The "lucky pass" deduction from last revision is now retired, not just smaller.**
Last revision flagged that 2 of the 203 passes were accidental — a block-break
rule that collapsed onto a floor constant rather than measuring the page's own
line pitch. That rule has since been rewritten twice (`26a485d` for row groups,
`42e55ee` for label blocks) to use a genuine median pitch. The fix cost exactly
what was predicted: one assertion (Centracom's charges ladder, which has no honest
pitch-estimator answer — its own line gaps are 9.92/14.0/14.0/24.33, and 14.0 *is*
the correct pitch) came back red in the process and stayed red. There is no known
"lucky pass" left in the current 221.

**71.4% is essentially flat against last revision's 71.5%, not an improvement, and
that needs its own caveat.** The corpus changed size and composition in the same
window the code changed (10→11 documents, 263→287 assertions), and the new
document was deliberately chosen to stress-test recent fixes (§4.9) rather than
sampled the way the original ten were. Read "flat" as: real fixes landed this
week, and the number didn't move, because the harder new document introduced
about as much new failure surface (§4.4, §4.9) as the fixes closed. That is a
different — and more informative — story than either "we improved" or "we
regressed."

The other two cautions from every prior revision still hold: don't compare this
figure against pre-71.5% history (scope was narrowed earlier in the project), and
the one fully-correct document (DTSS) is still the least-measured one.

---

## 4. Outstanding risks

Ordered by what they cost if the system runs on documents it has not seen. **Six
of the nine items below are closed outright, including all of this revision's new
second-sample findings (§4.9); §4.1 closed on branch
`sdd/verified-findings-remediation`, with one accepted selector-quality tradeoff
(Edco, 1 of 28 real samples, fails safe) recorded under it.**

### 4.1 The wrong-inbox guard covering only half the corpus — **closed** (`fda882c`, then Tasks 6–8 of `sdd/verified-findings-remediation`)

Last revision: five personas with no `bill_to_name` selector (`comcast`,
`windstream`, `edco`, `upak`, `veritiv`) resolved bill-to by searching the whole
page for *any* roster name — a mention anywhere, not necessarily the party the
invoice was addressed to — and because the name came off the roster it could never
disagree with the roster, so `bill_to_mismatch` could never fire.

**What the fix closes:** `_roster_match` now requires a roster name to *head* a
line rather than merely appear anywhere on the page, reusing the head/mention
split `_candidate_lines` already computed one stage later instead of a second,
looser implementation of the same distinction. This closes the specific failure
mode last revision demonstrated — a routing-line or footer mention getting
promoted to `bill_to_name`. Verified properly: 203/263 assertions and 1/10
documents green, unchanged on the original ten, and **zero
field/tag/confidence/lane changes across 50 of the real second-sample documents**,
before vs after. This is the first fix in this project checked against
unseen-vendor-style data before landing, not just the sample it was built against.

**What closed the rest of it (branch `sdd/verified-findings-remediation`,
Tasks 6–8).** What `fda882c` left open was that those same five personas declared
**zero `bill_to_name` selectors**, so the value was always read off the roster,
never compared against a printed value, and `bill_to_mismatch` could not
structurally fire for them — reproduced live at the time on two real
second-sample Windstream invoices addressed to a different company, which raised
nothing, against **Lumen** in the same batch, which *does* have a selector and
correctly raised `bill_to_mismatch` on both of its cross-customer invoices.

All five now declare one: U-Pak (Task 6), Comcast (Task 7), Edco, Veritiv and
Windstream (Task 8). **The count of personas with no `bill_to_name` selector is
zero.** The closing evidence is that `bill_to_mismatch` now fires on real
documents that print a party the roster does not hold — measured in this
branch's final whole-branch review by replaying every real second sample:
`Windstream_216713099_08272025_BILL.pdf` reads its printed `GOLUB TOPs HQ` and
raises `bill_to_mismatch` (it read nothing at all before Task 8), and Edco raises
it on its own misprinted renderings (`NORTHSTRAY RECYCLING` on 823282AUG25 and
823282SEP25, `NORTHSTART RECYCLING` on 176024OCT25) — the printed rung
disagreeing with the roster, exactly as intended. Windstream's other four second
samples are OCR-sourced, miss the anchor, and fall through to the roster rung
unchanged. The roster rung remains behind every selector as the fallback when one
misses, so a selector miss is not a regression to the old behaviour.

The same whole-branch replay found **two selector-quality defects** no single
task's review had seen. Both fail safe; one is fixed and one is an accepted
tradeoff.

* **U-Pak, 3 of 12 real second samples — FIXED.** The `text_block` capture took
  the whole `Bill To` block rather than the party line when the block carried an
  `ATTN:`/email line above the name (invoices 4421470 and 4489932) or when OCR
  garbled it, which also cost those records their `bill_to_address`. Tightening
  the `pattern` alone made it *worse* — `near-anchor` reaches x=390 from `Bill`
  (x0=90) and takes in the service-location column at x0=355.07, so a per-line
  shape returned the service location on 6 of 12. The fix is a one-key grammar
  extension, `scope: "line" | "block"` (selector-grammar.md §1.1), which makes
  the column cut reachable by any pattern instead of only by `text_block`;
  U-Pak's selector is now `scope: "block"` plus an anchored party-name shape.
  Measured over all 12 samples plus the gold PDF: 10 clean captures, 3 clean
  misses, **zero wrong values**, `bill_to_address` present on all 12, and the
  one false `bill_to_mismatch` gone. A miss falls through to the roster rung, so
  it is never a loss.
* **Edco, 1 of 28 real second samples — accepted tradeoff, not fixed.** Invoice
  709223OCT25 prints the service-at descriptor above the party name instead of
  below it — the reverse of the other 27 — so the `same-row` selector reads
  `SYSCO FOODS-SAN DIEGO` and raises a false `bill_to_mismatch` on a
  correctly-addressed bill. Both orderings print four lines, so the party is at
  no fixed index, and a shape constraint is provably inert here (measured: the
  anchored shape returns byte-identical results to `text` on all 28 samples plus
  gold, `SYSCO FOODS-SAN DIEGO` included — it is a well-formed two-token party
  name in the correct position). Only a semantic check could separate them, and
  that is the roster rung this selector deliberately moves off. Accepted in
  exchange for the three *correct* misprint mismatches the selector raises;
  documented in `edco.json`'s own `notes`. It routes one correctly-addressed
  document to a human rather than auto-approving anything.

### 4.2 Confidence does not track correctness — **still open, narrower**

| Confidence | Accuracy on labelled fields (this revision, 11 docs) | Last revision (10 docs) |
|---|---|---|
| **0.99** | 74 / 79 = **93.7%** | 90.5% |
| 0.90 | 18 / 19 = **94.7%** | 93.3% |

The inversion is still there — 0.99 is still less accurate than 0.90 — but the gap
narrowed from 2.8 points to 1.0, and top-band accuracy itself rose 3.2 points.
**Five values are still wrong at maximum confidence** (was seven).

**The one payable-amount error is unchanged and independently reconfirmed this
revision.** U-Pak still extracts `please_pay = $8,119.44` where gold says
`$14,740.85` — the same $6,621.41 gap flagged last revision, at the same 0.99
confidence, still uncaught. Routing did move in one respect: `review_flag` is now
correctly `True` on this document (an arithmetic-mismatch check catches it
downstream), but the *lane* still lands `medium` rather than `review` — the same
mis-lane last revision named explicitly.

### 4.3 Confidence is effectively one bit — **status unchanged, not reverified in depth this revision**

Not re-measured field-by-field this revision beyond what §4.2 already shows (the
same handful of distinct confidence values doing almost all the work). Carried
forward as still true; due for a fresh count next revision.

### 4.4 Unfinished rule authoring — **still the largest single accuracy gap, and grew with the corpus**

Of 66 failing assertions (was 60), 48 are field/derived reads (was 45) — roughly 36
missing outright and 12 wrong text. The wrong-text share fell (was 16); the missing
share rose, mostly because the new Edco document exercises selectors that were
never written for that vendor (a payment-line field, a line-item ladder), not
because existing selectors got worse.

Still concentrated in addresses: `remit_address` (5), `bill_to_address` (5) and
`vendor_address` (3) account for 13 of the 48 — almost the same absolute count as
last revision's "13 of 45," despite the corpus growing.

### 4.5 The page geometry had no safety margin — **CLOSED** (`8d43340`, `f95483f`, `42e55ee`, `98822d1`)

Last revision: the same-line threshold was a flat 3.0pt against a measured
tightest gap of 3.02pt — 0.02pt of margin — and five other region constants were
absolute points hard-coded against an assumed 14pt line pitch that real documents
(measured 5.8–12.4pt) never actually have.

**Fix, landed as a sequence, not one patch:**
- `line_tolerance` and five region constants (`NEAR_ANCHOR_BELOW`, `TOTALS_BAND`,
  `LABEL_BLOCK_MAX`, `CELL_GAP`, `NEAR_ANCHOR_RIGHT`) now derive from the page's
  own measured median line pitch, each floored at its old absolute value so no
  existing region narrows.
- `MIN_TOLERANCE = 2.5` is the new explicit floor for line grouping — 0.52pt
  under the tightest genuine gap on file, replacing the old 3.0pt setting that had
  almost no margin.
- The block-break rule was rewritten to use a genuine median pitch (excluding the
  anchor's own leading gap, which was dragging DTSS's estimate wrong) instead of
  the shortcut that caused the accidental passes retired in §3.

Re-baselined at each step, exactly as predicted: 203/263 → 202/263 for the one
assertion with no honest pitch-estimator answer.

### 4.6 The per-page OCR threshold was calibrated on the wrong statistic — **CLOSED** (`798c614`, `2c28898`)

Last revision: the 50-character cutoff was calibrated on document-wide averages;
individual pages (Comcast page 2 at 58 characters, CentraCom page 10 at 60) sat
within single digits of flipping to OCR.

**Fix:** `NATIVE_CHAR_THRESHOLD` is now `29` — the midpoint between the measured
lowest-scanned-page and sparsest-native-page bands, not a round-number guess — and
OCR is decided per page. Both pages named above now clear the threshold by 29+
characters instead of single digits.

### 4.7 Two smaller items — **both CLOSED**

- **Gate's wrong reason on a forced review** (`b82ef02`): now surfaces a forced
  reason even when confidence has collapsed to low, instead of reporting
  "regenerate the persona" when the real cause was a wrong-inbox mismatch.
- **Document identity captured pre-hook** (`764657c`): the pipeline now commits
  the post-`beforeEmit` `document_identity`, not the pre-hook local, closing the
  desync risk before any pack actually exercised it.

### 4.8 Everything is still measured on close to one document per vendor — **materially changed, not resolved**

Last revision's #1 ask (§6) was one more invoice per vendor. **That material now
exists**: `all-docs/second-samples/` holds 111 real second-period documents across
7 of 10 vendors (`complete_beverage` 27, `dtss` 30, `edco` 28, `u_pak` 12,
`veritiv` 7, `windstream` 5, `lumen` 2). Three vendors — `centracom`, `comcast`,
`federal_recycling` — have **none yet**.

**Only one of those 111 has been turned into a formal, scored, gold-labelled
document**: `northstar-edco-819387`. A further 26 (roughly 4 per covered vendor)
were run informally through `docintel process` — extracted output eyeballed
against the value embedded in each filename, not scored against a real gold
label — which is how most of §4.9's findings surfaced. That informal check is a
real signal but a weaker one than a gold label: treat it as "strong lead," not
"confirmed," until each is formally scored.

**Net position:** the single biggest structural risk this report has carried
since its first revision — that the whole accuracy picture rests on one example
per vendor — is no longer *unaddressable*. It is now a backlog: material exists
for 7 of 10 vendors, one is formally done, six are informally spot-checked or
untouched, and three vendors have nothing yet.

### 4.9 New this revision: seven second-sample findings — all six confirmed bugs fixed, one closed as not-a-bug

Running real second-period invoices through the pipeline (informally, §4.8) is the
first time this project has tested its rules against documents they weren't
written against. A follow-up blind persona-regeneration exercise
(`docs/persona-regeneration/`, see box below) surfaced three more of the same
class. Seven findings total this revision, lettered/numbered inconsistently
across the two passes because the second pass's commit messages (`A`–`E`) were
written without cross-referencing the first pass's numbering (`1`–`5`) — Finding
`A` and Finding `2` are the same bug, cited here under both labels so a reader
searching either commit history or the earlier handoff doc can find it. **The
Windstream collapse (Finding 3) was still open as of the `2026-08-03` handoff
doc but was root-caused and fixed later the same day** (`1126cc5`/`11f1627`/
`c21bdac`, all committed 2026-08-03 21:10 or earlier) — the handoff doc itself
was never updated to say so, which is exactly the kind of drift this revision
exists to catch:

- **Finding 1 — Veritiv `invoice_number` was hardcoded to one prefix** (`715-`).
  3 of 4 new samples are `689-`-prefixed and came back `missing_required`.
  **Fixed and committed** (`dca2099`, generalized to any 3-digit prefix).
- **Finding 2 / A — Edco `vendor_account_number` was hardcoded to one prefix** —
  the literal string `25-3A`, which turned out to be the *calendar year*, not a
  vendor constant. All 4 new Edco invoices failed to extract this required
  field. **Fixed and committed** (`e95ce1d`) — worth flagging on its own: this
  rule would have started silently failing on every new Edco invoice going
  forward regardless of second samples, since the year rolls over. It was
  caught before that happened, not after.
- **Finding B — U-Pak `vendor_account_number` was a transcription of the one
  gold value**, including its coincidental leading and trailing "1"
  (`(1 -[0-9]{5} 1)`). Real second samples print 6 digits with inconsistent
  internal spacing that pattern never matched. **Fixed and committed**
  (`5921a17`) — swapped in the grammar's own named `account_number` pattern on
  the existing anchor/region instead of hand-fitting a wider regex; verified
  against all 12 real second samples plus the original gold document.
- **Finding C — Windstream `bill_to_address` was anchored to one of four roster
  clients by name** (`"CHOCTAW TRAVEL MART"`). A real sample billed to
  `"TOPS MARKETS LLC"` (not on the roster) came back with an empty address.
  **Fixed and committed** (`0f00953`) for the other three roster clients via
  `anchor_alts`; a non-roster client's address staying empty is left as the
  correct, honest outcome — onboarding a real new client is a business-data
  decision, not a mechanical one.
- **Finding E — Veritiv `vendor_account_number` required a leading zero**
  (`(0[0-9]{5})`), a verbatim copy of the one gold value (`068753`). A real
  sample prints `179502`, no leading zero, and the field silently dropped
  (`required: false`). **Fixed and committed** (`55db5c6`) — the leading-zero
  literal was doing no real narrowing work; the existing near-anchor selector
  already isolates the 6-digit run.
- **Finding 5 — Edco arithmetic anomaly, RE-MEASURED, NOT A BUG.** `total_printed`
  appeared not to equal `prior_balance + current_charges` on account `15570`'s
  two consecutive months. Reading the real PDFs (`ad56a97`) showed
  `total_printed` correctly reads the printed header total in every case; the
  *naive sum* only reconciles for accounts with no intervening `PAYMENT` line.
  Locked in with a test documenting the printed-fields-only behavior. No fix
  needed — closed as a measurement artifact, not carried forward.
- **Finding 3 / 4 — Windstream near-total extraction collapse on 2 of 4 new
  invoices — ROOT-CAUSED AND FIXED** (`1126cc5`, `11f1627`, `c21bdac`).
  `Windstream_205577168` and `Windstream_216713099` each extracted only 1 of
  ~12 fields, and that one field was garbled boilerplate, not real content.
  Root cause: Windstream prints **two structurally different bill templates**
  ("Kinetic" and "Enterprise") sharing only the brand name, and
  `windstream.json` only ever encoded Kinetic — every Enterprise selector
  missed outright, and the one field that populated matched the vendor's own
  name inside a sentence of portal boilerplate, returning a paragraph of prose
  as `remit_address`. Fixed by recognizing `TOTAL INVOICE AMOUNT` as a totals
  label (`1126cc5`), carrying the seven disjoint Enterprise label phrases as
  `anchor_alts` on the existing selectors — safe because the two templates'
  vocabularies never overlap (`11f1627`), and reading the printed Enterprise
  brand name instead of falling through to the hardcoded Kinetic display name
  (`c21bdac`). **Measured on the two broken documents: 1 populated field
  (garbage) → 8, every value cross-checked against the printed text and the
  scanline; `missing_required` fell from 8 fields to 1** (`bill_to_name`, the
  already-known N1 gap — see §4.1). All 263 original-corpus assertions
  produced byte-identical values throughout (Windstream's one gold document is
  a Kinetic bill, untouched by this fix) — verified live during this revision
  by checking out each of the three commits and re-running `replay-gold`, not
  just trusted from the commit messages. **One residual, left deliberately
  open:** on the OCR-sourced Enterprise sample, `remit_address` is still wrong
  — now OCR noise from the remittance stub rather than a prose paragraph.
  It's an optional field on a document already routed to `review`; suppressing
  it would need an OCR-confidence heuristic this codebase does not have.
  This was the report's one "reads as almost nothing" red flag; it no longer
  is one.

**Blind persona-regeneration exercise, new this revision** (`docs/persona-regeneration/`,
commit `a4eaa19`): a fresh session, with the corpus answers redacted, was given
one document and asked to author a `persona.json` from the grammar and pack
contract alone — a check on whether a rule reads the page or restates a known
answer. Only the DTSS run (`01-dtss`) completed: the blind-authored persona
scored **17/19** against DTSS's gold labels, against **19/19** for the
hand-tuned persona currently shipped. Findings B, C and E above came from
reading real second samples against the shipped personas during the same
session, not from a completed blind run on those vendors — the other 9
document folders are scaffolded but not yet run. Takeaway so far: a blind
agent can produce a mostly-working persona, but currently scores worse than
the hand-tuned one it's compared against — evidence the hand-tuned rules carry
some real, non-overfit signal, not proof either way about the other 9 vendors
until their sessions are run.

---

## 5. Where the remaining accuracy is, and what it needs

Clearing all 48 current field-level failures reaches an estimated **269/287
(93.7%)** — consistent with last revision's 94.3% on the smaller corpus, but not
independently re-verified per-field against page text this revision (last
revision's check, "every failing field is present on the page," was not rerun
against the 3 new failures the Edco document introduced — treat that specific
claim as carried forward, not reconfirmed).

**A vision/AI model is needed for zero of the current failures** — the web UI's
own wiring (`FakeVision`, no model call) is a second, independent confirmation of
this alongside the disabled-model-path run from the previous revision.

Recommended order, updated:

| Priority | Action | Why |
|--:|---|---|
| 1 | **Fix confidence calibration** (§4.2) | The item where the failure mode is real money misrouted despite correct-looking machinery — the U-Pak $6,621.41 error has now survived two revisions unfixed. |
| 2 | **Finish labelling the second-sample backlog** (§4.8): 6 vendors with material and no formal gold label yet, 3 vendors with no second sample at all | Converts informal spot-checks into permanent regression coverage. Edco is the template. |
| 3 | **Write the missing rules**, addresses first (§4.4) | Largest raw accuracy gain, ~48 assertions, growing as more vendors are added. Do this alongside item 2, on the *new* samples, so rules aren't fitted to single documents again. |
| 4 | Re-enable the deferred arithmetic cross-checks (12 tests currently skipped) | Independently required before some documents can route correctly; also unblocks 3 of the 12 skipped tests. |

**Dropped from this list, resolved this revision:** root-causing the Windstream
collapse was priority 1 last revision — closed, see §4.9. Writing a `bill_to_name`
selector for the five personas that lacked one was priority 1 in the revision
before this — closed by Tasks 6–8 and the `scope: "block"` fix, see §4.1.

Deliberately **not** recommended, unchanged from every prior revision: enabling
the vision/LLM path. Nothing measured this revision changes that conclusion.

---

## 6. What we need from the business

**The previous ask is half-answered.** 111 second-period documents arrived for 7
of 10 vendors — thank you, and it already found seven issues (§4.9), all now
resolved (six fixed, one closed as not-a-bug). What's still missing:

- **Second samples for the 3 vendors with none**: `centracom`, `comcast`,
  `federal_recycling`.
- If more periods exist for the 7 vendors already covered, useful too, but the
  priority now is breadth (the 3 missing vendors) over depth.

No further business input is required to make progress on §4.1 (the two open
bill-to selector defects), §4.2 (confidence calibration), or §4.4/§4.8
(rule authoring and labelling against material already delivered) — that is all
engineering work against material already in hand.

---

## Confidence in these figures

Every number here was produced by executing the code on the current commit while
preparing this revision: the full pytest suite, `ruff`, `mypy`, and
`docintel replay-gold` were all re-run fresh rather than trusted from a prior
report or from `.loop/scorecard.json` (stale — do not use it as a source). The §3
methodology error (76.5% vs. the correct 71.4%) was caught and corrected in the
course of that verification, which is itself the best evidence for re-deriving
these numbers each revision rather than editing the previous ones in place.

Known limitations, stated rather than silently carried as fact: **the "every
failing field is present on the page" claim in §5 was not rerun this revision**;
**confidence's one-bit character (§4.3)** was not independently remeasured;
**§4.9's findings come from an informal spot-check against filenames, not a gold
label**, so treat them as strong leads, not confirmed facts, until each is scored
formally; and **the blind persona-regeneration exercise (§4.9) has completed
only 1 of its 10 scaffolded document folders** (DTSS) — its 17/19-vs-19/19 result
is one data point, not a general claim about the other 9 vendors.
