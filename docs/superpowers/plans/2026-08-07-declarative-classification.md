# Declarative Classification — pivot from correctness to generality

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans.

**Supersedes the remaining tasks of** `2026-08-07-classification-correctness-v2.md`.
Tasks 0-2 of that plan are landed and keep their value. Tasks 3, 6, 7 and 8 are
**parked**: each is a narrow fix to one tag on one vendor, and none of them moves the
goal below.

**Goal:** Onboarding a new company, or a new document type for an existing company,
must be **data plus evidence** — not a Python module and a pull request.

---

## The decision, and why

The codebase already solved this problem once, for the other half of the pipeline:

| layer | how a new vendor is onboarded | mechanism |
|---|---|---|
| **Extraction** | write a persona JSON | `field_selectors` validated against a closed grammar (V1-V13, `BASE_ADJUST_OPS`) |
| **Classification** | **write Python** | hand-coded ladder, hand-coded `claims()`, hand-edited `PACK_MODULES` |

Extraction is declarative, validated, and testable as data. Classification is the one
layer that stayed code, and that asymmetry *is* the generality problem:

- **"different types of company"** → a pack is a Python module named in a hardcoded
  tuple (`registry.PACK_MODULES`), with a bespoke `claims()`.
- **"different types of doc per company"** → a doc type is a rung in a hand-written
  `if` ladder (`northstar/ladder.py:302`, `digitaldirection/ladder.py:58`).

So: **give classification the same treatment the grammar gave extraction.** A closed,
named, tested registry of signal primitives; ladders and claim rules expressed as data
compiled against it; a validator that rejects a bad pack file the way
`validate_persona` rejects a bad persona.

This is deliberately *not* a rewrite. The pack protocol, the claim gate, the hook
sockets and the emit-always guarantee are unchanged. Only the ladder's and the guard's
**representation** changes.

### What this does NOT solve, and what to do about it

Two other generality gaps were measured on 2026-08-07 and are **not** in this plan:

- **File types.** Everything is `pdfplumber` + `pytesseract`-on-PDF-pages. A `.png`,
  `.docx` or `.eml` raises `PdfminerException` at Stage 2, is caught by the runner's
  catch-all, and dead-letters. The OCR engine exists but cannot be reached for a bare
  image. **Own plan** — a format adapter is self-contained and does not interact with
  this one. Sequence it second; a new company that sends PDFs is unblocked by this
  plan alone, whereas a new *file type* is blocked regardless of how packs are
  expressed.
- **Locale.** `parse_date("03/04/25")` returns `2025-03-04` — MM/DD assumed — with no
  ambiguity flag, so a UK/EU invoice silently inverts for the first twelve days of
  every month. `DateResult` already has `ambiguous_two_digit_year`; the day/month
  flag has a home waiting. Currency defaults to USD per pack and every anchor pattern
  is English. **Own plan**, small and high-value.

The tail — a company matching no pack, or a document matching no rung — still needs
the escalation path Stage 3 does not have (`s3_classify.py:55` defaults to
`standard_invoice` at 0.50 and proceeds). Declarative packs make onboarding cheap;
escalation makes the *first* document from an unknown sender useful. **Own plan,
third.**

---

## Architecture

```
  pack.json  (data: claim rules + ladder + tags)
      │
      ▼  compiled at load, validated like a persona
  ┌──────────────────────────────────────────┐
  │ packs/signals.py  — CLOSED signal registry│  ← the classification analogue
  │  short_label_line  title_near_top         │    of grammar's BASE_ADJUST_OPS
  │  label_with_corroborating_value           │
  │  marker_present  marker_corroborated      │
  │  every_hit_in_block  …                    │
  └──────────────────────────────────────────┘
      │
      ▼
  the SAME Pack protocol, the same classifySignals hook, unchanged pipeline
```

**The registry is closed on purpose**, exactly as `BASE_ADJUST_OPS` is. A pack author
composes existing primitives; adding a primitive is a code change with a test and a
named real document behind it. That is what stops "declarative" from becoming
"arbitrary regex soup authored by whoever onboarded the client last."

---

### Task A: `packs/signals.py` — the closed signal registry

Prerequisite for everything else. Carried over from v2 Task 5 with the review's
corrections applied (boundary tests; both of `title_near_top`'s constraints covered;
`primary_pages` single-sourced with `registry.primary_text` rather than duplicated).

Primitives, each already justified by a named real document:

| primitive | separates | evidence |
|---|---|---|
| `primary_pages` | invoice from stapled attachment | Complete Beverage's 3 BOL pages |
| `short_label_line` | a banner from prose | Federal Recycling's T&C boilerplate |
| `title_near_top` | a title from a wrapped footnote | `_AP Invoice 32473` vs `32593` |
| `label_with_corroborating_value` | a printed column label from a real value | Veritiv's `Total Tax` at $0.00 |
| `marker_corroborated` | a specific name from a bare ZIP | EDCO's typo'd bill-to |
| `every_hit_in_block` | bill-to from ship-to | landed 2026-08-07, Task 1 |

