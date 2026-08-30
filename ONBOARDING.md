# DocIntel — Onboarding Guide

DocIntel turns a vendor invoice or bill into a confidence-scored structured record — without a human in the middle, except for the cases where a human genuinely should be, which the system says so about rather than guessing.

This guide covers two things: **installing and running it**, and **onboarding a new vendor/company**.

---

## 1. Install

```bash
pip install "docintel[ui] @ git+https://github.com/jeevatechjays/DocIntel.git"
```

Contributing to the repo itself instead of just using it? Clone it and install editable:

```bash
pip install -e ".[dev,ui]"
```

**Optional extras**, install only what you need:

| Extra | Needed for |
|---|---|
| `vision` | Real Gemini API calls (`--vision live`/`record`) |
| `export` | Writing Excel exports (also covers reading XLSX input) |
| `email` | `.msg` (Outlook) attachment support — `.eml` needs nothing extra |
| `generation` | AI-assisted persona drafting (`docintel generate-persona`, calls Claude) |

**One non-pip dependency**: LibreOffice (`soffice`) must be on the host if you'll process `.docx` input. Its absence fails loudly, per-document, with a clear error — it's safe to notice at deploy time rather than a hard install-time requirement. `.xlsx` is the one exception: without `soffice`, it still extracts via a pure-Python HTML-then-image fallback instead of failing (LibreOffice is still the primary path when present).

---

## 2. Process your first document

```bash
docintel process path/to/an/invoice.pdf --json
```

That's the whole loop: read the page, figure out which company it belongs to and what kind of document it is, extract the fields that company cares about, apply the business rules that decide what's actually owed, and emit **one JSON record — always exactly one**, even when nothing could be extracted.

Every supported format works the same way, no special flags:

```bash
docintel process invoice.jpg statement.docx notes.txt receipts.csv
```

**Supported formats today**: `.pdf`, `.png/.jpg/.jpeg/.tiff/.tif/.bmp/.gif`, `.docx/.xlsx`, `.txt/.csv/.html/.htm`, and `.eml`/`.msg` (every attachment inside is processed individually). Each format takes the internally appropriate path — images never touch PDF conversion, DOCX/XLSX render through LibreOffice (cached), TXT/CSV/HTML are read natively with no OCR or vision call at all.

### Reading the output

The fields that matter most in the emitted record:

- `disposition` — `processed`, `skipped`, or `dead_letter`. Always exactly one of these.
- `lane` — `high` / `medium` / `review` / `low`. Tells you how much to trust the result.
- `review_flag` / `regen_flag` — whether a human should look at this document, or whether the *rules* for this vendor need regenerating.
- `fields` vs `derived` — `fields` are raw printed values; `derived` are computed values (like `amount_payable`) that have gone through business-rule reconciliation. **Never trust a raw printed total as what's owed** — always read `derived.amount_payable`.
- `tags` — anomalies worth knowing about (e.g. `xlsx_hidden_content_present`, `has_flattened_annotations`).

---

## 3. Everyday commands

| Command | What it's for |
|---|---|
| `docintel serve` | Local web UI — upload a document, see the result, work the human-review queue |
| `docintel queue-status` | How many documents are waiting on a human, and for how long |
| `docintel replay-gold` | Score the whole labelled corpus — run this after **any** change |
| `docintel accuracy-report` | The same score, human-readable: percent correct by company/type, every failure named |
| `docintel telemetry-report` | Dead-letter rate, vision-escalation rate, mean confidence from real production runs |
| `docintel reconcile` | Cross-check a processed invoice against contracts on file |
| `docintel export` | Render already-processed records to Excel |

```bash
docintel serve --port 5000
```

---

## 4. Onboarding a new vendor

### Step 1 — Fill in the template

Hand `docs/onboarding/COMPANY-CONFIG-TEMPLATE.md` to whoever knows the vendor: company name, how to recognize its documents, every document type it sends, the fields your team needs per type, and one real sample document per type. **No engineering background required** — this is the whole interface.

### Step 2 — Get an AI-assisted first draft (optional, recommended)

```bash
docintel generate-persona path/to/sample_invoice.pdf --company "Acme Corp"
```

Sends one sample document to Claude, once, and asks it to describe each field's name/type/one-sentence location hint — from this project's own fixed field vocabulary, never an invented name. It **never** writes the actual selector geometry (the exact coordinates a persona uses to find a value) — that part doesn't generalize from a single blind pass and stays a human's job. The output is clearly labelled `"status": "draft - not reviewed, do not use in production"` and is never read by the real pipeline on its own.

### Step 3 — Scaffold the actual pack

```bash
docintel new-pack acme_corp --company "Acme Corp" --doc-type standard_invoice --hints path/to/generated/hints.json
```

