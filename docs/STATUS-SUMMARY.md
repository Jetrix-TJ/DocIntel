# Document Intelligence POC — Status Summary

**As of 2026-07-29** · branch `dev` @ `06b6d88` · all figures produced by running the code, not read from documentation

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
| Per-vendor rule engine | Complete — 10 vendor rule sets, 130 selectors, validated by 13 static rules |
| Table / line-item extraction | Complete; correct row counts on 4 of the 5 documents that have tables |
| Confidence scoring and lane routing | Complete but weak — see §4 |
| Output contract validation | Complete; 22 required keys, type- and range-checked |
| Vision/LLM fallback | Built, but unreachable in practice and **not currently needed** |

**Engineering quality:** 1,446 automated tests passing, 12 deliberately skipped
with recorded reasons. Linting clean. 8 "guardrail" test suites exist specifically
to stop known classes of silent failure recurring.

Two honest gaps: type checking covers 25 of 73 source files (the pipeline and
vendor packs are unchecked), and duplicate detection is present in the output
contract but never populated.

---

## 3. Accuracy

Measured against 10 hand-labelled documents with 263 individual assertions.

| Measure | Result |
|---|---|
| **Field-level accuracy** | **201 / 263 = 76.4%** |
| **Documents fully correct** | **1 / 10 = 10%** |

**Both are true and they are not in conflict.** A document counts as "fully
correct" only if *every* assertion on it passes, so a document at 30/31 still reads
as a failure. Distance from fully-correct, per document: `0, 3, 4, 4, 4, 5, 7, 9,
13, 13` — **six of ten are within five assertions.**

### The number to quote internally: 63.9%

Of the 201 passing assertions, 33 are not evidence that the system can read an
unseen document:

- **18** pass because the rule contains the answer rather than reading it. They
  will keep passing on this sample forever and return nothing on a new invoice
  where that value differs.
- **15** pass because the expected answer is "no review needed", which an empty
  record also satisfies.

**Excluding both: 168 / 263 = 63.9%.** That is the defensible figure.

Two further cautions:

- **Do not compare 76.4% against earlier figures.** The measurement scope was
  deliberately narrowed earlier in the project, so part of the rise came from
  measuring less. Compare it only to itself from here.
- **The one fully-correct document is also the least-measured one** — 19
  assertions against 31 for the largest. It is green partly because less is asked
  of it.

---

## 4. The main risk: incomplete extraction is invisible

This is the finding that matters most for production, and it was proven by
experiment rather than inferred.

We deleted 13 of one vendor's 16 extraction rules and re-ran the document:

| | Normal | With 81% of rules removed |
|---|---|---|
| Fields extracted | 14 | **3** |
| The vendor's designated guard field | populated | **empty** |
| Lane assigned | `high` (auto-approve) | **`high` (auto-approve)** |
| Review flag | not raised | **not raised** |
| Warnings recorded | none | **none** |

**A document missing four-fifths of its data was auto-approved with no signal of
any kind.** The cause is structural: only fields that produced a value are scored,
so a field that extracts nothing is invisible to confidence and therefore invisible
to routing.

This matters because ordinary layout drift at a known vendor — a redesigned
invoice template — produces exactly this shape. At thousands of documents it is
the dominant risk, and it is currently undetectable.

Related: confidence does not track correctness. The highest confidence band (0.99)
is **89%** accurate while the band below it (0.90) is **93%** — the signal is
inverted where it matters. Eight values are wrong at maximum confidence, including
one payable amount wrong by **$6,621.41**. Any auto-approval threshold set below
1.0 would pass all eight.

---

## 5. Challenges

1. **Rules are keyed to sample values.** 24 of 118 field rules (20%) restate the
   expected answer rather than describing where to find it. The worst cases are on
   a telecom-expense-management client whose invoices are addressed to *different
   end customers* — that field varies per document and is hardcoded on all four
   carriers, so an unseen customer yields an empty field and no warning.

2. **No signal when extraction is incomplete** — §4.

3. **Confidence is effectively one bit.** Only six distinct confidence values occur
   across the whole sample, and on 7 of 10 documents only two. 39 of 74 configured
   thresholds can never fire. Three documents are mis-routed as a direct result.

4. **Unfinished rule authoring is the largest single gap.** Of 62 failing
   assertions, **33 are fields with no rule written at all** and 14 are rules that
   capture the wrong text. Concentrated: two field names (`bill_to_address`,
   `remit_address`) account for 13 of them.

5. **One geometry setting has no safety margin.** The threshold deciding whether
   two pieces of text are on the same line is 3.0 points; four of eight
   text-based documents have their tightest line gap between 3.02 and 3.13 points.
   A slightly tighter document would merge two lines and corrupt everything derived
   from that page.

---

## 6. Where the remaining accuracy is, and what it needs

We checked every failing field against the text the pipeline already extracts:
**46 of 47 are already present on the page.** This is not a capability gap — the
rules to read them have not been written. Clearing them would reach roughly
**250/263 (95%)**.

**A vision/AI model is needed for zero of the current failures.** Verified by
running: no model call occurs anywhere in the 10-document run, and every failing
value is deterministically reachable. OCR, by contrast, is already essential — two
documents contain no extractable text at all.

Recommended order:

| Priority | Action | Why |
|---|--:|---|
| 1 | **Obtain a second invoice per vendor** (different billing period; for the telecom client, different end customers) | Not an engineering task. Every generalisation risk above is currently *unmeasurable* because we have one document per vendor. This makes the others verifiable. |
| 2 | **Make missing fields visible to confidence and routing** | Closes the §4 risk. Expect reported lane quality to look *worse* while real safety improves. |
| 3 | **Write the missing rules**, addresses first | Largest accuracy gain (~47 assertions). Needs 1 and 2 in place first, or it will add more sample-fitted rules. |
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
