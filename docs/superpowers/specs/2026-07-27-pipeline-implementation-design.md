# Design: runnable document-processing pipeline

**Date:** 2026-07-27
**Status:** approved (design), pending spec review
**Goal:** pass any PDF to a CLI and have it traverse all 8 stages of
[`architecture/pipeline-v2.md`](../../architecture/pipeline-v2.md), emitting a valid Stage 8 record.

## Inputs this design builds on

| Document | Role here |
|---|---|
| [`architecture/pipeline-v2.md`](../../architecture/pipeline-v2.md) | The spec. 8 stages, rule lifecycle, 8 hook sockets, Stage 8 contract. |
| [`corpus-analysis.md`](../../corpus-analysis.md) | 21 findings (F1–F20, F1b) + 13 spec deltas. The requirements. |
| [`architecture/selector-grammar.md`](../../architecture/selector-grammar.md) | The closed grammar: selectors, regions, patterns, ops, modifiers, V1–V13. |
| [`packs/*.md`](../../packs/) | Two pack specs: ladders, field sets, aliases, thresholds. |
| [`corpus/gold/`](../../corpus/gold/) | 10 labelled documents. **The objective function.** |
| [`corpus/validate_gold.py`](../../corpus/validate_gold.py) | Label self-consistency, 95 checks. |

## Scope decisions (agreed 2026-07-27)

| Decision | Choice | Consequence |
|---|---|---|
| Cost ladder | 5a + 5b real; 5c enqueues a real single-flight job, authoring deferred | All 8 stages genuinely execute; the expensive half is a clean seam |
| Model calls | Real Anthropic adapter behind a port + recorded cassettes; `--live` re-records | Works with no API key today; tests hermetic and free |
| Storage | SQLite for state (atomic CAS) + JSON export for rules (diffable) | Single-flight and promotion counters are correct; rule changes reviewable |
| Done bar | All 10 gold documents green end-to-end | Ties the build to evidence already gathered |

**Out of scope:** rule *authoring* by the agent (5c writes a job, not rules) · IMAP/Outlook intake ·
the downstream service (vendor resolution, matching, duplicate decision, review UI) · batch-PDF
splitting · retention/PII policy.

---

## 1. Architecture

Python 3.12, no web framework. Ports and adapters, because the spec's base/pack split already
demands it: the base owns all 8 stages and the hook machinery; packs supply taxonomy, fields and hook
functions. That is a plugin architecture, and the 8 hook sockets are middleware chains.

```
src/docintel/
  core/
    models.py      Document, Page, PageText, JobContext, ExtractedFields, DerivedFields
    contract.py    Stage 8 record construction + schema validation
    errors.py      TransientError / PermanentError / PackError / ValidationError
    confidence.py  modifier registry, multiplicative application, boost cap
    money.py       Decimal money parsing: -99.80, (249.84), "212.87 cr", "481.20 USD"
    dates.py       parse ladder, ISO normalization, loose passthrough
  pipeline/
    runner.py      orchestrator; owns the emit-always invariant
    hooks.py       8 sockets, chain dispatch, per-hook failure isolation
    stages/        s1_intake s2_filter s3_classify s4_persona
                   s5a_cached s5b_vision s5c_agent s6_capture s7_gate s8_emit
  grammar/
    schema.py      selector kinds as dataclasses
    validator.py   V1–V13
    executor.py    region resolve -> anchor find -> pattern apply -> score
    patterns.py    named pattern registry
    regions.py     region vocabulary resolution
    ops/           base.py derive.py crosscheck.py infer.py   (closed adjust-op enum)
  extract/
    pdf.py         pdfplumber: chars, words, tables, images, annots
    ocr.py         tesseract adapter
    normalize.py   -> PageText, identical shape for native and OCR
    annotations.py flattened-overlay detector (F3)
    pageroles.py   primary / supporting classification (F10)
    scanline.py    OCR-A line extraction + corroboration (F7)
  personas/
    store.py       SQLite: personas, layout variants, jobs, promotion counters
    export.py      JSON dump/load for review
  packs/
    registry.py    discovery + hook registration
    northstar/     ladder, fields, reference patterns, aliases, hooks, thresholds
    digitaldirection/
  adapters/
    vision/        port.py anthropic.py cassette.py fake.py
    intake/        port.py filesystem.py
  cli.py           process · replay-gold · show-record · personas · validate-grammar
```

