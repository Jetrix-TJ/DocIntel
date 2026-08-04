# Simple Web UI — design

**Status:** approved (user opted to skip the written-spec review checkpoint and proceed straight
to implementation — see conversation, 2026-08-04).

## Purpose

A local, single-user web UI that wraps the existing extraction pipeline: upload one PDF, see
whether it processed and what was extracted. It is a thin viewer over the pipeline that already
exists — it introduces no new extraction, classification, or routing logic of its own.

## Scope decisions

- **Audience/deployment**: local only. `docintel serve` starts a dev server on `localhost` and
  opens a browser tab. No auth, no multi-user concerns, no production deployment story.
- **Persistence**: none. Upload → see result → done. Nothing is written to disk beyond the
  lifetime of one request (the uploaded PDF is saved to a temp file for the pipeline call and
  deleted immediately after).
- **Vision fallback**: off. The UI always runs with `FakeVision` (deterministic, answers nothing,
  no API key, no cost) — the same rule-engine-only extraction used throughout this project's
  development. If a document needs the AI vision fallback to resolve, it will route to
  review/dead_letter here exactly as it would in most `docintel process` runs today. Turning
  vision on is a possible later addition, not in this scope.
- **Results view**: a clean field table (`fields` + `derived`, skipping internal plumbing like
  `schema_version`, `extraction_route`, `scanline`), plus a status badge derived from
  `lane`/`review_flag`. Not raw JSON.

## Architecture

New, self-contained package `src/docintel/webui/`:

```
src/docintel/webui/
  __init__.py
  app.py              # Flask app factory + the two routes
  templates/
    upload.html
    result.html
  static/
    style.css
```

New CLI command `docintel serve` (added to `cli.py` alongside `process`/`replay-gold`): starts
Flask's dev server on `localhost:5000` and opens the browser via `webbrowser.open()`.

New optional dependency group in `pyproject.toml`: `ui = ["flask>=3.0"]`. The default install is
unaffected.

The web layer calls `build_pipeline(vision=FakeVision())` and `runner.process(...)` — the exact
same objects `docintel process` already uses. No parallel extraction or routing logic is written;
if pipeline behavior changes, the UI's behavior changes with it automatically. `app.py` exposes a
`create_app(runner_factory=...)` factory so tests can inject a runner backed by an empty persona
store, matching the pattern `tests/pipeline/test_stages_skeleton.py` already uses for exercising
the no-persona path.

## Components & data flow

**`GET /`** — upload form. One file input (`accept=".pdf"`), one submit button. No vision toggle,
no history list, no other controls.

**`POST /process`** — the only other route:

1. Reject anything that isn't a `.pdf` by extension (mirrors `FilesystemIntake`'s own check) and
   anything over 25MB (`MAX_CONTENT_LENGTH`) before the pipeline ever runs — shown as a plain
   validation error, no wasted extraction call.
2. Save the upload to a `tempfile.NamedTemporaryFile`, call
   `runner.process(document_id=<generated>, source_path=<temp path>)`, delete the temp file
   immediately after, regardless of outcome.
3. Inspect the returned record and render exactly one of four screens:

   | State | Detection | Shown |
   |---|---|---|
   | No persona at all | `record["extraction_coverage"]["declared"] == 0` — true iff no persona's selectors were declared for this vendor/doc-type combination | *"No extraction rules exist yet for this document."* Nothing else. |
   | Persona exists but collapsed on this document | `record["regen_flag"] is True` | *"Rules exist for this vendor but aren't matching this document — may need updating."* Different message from "no persona" because the fix is different (regenerate an existing persona vs. author a new one). |
   | Extracted | Neither of the above, `disposition == "processed"` | Field table + status badge (`lane`/`review_flag` → "Auto-approved" / "Needs review" / etc). |
   | Skipped or dead-lettered | `disposition in ("skipped", "dead_letter")` | The pipeline's own `reason` string, shown directly — already written for a human to read. |

   `extraction_coverage.declared == 0` is precise: it comes from `ctx.persona.field_selectors`
   (empty when `ctx.persona is None`), verified by reading `core/coverage.py::assess`. It is not a
   guess about record shape.

## Error handling

- Non-PDF upload / empty submission: rejected before the pipeline runs, form re-shown with a
  message.
- Oversized upload: rejected by `MAX_CONTENT_LENGTH`, same treatment.
- Unexpected pipeline exception: caught at the route level, renders a generic error page rather
  than a stack trace or a crashed server. Expected to be rare given the pipeline's own
  invariant (`tests/test_invariant.py`) that nothing is ever silently dropped — but the web layer
  should not assume that invariant covers surfaces the pipeline was never tested against.

## Testing

Flask's `app.test_client()` against the real pipeline — no mocked extraction:

- Upload a known-good sample (e.g. the DTSS control case, the cleanest document in the corpus) →
  assert the field table renders the correct values and the "Auto-approved" badge shows.
- Upload a `.txt` file → assert it's rejected pre-pipeline (no record produced).
- Inject a runner backed by an empty persona store (`_StubStore(None)`, same pattern as
  `tests/pipeline/test_stages_skeleton.py`) → assert the "no extraction rules exist" screen shows.
- Inject a runner backed by a persona whose rules will collapse on the test document → assert the
  "rules exist but aren't matching" screen shows, distinct from the no-persona screen.

## Explicitly out of scope (possible future additions, not building now)

Raised with the user as "anything else you think you can do" — not committed to, listed for
awareness:

- Turning vision fallback on via a UI toggle (would need API-key configuration handling).
- A history/audit list of past uploads (would need the small local store this design deliberately
  avoids).
- Batch upload (multiple PDFs at once) — current scope is deliberately one PDF, one result.
- Downloading the extracted record as JSON/CSV from the result screen.
- Surfacing which persona/pack _would_ need to be authored (vendor fingerprint, doc_type guess) on
  the no-persona screen, rather than just the stop message — useful operationally but adds detail
  the user explicitly said to leave out for now ("just the message, no table").
