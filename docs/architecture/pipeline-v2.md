# Document Processing Pipeline — Architecture

**v2 — revised after engineering review 2026-07-23. Supersedes v1.**

> Markdown transcription of the interactive architecture walkthrough
> ([artifact `c771b645`](https://claude.ai/code/artifact/c771b645-8fa5-45fb-8527-e407618eed24)).
> This file is the authoritative text; the artifact is the visual companion.

---

## From inbox to structured record — without a human in the middle

Every incoming email attachment becomes a confidence-scored data record. Routine documents flow
straight through; people only ever see the genuine exceptions.

The system has two halves:

| | |
|---|---|
| **⚡ Runtime pipeline** | Takes one document in → classifies it → extracts fields → scores confidence → emits a record. *Runs on every document, in real time.* |
| **🧠 Rule lifecycle** | An AI agent that writes and repairs the extraction rules the runtime uses. *Runs only when triggered: first-time sender, low confidence, nightly eval.* |

> **The core economic idea:** extraction *rules* are cheap and reusable; the *agent* that writes them
> is expensive. Pay the agent once per document pattern, then reuse its rules on every future
> document that matches — for free.

---

# Part 1 · The runtime pipeline

## Eight stages, one document at a time

Teal **⌁ sockets** between stages are extension points (see [Part 4](#part-4--extensibility)).

```
                    ⌁ beforeIntake
                          │
                    ┌─────▼─────┐
                    │ 1 Intake  │
                    └─────┬─────┘
                          │
              ┌───────────▼───────────┐
              │ 2 Attachment Filter   │
              └───────────┬───────────┘
                    ⌁ afterFilter
                          │
                    ┌─────▼─────┐
                    │ 3 Classify│
                    └─────┬─────┘
                  ⌁ classifySignals
                          │
              ┌───────────▼───────────┐
              │ 4 Persona Lookup      │
              └───────────┬───────────┘
                ⌁ beforePersonaLookup
                          │
         ┌────────────────┴────────────────┐
    persona HIT                       persona MISS
    (fast lane)                      (cost ladder)
         │                                 │
  ┌──────▼───────┐              ┌──────────▼──────────┐
  │ 5a Apply     │              │ 5b Vision LLM       │
  │ Cached Rules │              │    One-Shot         │
  └──────┬───────┘              └──────────┬──────────┘
         │                        still weak → escalate
         │                                 │
         │                      ┌──────────▼──────────┐
         │                      │ 5c Claude Code      │
         │                      │    Agent            │
         │                      └──────────┬──────────┘
         └────────────────┬────────────────┘
                   ⌁ afterExtraction
                          │
                 ┌────────▼────────┐
                 │ 6 Capture Fields│
                 └────────┬────────┘
              ⌁ beforeConfidenceGate
                          │
                ┌─────────▼─────────┐
                │ 7 Confidence Gate │
                └─────────┬─────────┘
                     ⌁ beforeEmit
                          │
             ┌────────────▼────────────┐
             │ 8 Emit Structured Record│
             └─────────────────────────┘
```

---

### Stage 1 · Intake — *catch the email, keep everything*

- An email listener (Outlook / IMAP) receives mail and pulls out attachments.
- Every attachment gets a **stable ID and is saved to storage before anything else happens** — the ID
  derives from the mail message ID, so a crashed listener re-reading the mailbox yields the same
  document, not a duplicate. The email is acknowledged only after the write is durable.
- A cheap heuristic checks for **batch PDFs** (several invoices concatenated in one file); suspected
  batches are flagged for review — splitting is explicitly **not** attempted in v1.
- A **soft fingerprint** (sender + filename pattern + size + look of page 1) clusters *likely*
  duplicates — but never rejects them, because forwarded copies are often re-saved and byte-for-byte
  checks miss them.
- The real "is this a duplicate?" call waits until after extraction, when invoice number + vendor are
  known.

**Outputs:** `received_at` · `sender_email` · `email_id` · `possible_duplicate_of?`

> 📌 **Rule: Nothing is ever discarded at intake.**

---

### Stage 2 · Attachment Filter — *worth processing, or politely skipped?*

**Level 1 — cheap & deterministic** (handles most of the volume):

- File-type allowlist, sender-domain check, size sanity check.
- Filename pattern is only a *weak hint* — never the deciding signal.

**Level 1.5 — parse the text layer** (pdfplumber or similar — still no AI):

- Extract first-page text and scan for strong domain keywords: *invoice*, *statement*,
  *credit memo*…
- A keyword hit is a confident **accept** → tag `process` and skip the AI call entirely.
- But **no keywords ≠ skip** — scanned PDFs often have no text layer at all. Missing or ambiguous
  text just falls through to Level 2.
- **No text layer → OCR runs here, once.** OCR/normalization output (text + layout artifacts) rides
  along in the job context — classification and extraction never re-parse the document, and rules run
  on OCR text exactly like native text.

**Level 2 — one light AI call**, only for what's still ambiguous:

- A single cheap question on the first page: *"is this worth processing?"* — not full classification
  yet.

**Outputs:** `process | skip` · `reason`

> 📌 **Rule: Never silently drop** — a skip still emits a Stage 8 record with
> `disposition: skipped` and a reason.

---

### Stage 3 · Classify — *what kind of document is this?*

- Document type is decided from **content only — never the filename**.
- A **priority-ordered ladder of signals** runs top-down; the **first signal that fires wins**, then
  it stops. Example: credit-memo label → statement pattern → adjustment markers → own paperwork →
  *default: standard invoice*.
- Secondary **tags** are layered on afterwards (mixed-sign, has-tax, foreign-currency…) — they add
  handling hints but never change the type.

**Outputs:** `doc_type` · `tags[]` · `classification_confidence` · `signal_that_fired`

> 📌 **Rule: Classify before extracting** — rules depend on knowing the type. Hard boundary, never
> fused.

---

### Stage 4 · Persona Lookup — *have we seen this sender + doc type before?*

Lookup key: `company × sender_fingerprint × doc_type`

- The fingerprint is **deliberately dumb**: email domain + printed vendor name, lowercased and
  cleaned. It is *not* a resolved vendor identity — that's a downstream job.
- **Hit** → a persona (saved extraction rules) exists → fast lane (5a).
- **Soft miss** → persona exists but the layout looks different → run the rules first (drift is
  usually cosmetic); if the result **collapses** — several fields below threshold — fall back to the
  vision one-shot (5b) in the same pass. Either way the fingerprint divergence counts toward
  regeneration.
- **Hard miss** → never seen before → enter the cost ladder (5b, escalating to 5c).
- **Aggregator senders** (bill.com, Ariba, QuickBooks…) are keyed by the printed vendor name, never
  the shared email domain — a cheap first-page name probe (post-OCR when needed) supplies it before
  the lookup key is built.

---

### Stage 5a · Apply Cached Rules — *no AI needed*

- Deterministic extraction using stored field selectors — **zero AI calls**.
- This is the intended **high-volume path**: as personas mature, most traffic lands here.
- This is where the "pay the agent once, reuse forever" economics pay off.

### Stage 5b · Vision LLM One-Shot — *no rules? Just try it*

- Before spinning up a full agent session, the document pages go straight to an **expensive vision
  model** (Claude or Gemini) with the pack's field list: *"extract these."*
- Returns fields + per-field confidence for **this one document**. If confidence is good → proceed
  straight to capture.
- It produces **no reusable rules** — the cost repeats on every future document. So a rule-writing job
  for the agent is still queued, and the fast lane forms behind the scenes.
- If the result comes back weak or the layout is genuinely irregular → escalate to 5c.

### Stage 5c · Claude Code Agent — *extract this one + write rules for next time*

- The agent extracts *this* document directly **and** generates: field selectors, a layout
  fingerprint, and a few worked examples.
- **Runs async, single-flight:** one agent job per persona key, off a job queue — a burst of
  first-time documents queues ONE job while every sibling emits promptly via the one-shot. Agent
  timeout or crash → the document still emits (vision result + review flag).
- **Single-sample caution:** rules from one document are marked **draft**. Promotion to **stable** is
  mechanical: N consecutive gate-clearing extractions with zero corrections. Any correction resets
  the counter and re-queues the agent with the correction attached as evidence.
- Genuinely weird documents (e.g. inverted sign conventions) get **flagged, not forced** into the
  standard pattern.
- Writes to the Persona DB. See [Part 2](#part-2--inside-a-persona) for the exact payload.

---

### Stage 6 · Capture Fields — *every field, each with its own confidence score*

- **References are captured as a list, not a single value** — the match key can be labelled, buried
  in free text, or repeated per line. Keeping only the first hit loses real matches downstream.
- **Per-field confidence**, never one blended document score — a confident vendor name next to an
  uncertain total needs different handling than uniform doubt.
- Business-rule adjustments apply here via `adjust` ops — a **closed, pack-registered enum**. The
  agent may reference existing ops in its rules, never invent new ones; persona-writes naming unknown
  ops are rejected.
- Every dampener is a named multiplicative **confidence modifier** (`soft_miss ×0.8`,
  `draft_rules ×0.85`…) applied here and listed on the emitted record — one mechanism, auditable,
  composable.

**Outputs:** `fields{}` · `confidence{}` · `reference_list[]`

---

### Stage 7 · Confidence Gate — *three exits, but every document leaves*

| Lane | Condition | Action |
|---|---|---|
| **✓ High** | All fields clear their thresholds **and** every required field was found. | Emit as-is — plus a random N% **audit sample** into review: the only defense against rules that are confidently wrong. |
| **⚑ Medium / Low** | Specific fields fall short. | Emit + **review flag**. A human corrects it — and that correction becomes training data. |
| **⚑ Review** | A required field produced **nothing**, or the document itself mandates a human (flattened annotations). | Emit + **review flag**. |
| **⚠ Very Low** | Systemic failure — most fields uncertain, **or** most declared selectors produced nothing. | Emit + **regen flag**: the fix is "the rules are wrong," not "read this one document." |

> 📌 **Rule: Never withhold output.** Every document is emitted, whatever its confidence.

> 📌 **Rule: Completeness is scored separately from confidence.** Confidence exists only
> where a value exists, so it can never speak about a field that extracted nothing. The gate
> therefore routes on two dimensions, and `core.coverage` supplies the second — otherwise a
> document that lost four-fifths of its fields reads as clean, because the few that survived
> scored well. See `docs/architecture/selector-grammar.md` and `core/coverage.py`.

---

### Stage 8 · Emit Structured Record — *the hard contract everything downstream consumes*

This JSON is the **only** interface downstream systems see:

```jsonc
{
  "doc_type": "standard_invoice",
  "sender_fingerprint": "acmehauling.com|acme hauling",
  "fields": { … },                    // every captured field
  "confidence": { … },                // score per field, not per doc
  "extraction_coverage": {            // what was PROMISED vs what was found
    "declared": 16,                   //   selectors the persona declares
    "populated": 14,                  //   selectors that produced a value
    "missing_required": [ … ],        //   required fields that produced nothing
    "complete": false                 //   never true on an unassessed document
  },
  "reference_list": [ … ],            // ALL candidate match keys
  "extraction_rule_version": "v14",   // ← the audit trail
  "confidence_modifiers": [ … ],      // named dampeners applied
  "possible_duplicate_of": null,      // dedup DECISION lives downstream
  "schema_version": "1",
  "disposition": "processed",         // | "skipped" | "dead_letter"
  "review_flag": false,
  "regen_flag": false,
  "audit_sample": false
}
```

Why `extraction_rule_version` matters: every record traces back to the exact rule generation that
produced it. If a regeneration introduces a bug, the affected historical records are findable and
reprocessable.

> **The invariant:** every intaken document reaches this stage — `count(intaken) == count(emitted)`,
> alertable. Skips and dead-letters are records too, so "never silently drop" is machine-checkable,
> not a slogan.

---

## Worked scenarios

### 📄 Routine invoice — Acme Hauling, seen 40 times before

| Stage | What happens |
|---|---|
| 1 | Email arrives. Attachment saved with a stable ID — nothing is ever thrown away. |
| 2 | PDF from a known vendor domain, sane size. pdfplumber pulls the text layer — "INVOICE" is right in the header. Accepted, no AI needed. |
| 3 | Content ladder runs: no credit-memo label, no statement pattern… defaults to standard invoice. |
| 4 | Lookup: `acmehauling.com × invoice` → persona **HIT**. We already have rules for this exact layout. |
| 5a | Cached selectors run deterministically. Zero AI calls — this is the high-volume fast lane. |
| 6 | Every field captured with its own score. All three reference candidates kept as a list. |
| 7 | All fields clear their thresholds → **HIGH**. No human will ever see this document. |
| 8 | Record emitted with `extraction_rule_version: v14`. Done — fully automatic. |

### 🆕 First invoice ever from Novo Recycling

| Stage | What happens |
|---|---|
| 1 | Email arrives from an unknown sender. Saved and fingerprinted like everything else. |
| 2 | Unknown sender, but the parsed text layer contains "Invoice #" — a confident keyword accept, still zero AI calls. |
| 3 | Signal ladder says: standard invoice, tagged `has-tax`. |
| 4 | Lookup: `novorecycling.com × invoice` → **HARD MISS**. Never seen this pattern before. |
| 5b | No rules? Just try it: the pages go straight to a vision model with the field list. Usually that's enough — but this invoice's odd sign conventions come back low-confidence. |
| 5c | Escalate: **ONE** agent job queued for this persona key (single-flight, async). It extracts the fields AND writes selectors, a layout fingerprint, and worked examples — pure data, validated against the closed grammar. Saved as **DRAFT** — one sample proves nothing. |
| 6 | The agent's extraction is captured with per-field scores, kept conservative because the rules are drafts. |
| 7 | Draft-rule caution keeps confidence modest → routed with a **review flag** this first time. |
| 8 | Record emitted. The next Novo invoice will hit the persona and take the fast lane — the agent's cost is already amortizing. |

### 🔍 Messy scan — crumpled, rescanned invoice

| Stage | What happens |
|---|---|
| 1 | A blurry rescan arrives. The soft fingerprint clusters it near last week's copy as a possible duplicate — but nothing is rejected yet. |
| 2 | It's a scan — pdfplumber finds no text layer, so keywords can't decide. Falls through to the light AI gate, which says "worth processing." |
| 3 | Classified as a standard invoice despite the noise — content signals still fire. |
| 4 | Persona **hit** — we know this vendor's layout well. |
| 5a | Cached rules run, but the scan quality fights back on two fields. |
| 6 | Vendor name: 0.97 confident. Total amount: 0.55 — per-field scoring catches exactly which value is shaky. |
| 7 | The weak fields miss threshold → **MEDIUM**. Emit + review flag. A human fixes the total — and that correction joins the gold set. |
| 8 | Record emitted with `review_flag: true`. The correction just made tonight's eval smarter. ♻️ |

### 🛠 Vendor redesigned their invoice template

| Stage | What happens |
|---|---|
| 1 | A familiar sender, a familiar-looking email. Saved as always. |
| 2 | Filter passes — nothing unusual at this level. |
| 3 | Still classifies as a standard invoice — content signals survive a redesign. |
| 4 | Persona found, but the layout fingerprint diverges — **SOFT MISS**. Rules apply anyway with confidence auto-lowered. |
| 5a | Old selectors run against the new layout and collapse — multiple fields miss. Same pass: fall back to the vision one-shot, so the emitted values are still trustworthy. |
| 6 | Most fields come back uncertain — this isn't one bad field, it's everything. |
| 7 | Rule collapse + fingerprint divergence → **REGEN flag**: the rules are wrong, not the document. The emitted values came from the vision fallback, so they are still usable. |
| 8 | Record still emitted (never withheld). Flagged docs accumulate; once enough pile up, the agent regenerates the rules — and `rule_version` bumps so old records stay traceable. |

---

# Part 2 · Inside a persona

## What a rule actually looks like — and how it runs

A rule is not a model. It's **data**: anchors, patterns and regions that a dumb, fast executor can run
with zero AI calls. That's what makes the fast lane free.

**How a rule is applied, in four steps:**

1. **Verify the fingerprint** — page count, table shape, header signature still match? If the layout
   drifted → soft miss, confidence auto-lowered.
2. **Find each anchor** — locate the printed label the rule keys off ("Invoice #", "Total Due") in its
   expected region.
3. **Apply the pattern** — run the regex / value pattern near the anchor, on a linear-time engine with
   a hard timeout, so a pathological pattern can never wedge a worker. Reference patterns keep
   **every** match, not the first.
4. **Score each field** — anchor found? Pattern clean? Value parses? Match quality becomes that
   field's confidence score.

### 📦 The persona — rules at rest

One record in the Persona DB, keyed by `company × sender × doc_type`. A persona holds a **set of
layout variants** (keyed by fingerprint) — senders running two live templates don't oscillate.
Status: `draft → stable → drifting → regen_queued`.

```jsonc
{
  "sender_fingerprint": "acmehauling.com|acme hauling",
  "doc_type": "standard_invoice",
  "rule_version": "v14",
  "status": "stable",   // or "draft" until 2–3 samples agree

  "field_selectors": [
    { "field": "invoice_number",
      "anchor": "Invoice #",
      "region": "top-right",
      "pattern": "[A-Z]{2}-\\d{6}" },

    { "field": "total_amount",
      "anchor": "Total Due",
      "region": "last-table-row",
      "pattern": "currency",
      "adjust": "subtract_prior_balance_if_present" },

    { "field": "reference",
      "region": "line_items",       // no fixed anchor — buried in text
      "pattern": "NS\\s?#\\s?\\d{7}",
      "capture": "all_matches" },   // → reference_list[]

    { "row_group": "line_items",    // repeating rows — first-class (v2)
      "table_anchor": "Description",
      "columns": {
        "description": "text",
        "service_id": "[A-Z]\\d{4}",
        "amount": "currency" } }
  ],

  "layout_fingerprint": {
    "page_count": 1, "has_table": true,
    "header_signature": "logo-left|addr-right" },

  "few_shot_examples": [ /* 2–3 corrected documents */ ],
  "accuracy_last_eval": 0.97   // scored nightly vs. gold set
}
```

### 🧠 What the agent returns

Two payloads: an answer for *this* document, and rules for *every future* one.

```jsonc
{
  // ① this document's extraction — used immediately
  "extraction": {
    "fields": {
      "invoice_number": "AC-002561",
      "total_amount": 1284.50 },
    "confidence": {
      "invoice_number": 0.96,
      "total_amount": 0.88 },
    "reference_list": ["NS #2561194"],
    "irregularities": []   // e.g. "sign_convention_inverted"
  },                       //    — flagged, never forced

  // ② the persona write — the reusable investment
  "persona_write": {
    "status": "draft",        // one sample proves nothing
    "field_selectors": [ … ], // as shown above
    "layout_fingerprint": { … },
    "few_shot_examples": [ /* this doc */ ]
    // data only, validated against the closed selector
    // grammar — the agent never emits executable code (v2)
  }
}
```

The vision one-shot (5b) returns only payload ① — no `persona_write`. That's exactly why it's a
stopgap: it answers today's document but never builds the fast lane. Only the agent does both.

---

# Part 3 · The rule lifecycle

## The agent that keeps the rules honest

Runs beside the pipeline, not inside it. Three triggers, one strict boundary: it may **only** touch
extraction rules — never matching logic, resolution logic, or business rules.

### 🆕 First-time

A persona hard-miss the vision one-shot couldn't handle. Async, off a job queue, single-flight per
persona key. The document is never held hostage: agent timeout or crash → it emits anyway with the
one-shot result and a review flag. When the one-shot succeeds, rule-writing is queued in the
background.

### 📉 Low-confidence pile-up

Flagged documents accumulate for one sender + doc type. Async and batched — the agent is only paid
once enough evidence has piled up. All-fields-miss patterns are excluded from the count: that smell
is misclassification, not rule drift, and must not trigger regeneration of healthy rules.

### 🌙 Nightly eval

Current rules are scored against a growing gold set. Only personas whose accuracy has drifted below
threshold get regenerated — and a regenerated rule set ships only if it **beats the incumbent** on
that gold set (champion/challenger). Traceable damage is good; prevented damage is better.

### ♻️ The gold-set flywheel — accuracy that compounds for free

```
Doc scores Medium/Low — or is audit-sampled from High
        → Human corrects or confirms it
        → Correction saved as (document, expected output)
        → Nightly eval scores rules against it
        → Drifting rules regenerate
        → Fewer docs score low
```

The gold set is a *side effect* of normal review work from day one — never a separate labelling
project. It arrives via the **correction-return contract**: the downstream review surface posts
corrections, explicit confirmed-clean signals, and reconciliation mismatches back to the pipeline.
Targets are stored **pre-transform** (raw extracted values), so pack business logic can never leak
into extraction rules through the eval. Seeded with 20–30 hand-labelled documents per domain so the
evals work before the flywheel spins.

---

# Part 4 · Extensibility

## Hooks: how any domain plugs in without forking the code

The base pipeline exposes **8 named sockets** at stage boundaries. A domain pack registers a **chain
of functions** into any socket — the same middleware pattern as Express.js, applied to document stages
instead of web requests.

Each function gets the document's context and a `next()`. It can transform and pass along, stop the
chain early, or fail safely into a dead-letter queue.

```
pack.fnA()          →  next()  →   pack.fnB()      →  next()  →   base.default()
normalize totals                   tag currency                   built-in behavior
```

| Socket | Fires | What a pack plugs in |
|---|---|---|
| `beforeIntake` | Before dedup fingerprinting | Source-specific normalization (unwrap a carrier envelope format) |
| `afterFilter` | After filter, before classify | Domain-specific "worth processing?" logic |
| `classifySignals` | During classification | **The pack's own document taxonomy** — its priority-ordered signal ladder |
| `beforePersonaLookup` | Before the lookup key is built | Custom fingerprinting (two brand names, one carrier) |
| `afterExtraction` | After extraction (5a/5b/5c), before capture | Field transforms ("compute the real charge, don't trust the printed total") |
| `beforeConfidenceGate` | Before thresholds apply | Per-field threshold overrides, per-doc-type tolerances |
| `beforeEmit` | Just before the record leaves | Pack-specific metadata enrichment |
| `onRegenTrigger` | Before the rule agent runs | Gold-set filtering, domain-specific eval scoring |

> **Safety by design (v2):** hooks are **hand-written, PR-reviewed pack modules** — ordinary code in
> the repo, scoped to their company's namespace. A throwing hook routes the document to the
> dead-letter queue; it never crashes the run, and the same retry-then-DLQ policy covers
> stage-internal failures (corrupt PDF, vision timeout, storage error). The agent's output is **data
> only**, validated against a closed selector grammar — no machine-written code executes in this
> pipeline, so there is no sandbox runtime to build, secure, or debug. Documents the grammar cannot
> express stay on the vision path and are flagged, not forced.

---

# Part 5 · Reuse model

## One base, many domains

A new domain adopts the kit by writing a pack and providing labelled samples — never by rebuilding
the pipeline.

| 🏗 The common base — *built once, never changes* | 🧩 The per-domain pack — *supplied by each adopter* |
|---|---|
| All 8 runtime stages | Its document types + the signals that identify them |
| The confidence-gate mechanism | Its field set per document type |
| The rule lifecycle + Persona DB schema | Its hook functions (thresholds, transforms, fingerprinting) |
| The hook machinery itself (registry, dispatch, failure isolation → dead-letter queue) | Its reference data, tolerances & system of record *(used downstream)* |
| The four questions: *what is it · who sent it · what's on it · what do we do with it* | |

**Proven against two real domains:** Northstar Recycling (vendor AP invoices — one vendor group
mapping to 70+ account identities, match keys buried in free text) and Digital Direction (telecom
expense — every carrier lays out bills differently, one carrier arrives under two brand names).

---

# Part 6 · Why it's built this way

## Twelve deliberate decisions

Each looks odd until you see what it prevents.

| Decision | Rationale |
|---|---|
| The sender fingerprint is deliberately "dumb" | It stops the pipeline from silently absorbing vendor-resolution responsibility over time. True identity resolution belongs downstream, with its own rules and review. |
| First extraction produces draft rules, not final ones | One document overfits to that month's specific values. Rules stabilize only after 2–3 matching documents confirm the pattern. |
| References are captured as a list, never a single value | The match key moves around — labelled field, buried in free text, or repeated per line. Keeping only the first hit loses real matches downstream. |
| Confidence is scored per field, not per document | A confident vendor name next to an uncertain total needs different handling than a document that's uniformly uncertain. |
| Very-low confidence is a different flag from review | Systemic failure means "fix the rules," not "a human should read this one." Two flags, two different fixes. |
| Nothing is ever dropped or withheld | Every document — whatever its confidence — produces an emitted record. Silence is the one failure mode this design refuses. |
| The rule agent never touches matching or business logic | Extraction rules and business rules change at different speeds with different blast radii. Keeping them separate keeps changes safe. |
| Every record carries its `extraction_rule_version` | If a rule regeneration goes wrong, every affected historical record is identifiable and can be selectively reprocessed. |
| Hooks accept chains, not single callbacks | A pack can compose several independent behaviors at one socket without the base ever having to anticipate the combination. |
| Hook machinery is base; hook functions are pack | This is what keeps the base/pack split real: the pipeline codebase never forks per domain, yet every domain fully customizes it. |
| The agent writes data, never code *(v2)* | Selectors, patterns and fingerprints — validated against a closed grammar at persona-write. No sandbox runtime to build or secure; the blast radius of a bad agent output is a wrong value the gate catches, not arbitrary code in production. |
| The high lane is randomly audited *(v2)* | A feedback loop fed only by low-confidence review is structurally blind to rules that are confidently wrong. Sampling N% of clean emissions into review is the cheapest instrument that catches them — and confirmations double as promotion evidence for draft rules. |

### ⛔ Deliberately out of scope

A separate downstream service consumes the emitted record and owns:

- Vendor resolution to a system-of-record identity
- Invoice-to-contract matching & reconciliation
- Contract / rate cross-checks
- The Ready / Review / Handoff business decision
- The **duplicate decision** — fed by `possible_duplicate_of` + extracted keys on the record
- Implementing the **correction-return contract** (corrections, confirmed-clean, mismatches) — the
  flywheel's fuel line; a launch requirement, not a nice-to-have

It talks to this pipeline through the Stage 8 contract — and nothing else.

---

# Part 7 · Verification

## How we know it works — before production tells us

Thirty-one pipeline codepaths carry test requirements (full list in the eng-review test plan). Three
eval suites and one invariant guard the parts a unit test can't reach.

| Suite | What it does | Why |
|---|---|---|
| 🎯 **Agent rule-generalization eval** | Give the agent document #1 of a held-out sender; run the rules it writes against documents #2–3; score field accuracy vs gold. | Directly measures the bet the economics rest on: do one-shot rules generalize? Runs in CI before any prompt or grammar change ships. |
| 👁 **Vision one-shot eval** | Field accuracy of the 5b extractor against the gold set. | Guards the fallback path every first-time and collapsed document rides on. |
| 🚪 **Gate & classifier eval** | Stage 2 "worth processing?" and Stage 3 ladder accuracy on labelled documents. | A misclass runs the wrong persona's rules — cheapest to catch here. |
| ⚖️ **The invariant** | `count(intaken) == count(emitted)` under burst load with injected failures. | If this alert ever fires, "nothing is ever dropped" has stopped being true — the one failure mode the design refuses. |

**E2E journeys pinned by tests:**

- **First-time sender** — vision emit → agent drafts → next doc rides the fast lane
- **Template redesign** — collapse → 5b fallback → regen → version bump
- **Correction round-trip** — flag out → correction back → gold set → eval catches drift

---

## Change log

**v2 — revised after engineering review (2026-07-23), supersedes v1.** Adopted: declarative-only rules
(no generated code, no sandbox), async job state machine, single-flight agent jobs, OCR-once, row-group
selectors, layout variants, audit sampling of the high lane, champion/challenger regeneration,
correction-return contract, disposition on every record.

**Open questions still parked with the business:** confidence thresholds, audit-sample rate, review
SLAs, regeneration batch cadence.

**Consciously accepted risks:** portal-link bill volume unmeasured, no retention/PII policy yet,
review-surface build order unowned.