Roughly 30 files, each with one purpose. One file per stage, so a stage fits in context whole.

**8 stages, 10 stage modules** — stage 5 has three variants (5a cached, 5b vision, 5c agent), each in
its own file because they share no logic and have entirely different dependencies.

**Tooling:** `pyproject.toml` (setuptools), `pytest`, `ruff` for lint+format, `mypy` on `core/` and
`grammar/` only (the parts where types carry design weight, per §3.3). Runtime state — the SQLite
database, stored blobs, DLQ records — lives under `var/`, which is gitignored because it is
regenerated. Loop artifacts live in `.loop/` and **are** committed: the journal is history worth
keeping, and the scorecard is how a fresh session orients.

### Boundaries

| Unit | Does | Depends on |
|---|---|---|
| `core/*` | Value types and pure functions | nothing |
| `extract/*` | PDF/image → `PageText` | core |
| `grammar/*` | `PageText` + selectors → scored fields | core, extract types |
| `pipeline/*` | Sequences stages, enforces the invariant | all of the above via ports |
| `packs/*` | Domain knowledge only | core types, hook signatures |
| `adapters/*` | External world (Anthropic, filesystem, tesseract) | ports only |

A pack can be understood without reading the pipeline. The grammar executor can be tested without a
PDF. The pipeline can be tested with fake stages.

---

## 2. Data flow

One `JobContext` threaded through the stages. Each stage returns a new context with its slot filled;
no stage reaches backwards.

```
PDF path
  → s1 intake      : stable id (from source id), durable write, soft fingerprint, batch heuristic
  → s2 filter      : L1 allowlist/size → L1.5 text layer → OCR-ONCE → L2 light AI gate
                     produces PageText[] for the whole document, cached in context
  → s3 classify    : pack signal ladder over PageText; first hit wins; tags layered
  → s4 persona     : lookup key company × fingerprint × doc_type; hit / soft miss / hard miss
  → s5a | s5b | s5c: cached selectors | vision one-shot | enqueue agent job
  → s6 capture     : adjust ops, TWO confidence inputs (match quality + arithmetic closure)
  → s7 gate        : three lanes + audit sampling
  → s8 emit        : Stage 8 contract
```

**OCR happens once, in s2.** `PageText` lives in the context from that point on; no later stage
re-parses the document. This is spec Stage 2 as written, and it is why F2 costs almost nothing.

---

## 3. Design decisions worth defending

### 3.1 `Money` is `Decimal`, never `float`

The corpus is entirely exact-cent arithmetic with closure checks. `validate_gold.py` uses floats with
a ±0.011 tolerance, which is fine for checking labels but wrong for the pipeline: a tolerance is
where bugs hide. With `Decimal`, `298.34 + 69.62 == 367.96` is exact, so the F8 cross-checks demand
equality rather than nearness — and a genuine 1-cent discrepancy becomes visible instead of absorbed.

Parsing must handle every notation in the corpus: `-99.80` · `(249.84)` · `212.87 cr` ·
`$1,231.74 CR` · `481.20 USD` · `$.00` · `83.7900`. All normalize to signed `Decimal`.

### 3.2 `PageText` normalization is the entire OCR seam

pdfplumber yields chars/words with bounding boxes. tesseract TSV yields words with bounding boxes.
Both are normalized into one `PageText` structure, so `grammar/executor.py` never learns which source
it got. Consequences: regions resolve identically, patterns run identically, and OCR-vs-native parity
becomes a testable property rather than a hope.

The only difference the pipeline records is `text_source: native | ocr`, which drives the
`ocr_source ×0.90` modifier (delta 1 in corpus-analysis §6).

### 3.3 `amount_payable` has one writer, and it is not a selector

`ExtractedFields` and `DerivedFields` are separate types. Selectors write to the first; ops write to
the second. `ExtractedFields` keeps its backing dicts private and exposes them only as read-only
`MappingProxyType` views, so `set()` — which rejects every `derived_only` name — is the sole insertion
path. Grammar rule V10 ("no selector may target a `derived_only` field") is therefore enforced by the
type, not by reviewer vigilance.

This matters more than it looks. On 7 of the 10 corpus documents a selector pointed straight at
`amount_payable` would produce the correct value, so the bug is invisible to casual testing and
attractive to anyone simplifying the code.

