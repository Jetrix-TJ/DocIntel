# The config space — what happens after you hand in a company template

This is the answer to: *"we need a certain area where a team can add their own modules"* — a
documented, open place to declare a new company's document types and fields, the same way a team
today hands over an already-filled-in key-elements file. This page describes that space: what you
fill in, what's automated, what a human always checks, and where each piece lives.

## The three steps, in order

### 1. You fill in the template

**[`COMPANY-CONFIG-TEMPLATE.md`](COMPANY-CONFIG-TEMPLATE.md)** — company name and how to
recognise its documents, every document type it sends, the fields your team needs per type, and
billing conventions if it's a recurring bill. Attach one real sample document per type. No
engineering background required — this is the whole interface.

### 2. A reviewer gets a first draft — increasingly, an automated one

Writing the actual field list by hand, from scratch, for every new company doesn't scale — that
was the exact gap raised at the Aug 18 standup: *"the schema generation... you are proposing it to
do it by human... we also need to find a way... to do it with some agents."*

`docintel generate-persona` closes that gap for the first draft, not the final answer:

```bash
docintel generate-persona path/to/a/sample.pdf --company "Acme Corp"
```

This sends the one sample document to Claude, once, and asks it to describe — in plain language,
one sentence per field — what it sees and where: the field's name (from this project's own fixed
list of fields it already knows how to score, never an invented name), its type, and a hint like
*"the invoice number, printed top right beside the words Invoice No."* It never asks the model to
write real selector geometry (the coordinates a hand-authored persona uses to find a value with no
sentence attached) — an earlier internal test proved that's the one part that does **not**
generalize from a single blind pass. The field list and the one-sentence hints are what carries
over; the pixel-level geometry stays a human's job, informed by this draft.

The command writes a file that says exactly what it is:

```json
{
  "status": "draft - not reviewed, do not use in production",
  "company_name": "Acme Corp",
  "source_pdf": "sample.pdf",
  "spec": { "fields": [...], "row_groups": [...], "notes": "..." }
}
```

Nothing about this file is read by the real extraction pipeline. It exists purely to give the
human reviewer in step 3 a starting point instead of a blank page.

### 3. A human reviews it — always, no exceptions

This is not a formality and it is not skippable. Both the person who proposed the automated draft
and the person building it agreed on this at the standup: *"let's say the generation was done and
the quality is not good, then we will mark it down... and human review it. We only approve it."*

A reviewer:

- Reads the draft alongside the same sample document and confirms each field and hint is actually
  right — not close, right.