Writes `pack.json` + a starter `personas/*.json` with every threshold/claim/selector as an explicit `TODO-human-must-set` placeholder. Never auto-registered anywhere on its own.

### Step 4 — Fill in the real selector geometry, then self-check

A human fills in region/anchor/pattern per field against the real sample document, then:

```bash
docintel validate-persona docs/onboarding/generated/acme_corp/personas/acme_corp.json --pack-file docs/onboarding/generated/acme_corp/pack.json
```

Runs the exact same V1–V14 grammar rules every shipped pack is held to (e.g. V10: a persona can never select `amount_payable` directly — only derive it through business logic).

### Step 5 — Build a gold fixture from a clean run

```bash
docintel draft-gold acme-corp-001 --source path/to/sample_invoice.pdf
```

Auto-fills fields/derived values from a real pipeline run. `expected_routing` (lane/review_flag/regen_flag) is deliberately **not** auto-filled — that's the one thing a gold fixture exists to check independently, so a human sets it by hand.

### Step 6 — Register and verify

Move the reviewed `pack.json`/persona under `src/docintel/packs/` (needs a PR), then:

```bash
docintel replay-gold
```

Confirm nothing regressed and the new vendor scores correctly.

---

## 5. No commit access to this repo? Two fully-supported paths, zero repo edits

**A new vendor for a pack that already ships** (`northstar`, `spt_metals`, `digitaldirection`, etc.): set `DOCINTEL_EXTRA_PERSONAS_DIR` to a directory you own, laid out `<dir>/<pack_name>/*.json` (personas) plus an optional `aliases.local.json`. Picked up automatically by the CLI — no code change, no script.

> **One tested exception**: for `digitaldirection` specifically, a genuinely new carrier billing a client not already in the managed-client roster still needs a real edit to the shipped alias table (a PR) — the overlay reaches persona lookup and fingerprint resolution but not that particular claim decision. Check a pack's claim-rule `kind` before assuming the overlay alone is enough.

**A brand-new company no shipped pack claims at all**: build your own `pack.json` + `personas/` folder (the same `docintel new-pack` scaffold works from your own project), then:

```python
from docintel import build_pipeline
from docintel.packs.datapack import load_pack_file

pack = load_pack_file("path/to/your/pack.json")
pipeline = build_pipeline(vision=your_vision_adapter, extra_packs=[pack])
```

Want an automatic, structured record of what happened — which documents dead-lettered, which came back low-confidence — without wiring your own logging around every `.process()` call? Opt in at build time; off by default, so nothing changes for you if you don't ask:

```python
pipeline = build_pipeline(vision=your_vision_adapter, extra_packs=[pack], telemetry=True)
# or telemetry="my_app/logs/docintel.jsonl" for an explicit path

record = pipeline.process(document_id="d1", source_path="invoice.pdf")

from docintel import telemetry
telemetry.problem_records()   # every dead-lettered or review/low-lane document
                               # logged so far — not just the rate telemetry.aggregate() reports
```

Gold-corpus scoring works the same way too — `docintel.scorecard.replay_gold` and `docintel.evals.draft_gold.draft_gold_fixture` both take a plain `runner_factory`/`record`, so the exact same eval machinery this repo uses works from your own project's `docs/corpus/gold/`.

Full detail and a worked example (three real invoices, three different clients, onboarded with zero repo edits): `docs/DOCINTEL-ARCHITECTURE-GUIDE.html`.

---

## 6. Where things live (quick reference)

| Piece | File |
|---|---|
| Company config template | `docs/onboarding/COMPANY-CONFIG-TEMPLATE.md` |
| Automated first-draft generator | `src/docintel/generation/persona_agent.py` |
| New-company scaffold | `src/docintel/generation/pack_scaffold.py` |
| Standalone persona self-check | `src/docintel/grammar/validator.py` (V1–V14) |
| Closed field-name vocabulary | `src/docintel/scorecard.py` (`CHECKED_FIELDS`) |
| Closed selector-pattern vocabulary | `src/docintel/grammar/patterns.py` (`NAMED`) |
| Real, hand-reviewed personas | `src/docintel/packs/<company>/personas/*.json` |
| No-repo-access vendor overlay | `DOCINTEL_EXTRA_PERSONAS_DIR` — `src/docintel/packs/registry.py` |
| No-repo-access new company | `build_pipeline(extra_packs=[...])` — `src/docintel/pipeline/stages/__init__.py` |
| Opt-in library telemetry log | `build_pipeline(telemetry=True)` — `src/docintel/pipeline/runner.py` |
| Retrieve dead-letter/low-lane records | `docintel.telemetry.problem_records()` — `src/docintel/telemetry.py` |
| One-page deep reference | `docs/DOCINTEL-FEATURE-EXPLORER.html` |
| Architecture walkthrough for reviewers | `docs/DOCINTEL-TECHNICAL-OVERVIEW.html` |