**The precise claim, corrected 2026-07-27.** An earlier draft of this document said the separation made
the bug "structurally impossible" and "impossible to violate." That was overstated, and the Task A3
review disproved it: the first implementation subclassed `dict`, and `setdefault` and `|=` bypassed the
guard entirely because CPython implements them in C and they never dispatch to an overridden
`__setitem__`. Two fix rounds later the exposed surface is genuinely read-only, but
`obj._values[name] = value` still reaches the private attribute — and no Python design closes that,
since `object.__setattr__`, `__dict__`, name-mangled access and `ctypes` all remain.

So the accurate claim is: **no accidental path, exactly one intended writer.** The threat this guard
exists for is machine-authored persona JSON naming `amount_payable`, which reaches `set()` and raises.
A developer deliberately writing `obj._values[...]` is a different threat, addressed by code review and
by the grammar validator's V10 check at persona-write time — two independent defenses, neither of them
absolute. Claiming more than that invites someone to trust the type and skip the validator.

### 3.4 Stage 6 has two independent confidence inputs

Spec Part 2 scores confidence from match quality alone: anchor found, pattern clean, value parses.
Finding F8 adds an orthogonal input: does the arithmetic close?

These catch different failures. Match quality catches *"I could not read this."* Closure catches
*"I read it perfectly and it is still the wrong number."* U-Pak proves both are needed — every field
extracts cleanly at high match quality, and the document is still unpayable.

Implementation: the executor emits `match_quality` per field; `ops/crosscheck.py` emits named
modifiers; `core/confidence.py` combines them multiplicatively and records every modifier on the
record, per spec Stage 6. Boosts are capped at ×1.10 and can never lift a field above 0.99.

### 3.5 The invariant is enforced by a context manager

`count(intaken) == count(emitted)` is spec Stage 8's machine-checkable promise. Rather than trusting
every code path to remember, `runner.py` wraps each document in a context manager whose `__exit__`
emits a `dead_letter` record if nothing was emitted — including on unhandled exception, timeout, or a
pack hook throwing. The invariant then holds by construction, and the test only has to prove the
wrapper works.

---

## 4. Error handling

| Class | Cause | Behavior |
|---|---|---|
| `TransientError` | vision timeout, storage blip | retry with backoff; exhausted → DLQ |
| `PermanentError` | corrupt PDF, unsupported type | DLQ + `disposition: dead_letter` |
| `PackError` | a pack hook threw | that document → DLQ; the run continues; other documents unaffected |
| `ValidationError` | persona write violates V1–V13 | whole write rejected; no partial application; pipeline unaffected |

Every class still produces a Stage 8 record. Per spec Part 4, a throwing hook never crashes the run,
and the same retry-then-DLQ policy covers stage-internal failures.

---

## 5. Testing

| Level | Covers |
|---|---|
| Unit (pure) | money, dates, patterns, regions, validator, confidence, contract |
| Grammar | executor against fixture `PageText` — one test per selector kind and region |
| Stage | each of the 10 stage modules against a synthetic `JobContext` |
| Integration | `replay-gold`: 10 real PDFs → assert against `docs/corpus/gold/` |
| Invariant | burst load with failures injected at every stage → count equality |
| Anti-regression | **the naive F1 answer must fail** (see below) |

### The F1 anti-regression test

```
GIVEN the digital-direction pack
WHEN  amount_payable is derived for Centracom
THEN  it is 13752.60 and payable_basis is "current_charges"
AND   a hypothetical rule returning total_printed (33876.40) FAILS this test
```

Its purpose is to fire when someone notices `total_printed == current_charges` on 7 of 10 documents
and "simplifies" the derivation. The test names the reason in its failure message so the next reader
does not have to rediscover F1.

---

## 6. Build strategy: bootstrap, then converge

### Part A — Bootstrap (linear, not iterative)

You cannot run a convergence loop without a scoreboard. Part A ends when three things are true:

1. Any PDF passed to the CLI traverses all 8 stages and emits a schema-valid Stage 8 record.
2. `replay-gold --json` produces a machine-readable scorecard over all 10 documents.
3. The invariant test passes under injected failures.

Correctness is expected to be near zero at this point. That is the intended state: Part A builds the
instrument, Part B moves the needle.

