# docintel

Turn a vendor invoice or bill into a confidence-scored structured record — without a human in
the middle, except for the cases where a human genuinely should be, which the system says so
about rather than guessing.

## Install

```bash
pip install "docintel[ui] @ git+https://github.com/jeevatechjays/DocIntel.git"
```

Contributing to docintel itself instead of just using it? Clone the repo and install editable:
`pip install -e ".[dev,ui]"`.

## Run your first document

```bash
docintel process path/to/an/invoice.pdf --json
```

That's the whole loop: read the page, figure out which company it belongs to and what kind of
document it is, extract the fields that company cares about, apply any business rules that
decide what's actually owed, and emit one JSON record — always one, even when nothing could be
extracted (see `disposition` in the output: `processed`, `skipped`, or `dead_letter`).

Not just PDFs: an `.eml` or Outlook `.msg` is unwrapped and every attachment processed in its
own right, and a `.docx`/`.xlsx` is converted to PDF first (needs LibreOffice installed —
see `pyproject.toml` for details).

## As a library, in your own code

```python
from docintel import build_pipeline
from docintel.adapters.vision.fake import FakeVision  # or a real vision adapter

pipeline = build_pipeline(vision=FakeVision())
record = pipeline.process(document_id="d1", source_path="invoice.pdf")
```

**One `Runner` per concurrent worker, not one shared across threads.** A `Runner`
keeps small mutable state for the documents it processes (an in-run duplicate-detection
index, a processed-document counter) — safe for one worker calling `.process()`
repeatedly, not safe for two threads calling `.process()` on the *same* `Runner` at
once. `build_pipeline()` is cheap to call again per worker (the packs and personas it
loads are cached process-wide), so the right pattern for a concurrent service is one
`Runner` per worker/thread, built once and reused for that worker's whole lifetime —
never a single `Runner` shared across concurrent callers.

## Real-time notification

`docintel` doesn't include an inbox watcher or a webhook receiver — that's your own
infrastructure's job, whatever it looks like — but `pipeline.process(...)` is a plain synchronous
call, so wire it into whatever already tells you a document has arrived. To know the *instant* a
document needs a human, without polling, register a hook before building the pipeline:

```python
from docintel import build_pipeline, HookRegistry
from docintel.adapters.vision.fake import FakeVision  # or a real vision adapter

def notify_if_needs_review(ctx, nxt):
    ctx = nxt(ctx)  # let the pipeline finish deciding lane/review_flag first
    if ctx.review_flag or ctx.lane == "low":
        my_own_notifier(ctx.document_id, ctx.lane)  # your Slack/email/webhook — your choice
    return ctx

hooks = HookRegistry()
hooks.register("beforeEmit", notify_if_needs_review, pack="my_integration")
pipeline = build_pipeline(vision=FakeVision(), hooks=hooks)
```

`beforeEmit` fires after the pipeline has already decided `lane`/`review_flag`/`regen_flag` for
every document it emits a record for (including skipped and dead-lettered ones), so this hook sees
the real routing decision, not a guess — and it runs inline, in the same call that processed the
document, so there's no polling interval to wait out. `docintel` deliberately doesn't pick the
channel (email/Slack/webhook) for you; that stays your own code, in `my_own_notifier`.

## Onboard your first vendor

Start with **[`docs/onboarding/COMPANY-CONFIG-TEMPLATE.md`](docs/onboarding/COMPANY-CONFIG-TEMPLATE.md)**
— fill it in with the company's document types and the fields your team actually needs, attach
one real sample document per type, and hand it to whoever reviews new vendors. No engineering
background required to fill it in.

For how what you fill in actually turns into a working configuration — and what's automated
versus what a human always checks — see
**[`docs/onboarding/CONFIG-SPACE.md`](docs/onboarding/CONFIG-SPACE.md)** or the illustrated version,
**[`docs/onboarding/ONBOARDING-EXPLAINER.html`](docs/onboarding/ONBOARDING-EXPLAINER.html)** (open
directly in a browser).

**No commit access to this repo?** A vendor, or a whole new company, can be onboarded entirely
from your own project — `DOCINTEL_EXTRA_PERSONAS_DIR` for a vendor under a company docintel
already ships, `build_pipeline(..., extra_packs=[pack])` for a wholly new one. Neither touches
the installed package, so `pip install --upgrade` never wipes them out. Full step-by-step, with
a worked example (three real invoices, three different clients, zero repo edits), is in the one
doc below.

## Go deeper — one page, everything

**[`docs/DOCINTEL-FEATURE-EXPLORER.html`](docs/DOCINTEL-FEATURE-EXPLORER.html)** (open directly in
a browser) — the single, complete reference: install, the 11-stage pipeline explained, when and
how the Gemini vision fallback runs, an interactive composer that assembles real code live as you
toggle features, every currently-configured vendor, the full CLI, the complete `pack.json` and
`persona.json` JSON schema (every field, every closed vocabulary, all 14 validation rules), gold
data & scoring, and a troubleshooting section built from the real gotchas hit while building this.

**[`docs/DOCINTEL-TECHNICAL-OVERVIEW.html`](docs/DOCINTEL-TECHNICAL-OVERVIEW.html)** — a shorter,
narrative companion for a reviewing engineer deciding whether to adopt this: the two ideas that
explain the whole design, a walkthrough of one document end to end, per-mechanism Q&A, and an
honest table of what's deliberately not shipped yet.

## Everyday commands

| Command | What it does |
|---|---|
| `docintel process <paths...>` | Run one or more documents through the real pipeline |
| `docintel serve` | Local web UI — upload one document, see the result, work the review queue |
| `docintel replay-gold` | Score the labelled corpus — the number that matters when you change anything |
| `docintel accuracy-report` | The same score, read aloud: percent correct by company and document type, every failure named — hand this to someone who isn't reading code |
| `docintel queue-status` | How many documents are waiting on a human decision, and for how long |
| `docintel new-pack` | Scaffold a brand-new company's `pack.json` + a starter persona |
| `docintel validate-persona` | Self-check a persona file — scaffolded or hand-edited — before asking anyone else to look at it |
| `docintel draft-gold` | Turn one clean pipeline run into a draft gold fixture — no review-queue correction needed first |

Full command list: `docintel --help`.