- [ ] Write `tests/packs/test_signals.py` **including the boundary pairs v2 lacked**:
      a match at `max_line_index - 1` (passes) and at `max_line_index` (fails); a
      `max_words`-word line (passes) and `max_words + 1` (fails), for BOTH
      `title_near_top` and `short_label_line`. Without these, `max_line_index` can be
      changed to anything in [6, 25] and every test still passes.
- [ ] Implement, single-sourcing `primary_pages` — rewrite `registry.primary_text` to
      call it rather than reimplementing the fallback with a docstring promising the
      two "mirror" each other.
- [ ] Add `src/docintel/packs` to mypy's `files` in `pyproject.toml`. It is currently
      unchecked, so v2's per-task "mypy passes" claimed coverage that did not exist.

### Task B: migrate the Northstar ladder onto the registry

The pack whose behavior must not change, so a **byte-identical `replay-gold`** is the
proof the registry is a faithful extraction. Gate is strict: any diff stops the task
and is reported, never resolved by loosening the gate or editing a test.

- [ ] Preserve every page scope exactly, including the two deliberate
      `primary_only=False` sites.
- [ ] **Pin the deliberate widening** — a supporting-page `PAST DUE` banner must still
      tag. v2 bolded this instruction and no test enforced it, so flipping the default
      left the suite green and `replay-gold` byte-identical.
- [ ] Keep each docstring's evidence; rewrite its mechanism references.

### Task C: the declarative ladder

- [ ] Define the schema: an ordered `rungs` list, each
      `{name, signal, params, doc_type}`, plus `tags` rules of the same shape.
- [ ] Write `validate_pack_file`, mirroring `validate_persona`: unknown signal name
      rejected, unknown param rejected, empty ladder rejected, first-match-wins order
      preserved and explicit.
- [ ] Express Northstar's ladder as data. **Byte-identical `replay-gold` again** — the
      same proof, now for the representation change.
- [ ] Express Digital Direction's ladder as data.
- [ ] A pack file that declares a rung naming a signal not in the registry must fail
      loudly at load, not silently classify nothing.

### Task D: the declarative claim guard

Task 1 already produced the right shape by hand: strong markers, corroborated
markers, and a block veto. Express it as data.

- [ ] Schema: `{markers, corroborated: [[marker, token]], vetoes: [{block, …}]}`.
- [ ] Migrate both packs; `replay-gold` unchanged and the out-of-domain corpus
      (`tests/packs/test_claim_precision.py`) still 6/6.
- [ ] Extend the out-of-domain corpus as new claim shapes are added — it is the only
      test that measures the direction that matters.

### Task E: onboarding proof — a third pack, as data only

The task that proves the goal was met rather than asserted.

- [ ] Add a synthetic third company **without writing a Python module**: a pack file,
      a persona, and evidence. If this requires touching `PACK_MODULES` or any
      `.py`, the plan has not met its goal and says so.
- [ ] Pack discovery reads pack files; keep the deliberate "named, not scanned"
      property (`registry.py:44`) by listing pack *files*, so a stray directory still
      cannot activate a pack.

### Task F: whole-corpus sweep

Non-negotiable, and the defense that caught the 2026-08-06 phantom fix.

- [ ] Re-run all 111 second-samples, diff every tag / `doc_type` / claim / review flag
      against `var/baseline-111-preplan.json`.
- [ ] **Expected: zero change.** This plan is a representation change, not a behavior
      change. Any delta is a defect until explained per-document against the PDF.

---

## Parked, with reasons

| v2 task | why parked |
|---|---|
| 3 — `count_printed_names` | one tag, one document, invisible to a superset assertion. Real, tiny, no bearing on generality. |
| 4 — `forbidden_tags` | measurement infrastructure for the gold corpus; valuable, but it makes the existing 11 documents sharper rather than making the 12th company cheaper. |
| 6 — DD `past_due` | narrow; and after the fix it fires on 0 of 11 available DD documents. |
| 7 — `foreign_currency` | narrow. Note it is really a **locale** signal and belongs with the locale plan, not here. |
| 8 — DD `credit_memo` | latent: 0 of 7 telecom second-samples print the wording. |

None is deleted. Each keeps its measured evidence in
`2026-08-07-classification-correctness-v2.md` and its review findings in the REVIEW
document, so picking one up later costs nothing.

## Success criterion

A new company with three document types is onboarded by adding **one pack file, one
persona per doc type, and the evidence behind each constant** — with no Python change,
no entry added to a tuple, and the out-of-domain corpus still green.
