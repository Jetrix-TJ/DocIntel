# Document Intelligence POC — Status Summary

**As of 2026-07-29** · branch `dev` · all figures produced by running the code, not read from documentation

> **Update, this revision — two of the five challenges are closed.**
>
> * **§4**, incomplete extraction invisible to routing: **fixed**, and re-verified
>   by the experiment that found it.
> * **§5.1**, rules keyed to sample values: **fixed**. All 19 literal rules are
>   gone and grammar rule **V14** now refuses them at write time.
>
> The headline barely moved (201 → 202 of 263) and that is the point: the work
> replaced passes that only worked on our own samples with passes that read the
> page. **The defensible figure rose from 63.5% to 71.1%** (§3).

---

## 1. What it does

Reads vendor invoices and telecom bills as PDFs and emits one structured record per
document — vendor, invoice number, dates, amounts, line items, remittance details —
then routes each document to a processing lane (auto-approve, review, or reject)
based on how confident it is.

The extraction logic is **configuration, not code**: each vendor gets a small JSON
rule file describing where on the page to look and what shape each value has, and a
single generic engine interprets those files. Adding a vendor means adding a JSON
file. **No AI model runs in the extraction path.**

---

## 2. What is built

| Area | Status |
|---|---|
| 8-stage pipeline, intake → emit | Complete. Every intaken document emits exactly one record, enforced under injected failures |
| PDF text extraction | Complete (pdfplumber, word-level coordinates) |
| OCR fallback for scanned documents | Complete and automatic (Tesseract); 2 of 10 sample documents need it |
| Document classification and vendor identification | Complete; 4 document types observed |
| Per-vendor rule engine | Complete — 10 vendor rule sets, 119 selectors, validated by 14 static rules |
| Table / line-item extraction | Complete; correct row counts on 4 of the 5 documents that have tables |
| Confidence scoring and lane routing | Complete. Routes on two dimensions — per-field confidence and extraction completeness (§4) |
| Output contract validation | Complete; 23 required keys, type- and range-checked |
| Vision/LLM fallback | Built, but unreachable in practice and **not currently needed** |

**Engineering quality:** 1,476 automated tests passing, 12 deliberately skipped
with recorded reasons. Linting clean. 10 "guardrail" test suites exist specifically
to stop known classes of silent failure recurring.

Two honest gaps: type checking covers 26 of 74 source files (the pipeline and
vendor packs are unchecked), and duplicate detection is present in the output
contract but never populated.

---

## 3. Accuracy

Measured against 10 hand-labelled documents with 263 individual assertions.

| Measure | Result |
|---|---|
| **Field-level accuracy** | **202 / 263 = 76.8%** |
| **Documents fully correct** | **1 / 10 = 10%** |

**Both are true and they are not in conflict.** A document counts as "fully
correct" only if *every* assertion on it passes, so a document at 30/31 still reads
as a failure. Distance from fully-correct, per document: `0, 3, 4, 4, 4, 5, 7, 9,
13, 13` — **six of ten are within five assertions.**

### The number to quote internally: 71.1%

Of the 202 passing assertions, 15 are not evidence that the system can read an
unseen document:

- **15** pass because the expected answer is "no review needed", which an empty
  record also satisfies. `False` is both the gold expectation on most documents
  and a `JobContext` default, so the assertion does not discriminate.

**Excluding those: 187 / 263 = 71.1%.**

**This is the figure that moved, and it is the one that matters.** It was 63.5%.
The previous deduction of **19 assertions that passed because the rule contained
the answer is now zero** — those rules no longer exist (§5.1), and V14 prevents
their return. The headline barely changed (201 → 202) because the work traded
sample-fitted passes for real ones almost one-for-one; the defensible figure rose
7.6 points because the passes are now earned.

Two further cautions:

- **Do not compare 76.8% against earlier figures.** The measurement scope was
  deliberately narrowed earlier in the project, so part of the rise came from
  measuring less. Compare it only to itself from here.