- For a genuinely new company (no pack at all yet), starts from a real scaffold instead of reading
  `acme_freight`'s source by hand:

  ```bash
  docintel new-pack acme --company "Acme Corp" --doc-type standard_invoice \
    --hints docs/onboarding/generated/acme.hints.json
  ```

  Writes `docs/onboarding/generated/acme/pack.json` and a starter
  `personas/acme.json` — field names/types carried over from the hint-spec draft, every
  `region`/`anchor`/`table_anchor` left an explicit, unmissable placeholder (selector geometry is
  the one thing that doesn't generalize from a blind pass, same reasoning as step 2). Nothing here
  is registered anywhere — same as the hint-spec draft, it's a starting point, not a live
  configuration.
- Self-checks the result — scaffolded or hand-edited — before asking anyone else to look at it:

  ```bash
  docintel validate-persona docs/onboarding/generated/acme/personas/acme.json \
    --pack-file docs/onboarding/generated/acme/pack.json
  ```

  Runs the same V1-V14 rules the real pipeline enforces on every shipped persona, standalone — no
  need to register anything first. Reports the first thing wrong (a placeholder region, a field
  name the pack doesn't register, …) clearly enough to fix and re-run, the same red-means-fix-it
  loop `ruff`/`mypy` already are in this project.
- Builds (or hand-corrects) the real persona: the selector geometry, the claim rules, anything the
  draft doesn't and shouldn't attempt.
- Tests it against the sample document(s) from step 1 and confirms the extracted values are
  correct before anything goes live.
- Only then does this company's documents route automatically going forward — and even after
  that, anything the system isn't confident about still goes to a review queue rather than
  guessing.

### If you don't have commit access to this repo

Everything above assumes the reviewer can add files under `src/docintel/packs/` and merge a PR.
A team that only `pip install`s the library has a fully-supported alternative that needs **no
repo access at all** — same `pack.json`/persona JSON shape, same `docintel validate-persona`
self-check, living entirely in your own project instead:

- **A new vendor for a pack that already ships** (`northstar`, `spt_metals`, `acme_freight`, or
  `digitaldirection` when the carrier already bills an existing managed client): set
  `DOCINTEL_EXTRA_PERSONAS_DIR` to a directory you own, laid out `<dir>/<pack_name>/*.json`
  (personas) plus an optional `aliases.local.json`. Picked up automatically by the CLI, no
  script needed. **Tested exception:** `digitaldirection` claims by carrier via an
  `alias_table` rule compiled once from the shipped table at import — the overlay reaches
  persona lookup and fingerprint resolution but not that claim decision, so a genuinely new
  carrier billing a client *not* already in `MANAGED_CLIENTS` still needs a real edit to the
  shipped alias table (a PR). Confirmed with a live test against both packs; check a pack's
  claim rule `kind` before assuming the overlay alone is enough.
- **A brand-new company no shipped pack claims**: build a `pack.json` + `personas/` folder in
  your own project (`docintel new-pack` scaffolds it the same way), load it with
  `docintel.packs.datapack.load_pack_file()`, and pass it to
  `build_pipeline(vision=..., extra_packs=[pack])`.
- Gold-corpus scoring works the same way too: `docintel.scorecard.replay_gold` and
  `docintel.evals.draft_gold.draft_gold_fixture` both take a plain `runner_factory`/`record`, so
  the exact same eval machinery this repo uses works from your own project's `docs/corpus/gold/`.

Full detail, real commands, and a worked example (three real invoices, three different clients,
onboarded with zero repo edits): `docs/DOCINTEL-ARCHITECTURE-GUIDE.html#external`.

## Where each piece lives, for anyone extending this

| Piece | File |
|---|---|
| The template a team fills in | `docs/onboarding/COMPANY-CONFIG-TEMPLATE.md` |
| The automated first-draft generator | `src/docintel/generation/persona_agent.py` |
| The hint-draft CLI command | `docintel generate-persona <pdf> --company <name>` |
| The new-company scaffold | `src/docintel/generation/pack_scaffold.py`, `docintel new-pack <slug> --company <name> --doc-type <type> [--hints <path>]` |
| The standalone persona self-check | `docintel validate-persona <persona.json> [--pack <name> \| --pack-file <path>]` (reuses `grammar/validator.py`'s own V1-V14, no new rules) |
| The closed field-name vocabulary a draft may use | `src/docintel/scorecard.py` (`CHECKED_FIELDS`) |
| The closed type vocabulary a draft may use | `src/docintel/grammar/patterns.py` (`NAMED`) |
| Where a reviewed draft's hints actually get used | `adapters.vision.hints.hints_for_persona` — the same `{field: hint}` shape, feeding Stage 5b's vision fallback, which already runs unconditionally for a company with no persona yet |
| The real, hand-reviewed personas the pipeline actually reads | `src/docintel/packs/<company>/personas/*.json` |
| Growing the gold corpus from a real run | `docintel draft-gold <gold_id> --source <pdf>` — auto-fills a new gold fixture from one clean pipeline run, no review-queue correction needed first; see `docs/DOCINTEL-ARCHITECTURE-GUIDE.html#eval-layer` |
| No repo access: a vendor added to a shipped pack | `DOCINTEL_EXTRA_PERSONAS_DIR` env var — `src/docintel/packs/registry.py` (`load_extra_personas`/`load_extra_aliases`) |
| No repo access: a wholly new company | `build_pipeline(vision=..., extra_packs=[pack])` — `src/docintel/pipeline/stages/__init__.py` |

## Why "draft" is a real status, not a suggestion

`draft` already carries a tested consequence in this system: a document extracted with a draft
persona gets an automatic confidence penalty and routes to review rather than auto-approving. This
page reuses that same status rather than inventing a new one, so a generated hint spec that
somehow ended up wired in early would still get caught the same way any other unreviewed
configuration would — belt and suspenders, not just a naming convention.
