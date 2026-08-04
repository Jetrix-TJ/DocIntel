# Web UI — trust signals and JSON export — design

**Status:** approved (design discussed in conversation, 2026-08-04).

## Purpose

The web UI (`src/docintel/webui/`, see
`docs/superpowers/specs/2026-08-04-simple-web-ui-design.md`) already computes per-field
confidence, confidence modifiers (e.g. `bill_to_mismatch`), and `possible_duplicate_of` on every
processed record, but the result screen discards all three and shows only extracted values and a
lane-derived Auto-approved/Needs-review badge.

`docs/STATUS-SUMMARY.md` (2026-07-30) names the two risks this leaves invisible:

- **§4.2 Confidence does not track correctness.** The highest confidence band (0.99) is *less*
  accurate than the band below it (0.90) — seven fields are wrong at maximum confidence,
  including one payable amount wrong by $6,621.41. A reviewer looking only at the
  Auto-approved badge has no way to know this.
- **§4.1 The wrong-inbox guard covers only half the corpus.** `bill_to_mismatch` — the tag
  raised when the printed bill-to party disagrees with the pack's client roster — is already
  computed and already on the record; it just never reaches the screen.

This change surfaces data the pipeline already produces. It adds no new extraction, scoring, or
routing logic — same principle as the original web UI design.

## Scope decisions

- **No color-coding by confidence value.** Only two confidence values occur in practice (0.90,
  0.99 — `docs/STATUS-SUMMARY.md` §4.3), and the higher one is measurably less reliable. A
  green/red indicator keyed to the number would manufacture a trust signal the data doesn't
  support. Confidence is shown as a plain number; the *modifiers* carry the actual warning
  weight.
- **`bill_to_mismatch` gets distinct treatment from other modifier tags.** It's the
  highest-consequence flag on record (wrong-party payment risk). Other tags (e.g.
  `has_flattened_annotations`) render as a generic humanized label so a newly-added tag doesn't
  require a template change; `bill_to_mismatch` gets specific, human-readable copy.
- **No new persistence for JSON export.** The original design's "Persistence: none" principle
  holds — nothing is written to disk beyond the lifetime of one request. JSON export is done
  client-side: the record is serialized into the already-rendered result page and downloaded via
  a `data:` URI anchor, not a second server route or a saved file.

## Components & data flow

All changes are in `src/docintel/webui/app.py::_view()` and `templates/result.html`. No route
changes, no new endpoints.

**`_view()` changes:**

- `rows` becomes `(label, value, confidence)` triples: `confidence = record.get("confidence",
  {}).get(name)`, rendered as `—` when absent (some derived fields carry no confidence entry).
- New `modifiers` list passed to the template: each raw tag in `record.get("confidence_modifiers",
  [])` mapped through a small `_MODIFIER_COPY` dict (`bill_to_mismatch` → its specific warning
  sentence) with a fallback to `_label(tag)` for anything not in the dict.
- New `duplicate_of` value: `record.get("possible_duplicate_of")`, `None` when absent.
- New `record_json` value: `json.dumps(record, indent=2)` — the full record, for the export link.
  Computed unconditionally (cheap, and useful on every state, not just "extracted") so the export
  link can appear on all four result screens, not only the happy path — a "no persona" or
  "collapsed" result is exactly the kind of record someone would want to hand to whoever authors
  the next persona.

**`result.html` changes:**

- Field table gets a third `<th>Confidence</th>` column.
- A modifiers block renders above the field table when `modifiers` is non-empty: each as a tag,
  `bill_to_mismatch`'s tag styled distinctly (reuse the existing `.error`-weight styling already
  in `style.css` rather than inventing a new color).
- A duplicate-warning line renders when `duplicate_of` is not `None`: "Possible duplicate of
  `<duplicate_of>`."
- An export link at the bottom: `<a download="{{ filename }}.json" href="data:application/json;charset=utf-8,{{ record_json | urlencode }}">Download raw JSON</a>`.

## Error handling

No new failure surface: `_view()` already runs inside the existing try/except in the `/process`
route. `json.dumps(record, indent=2)` cannot fail — every value in a validated record is
JSON-native by contract (`core/contract.py`'s own validation guarantees this before `_view` ever
sees the record).

## Testing

Extend `tests/webui/test_app.py` (same real-pipeline-no-mocks pattern already used there):

- Upload the clean DTSS document (end-to-end, real pipeline) → assert the confidence column
  renders numeric values for known fields, and that no modifier warning or duplicate banner
  renders (this document trips neither).
- No corpus/gold document currently trips `bill_to_mismatch` (confirmed: no gold file references
  it), so its rendering is not worth exercising end-to-end. Instead, unit-test `_view()` directly
  — the same level `tests/test_f3_forced_review.py::test_a_bill_to_mismatch_forces_review_whatever_the_confidence`
  already tests the gate at — with a hand-built record dict containing
  `confidence_modifiers: ["bill_to_mismatch"]` → assert the specific warning copy is produced, and
  with an unknown/future tag → assert the generic humanized fallback is produced.
- Unit-test `_view()` with `possible_duplicate_of` set → assert `duplicate_of` is passed through.
- Unit-test `_view()`'s `record_json` output round-trips through `json.loads` back to a dict with
  the expected keys, and assert the rendered `Download raw JSON` link's `href` contains a
  `data:application/json` URI wrapping that same content, on an end-to-end DTSS upload.
- Existing four-screen tests (no persona, collapsed, extracted, failed) continue to pass
  unmodified except for the new column existing in the extracted-state assertions.

## Explicitly out of scope

- Editing/correcting values in the UI (this stays a viewer, not an editor).
- Persisting the modifier/duplicate data anywhere — still request-scoped only.
- A confidence *threshold* control (e.g. "flag anything under 0.95") — the two-value reality
  documented in §4.3 makes a threshold control mostly meaningless right now.