- **The one fully-correct document is also the least-measured one** — 19
  assertions against 31 for the largest. It is green partly because less is asked
  of it.

---

## 4. The main risk: incomplete extraction — **now closed**

This was the finding that mattered most for production. It was proven by
experiment, and it has since been fixed and re-proven by the same experiment.

We deleted 14 of one vendor's 16 extraction rules and re-ran the document:

| | Normal | 2 of 16 rules left (before) | 2 of 16 rules left (**after**) |
|---|---|---|---|
| Fields extracted | 14 | **2** | 2 |
| The pack's required bill-to field | populated | **empty** | empty |
| Lane assigned | `high` | **`high` (auto-approve)** | **`review`** |
| Review flag | not raised | **not raised** | **raised** |
| Signal on the record | none | **none** | **`extraction_coverage.complete: false`** |

The cause was structural: confidence was keyed by what was *found*, not by what was
*declared*. `match_quality` is only recorded when a value is stored, the scorer
iterated that map, and the gate iterated the scorer's output — so the set of fields
that could lower a lane was a subset of the fields that had already succeeded. A
miss was not a low score; it was an absence, and absence had no representation.

**The fix adds completeness as a second routing dimension** rather than faking a
confidence score for a field that was never read. `core/coverage.py` measures what
the persona declared against what survived, and Stage 7 routes on it:

- a **required field that produced nothing** → `review` lane, review flag;
- **most declared selectors producing nothing** → `low` lane + regen flag, because
  a persona that no longer matches its template needs rewriting, not re-keying;
- the record carries `extraction_coverage` — counts plus the *names* of the missing
  fields, so downstream never has to parse prose to learn what was lost.

Two mechanisms are needed and neither substitutes for the other. A selector's
`required` flag catches *declared and empty* — the hardcoded-literal case in §5.1.
The pack's `required_fields` / `required_any_of` contract catches *never declared at
all*, which is what the rule-deletion experiment actually produces: delete the
selector and there is nothing left to be required.

Ordinary layout drift at a known vendor — a redesigned invoice template — produces
exactly the shape this now catches.

**Cost on the current corpus: zero.** No document changed lane and the scorecard was
unchanged at 201/263 when this landed. That is not a weak result, it is the expected one: the ten
personas were authored against these ten documents, so all ten are already complete.
The defence is entirely for documents we have never seen — which is also why it
cannot be credited as an accuracy gain.

Still open, and unrelated to the above: confidence does not track correctness. The highest confidence band (0.99)
is **89%** accurate while the band below it (0.90) is **93%** — the signal is
inverted where it matters. Eight values are wrong at maximum confidence, including
one payable amount wrong by **$6,621.41**. Any auto-approval threshold set below
1.0 would pass all eight.

---

## 5. Challenges

1. ~~**Rules are keyed to sample values.**~~ **Fixed.** 19 of 118 field rules were a
   literal restatement of the expected answer (24 counting vendor-specific
   *prefixes*). **All are gone, and the habit is now unrepresentable:** grammar
   rule **V14** rejects a pattern that captures fixed text on a whole-page region
   with no anchor, so such a rule can no longer reach the repo. The pre-existing
   debt list that tracked them is empty and can only shrink.

   How each was cleared, because the answer differed by field:

   | Situation | Fix |
   |---|---|
   | a printed label existed | anchor on it — `Make checks payable to`, `payable to`, `Name` |
   | a shape described the field | `(ATTN[ :][A-Z0-9 .,&'-]{2,40})` reads *any* attention line |
   | the print was unreadable | the pack's table supplies it (two logos are images; one text layer breaks the brand mid-word) |
   | none applied | the rule was **deleted** and the field left empty for §4 to report |

   For the telecom client specifically, the client list moved out of the rules and
   into the pack as a **roster**: one table serves all four carriers and every
   billing period, onboarding a client is a config change rather than four rule
   rewrites, and an unrostered client yields an empty required field that routes to
   `review` instead of putting a wrong party on a payment. `bill_to_name` is now a
   *required* field for that pack, which is what makes that escalation happen.

   Still true, and only a second invoice per vendor can settle it (§7): a rule can
   anchor on a label that exists on the one document we have. V14 removes the worst
   form of sample-fitting, not all of it.