### Part B — Convergence loop

Repeat until the exit condition holds:

```
1. docintel replay-gold --json > .loop/scorecard.json
2. cluster failing assertions by root cause, then rank:
     tier 1  a whole stage or layer is missing        (affects many docs)
     tier 2  one shared op / pattern / region is wrong (affects several)
     tier 3  one persona selector is wrong            (affects one)
   within a tier, cheapest first
3. pick exactly ONE failure cluster
4. write a failing test at the LOWEST level that reproduces it
5. implement the minimum fix
6. re-run: unit tests + replay-gold + validate_gold.py
7. regression? revert, narrow the cluster, retry
8. append the iteration to .loop/journal.md (cluster, fix, score delta)
```

**Exit condition:** 10/10 gold documents green · invariant test passing · zero unit regressions ·
`validate_gold.py` green.

The scorecard and journal make the loop **resumable**. A fresh session runs `replay-gold`, reads the
two files, and knows exactly where it is without re-deriving anything.

### Loop guardrails

"Loop until green" has one obvious failure mode: relaxing the assertion instead of fixing the code.
Four guardrails, in priority order:

| # | Guardrail | Enforcement |
|--:|---|---|
| 1 | **Gold files are read-only to the loop** | Changing any gold value requires re-reading the source PDF and writing a justification in the journal. The gold set is the spec, not a variable. |
| 2 | **The F1 anti-regression test is undeletable** | Its removal is precisely the shape of the bug it guards. |
| 3 | **`validate_gold.py` stays green** | Prevents "fixing" a label into internal inconsistency. |
| 4 | **Stuck detector** | The same cluster surviving 2 consecutive iterations halts the loop and escalates. Two failures mean the fix is architectural, not local; further iterations only burn tokens. |

Plus a hard iteration cap that escalates rather than churning.

### Expected trajectory

| Milestone | `replay-gold` | Route taken |
|---|--:|---|
| Part A complete | runs; ~0/10 correct | everything falls through to a fake 5b |
| Extract + grammar landed | partial fields, native-text docs | 5a with incomplete personas |
| Adjust ops + gate landed | most Northstar docs green | 5a |
| Both packs + 8 authored personas | 8/10 | 5a for the 8 native-text documents |
| Vision port + cassettes (5b) | 10/10 | 5b for the 2 image-only documents |
| Persona store + 5c enqueue | 10/10, fast lane exercised | 5a hits on re-run |

**Why 8 authored personas and not 10.** The two image-only documents (Complete Beverage, Federal
Recycling) are deliberately *not* given hand-authored selectors. Authoring reliable anchors against
OCR noise is unproductive work that the vision path exists to absorb — and it matches their gold
expectations, which are `medium/review` and `forced review` respectively. Neither is expected to reach
the High lane, so neither needs a fast lane. They are the documents expected to resist longest, and
the correct outcome for both is a flagged record, not a clean one.

---

## 7. Risks

| Risk | Mitigation |
|---|---|
| OCR quality on the two image-only PDFs is too poor for exact-cent closure | Tesseract tuning is its own loop cluster. If closure proves unreachable, both documents route to review — which is a *correct* outcome and already exactly their gold expectation (`medium/review` for Complete Beverage, `forced review` for Federal Recycling). This risk cannot fail the done bar. |
| The closed grammar cannot express a corpus layout | Spec Part 4: it stays on the vision path and is flagged, not forced. Growing the grammar is a deliberate act with an eval, never a loop shortcut |
| No API key, so 5b cannot be recorded | `fake.py` carries the loop until a key exists; the cassette format is written first so recording is a drop-in later |
| The loop optimizes for the 10 documents and overfits | Gold assertions test *derivations and routing*, not just values; the grammar validator and the F1 test constrain the shape of any fix |
| Scope creep into the downstream service | The Stage 8 contract is the only interface; anything needing vendor resolution or matching is out of scope by construction |

## 8. Open questions (do not block this build)

Carried from `docs/README.md`, still with the business: confidence thresholds · audit-sample rate ·
review SLAs · regeneration cadence · U-Pak's unexplained −$48.92 · whether annotated and clean copies
of the same invoice both arrive.

Provisional threshold values from the pack docs are used so the gate is testable. They are expected to
move and are isolated in one place per pack for that reason.