2. ~~**No signal when extraction is incomplete.**~~ **Fixed** — see §4.

3. **Confidence is effectively one bit.** Only six distinct confidence values occur
   across the whole sample, and on **every one of the ten documents only two** —
   eight of them the same pair, 0.90 and 0.99. 39 of 74 configured thresholds can
   never fire. Three documents are mis-routed as a direct result.

4. **Unfinished rule authoring is the largest single gap.** Of 62 failing
   assertions, **33 are fields with no rule written at all** and 14 are rules that
   capture the wrong text. Concentrated: two field names (`bill_to_address`,
   `remit_address`) account for **14 of those 47** — 9 of them never written at all.

5. **One geometry setting has no safety margin.** The threshold deciding whether
   two pieces of text are on the same line is 3.0 points; four of eight
   text-based documents have their tightest line gap between 3.02 and 3.13 points.
   A slightly tighter document would merge two lines and corrupt everything derived
   from that page.

---

## 6. Where the remaining accuracy is, and what it needs

We checked every failing field against the text the pipeline already extracts:
**46 of 47 are already present on the page.** This is not a capability gap — the
rules to read them have not been written. Clearing all 47 would reach
**248/263 (94.3%)**, or **247 (93.9%)** if the one value with no text behind it
stays unreachable. Passing 250 would additionally require some of the 15 failures
that are not field reads — lanes, tags and line-item counts.

**A vision/AI model is needed for zero of the current failures.** Verified by
running: no model call occurs anywhere in the 10-document run, and every failing
value is deterministically reachable. OCR, by contrast, is already essential — two
documents contain no extractable text at all.

Recommended order:

| Priority | Action | Why |
|---|--:|---|
| 1 | **Obtain a second invoice per vendor** (different billing period; for the telecom client, different end customers) | Not an engineering task. Every generalisation risk above is currently *unmeasurable* because we have one document per vendor. This makes the others verifiable. |
| ~~2~~ | ~~**Make missing fields visible to confidence and routing**~~ | **Done** (§4). Cost nothing on the current corpus, because the corpus is what the rules were fitted to — the benefit appears only on unseen documents. |
| 3 | **Write the missing rules**, addresses first | Largest accuracy gain (~47 assertions). Needs 1 in place first, or it will add more sample-fitted rules. Item 2 is now in place to catch it when they do not generalise. |
| 4 | **Fix the line-spacing threshold** | Removes the one setting with no margin. Requires a full re-baseline. |
| 5 | Re-enable the deferred arithmetic cross-checks | Independently required before one document can route correctly |

Deliberately **not** recommended: enabling the vision/LLM path. It buys nothing
measurable today, adds a per-document running cost, and would need ongoing
trust-boundary maintenance. Revisit only if a document appears whose values are
genuinely absent from the text.

---

## 7. What we need from the business

**One additional invoice per vendor, from a different billing period** — and for
the telecom-expense client, invoices addressed to *different end customers*.

This is the single highest-value input and costs no engineering time. Without it we
cannot distinguish a rule that works from a rule that merely matches the one
example we were given, and every accuracy figure in this report carries that
caveat.

---

## Confidence in these figures

Every number was produced by executing the code on the current commit, and the
central claims were independently re-derived rather than taken from project
documentation — which was found materially stale twice during this review and has
since been corrected. Known limitation: **no figure here measures performance on an
unseen sender**, because no such document exists in the sample. That is what
item 1 above is for.
