# Cluster C6 — the real vision adapter, with cassettes

**Delivers:** `AnthropicVision` (Anthropic SDK, structured output, PDF passthrough),
`CassetteVision` (record/replay, content-keyed), the vision privilege boundary
(`policy.py`), `--vision {cassette,fake,live,record}`, and GUARDRAILs 7 and 8.

```
tests     1,377 passing in 7.2s     (1,290 -> 1,377)
mypy      strict, 24 files          0 errors   (18 -> 24; vision adapters now checked)
ruff      src + tests               clean
gold      validate_gold.py          95 checks green
scorecard 1/10 documents, 274/339   unchanged, and unchanged on purpose — see below
```

**This cluster retires a risk; it does not move the scorecard.** The largest
unretired risk in the project was that nothing had ever called a vision model, so
the entire 5b branch was a shape with no implementation behind it. It now has one,
plus a deterministic offline replay path. What it deliberately did *not* do is
manufacture a scorecard improvement, for the reason in "The exit criterion" below.

---

## The exit criterion cannot be met as written, and should not be faked

**Plan, C6:** *"Exit criterion: `replay-gold` reaches 10/10."* With the note that
cassettes for Complete Beverage and Federal Recycling are *"hand-authored from the
gold files for the first pass (they are the expected vision output)."*

Two independent facts block that, and the second is the important one.

**1. No corpus document reaches Stage 5b.** All ten extract through `5a_cached`
and none collapses (`_collapsed` needs two fields below 0.50, or nothing extracted
at all):

```
5a_cached  native  high    centracom     5a_cached  native  high    dtss
5a_cached  native  high    comcast       5a_cached  native  high    edco
5a_cached  native  high    lumen         5a_cached  ocr     review  federal-recycling
5a_cached  native  high    windstream    5a_cached  native  review  upak
5a_cached  ocr     medium  complete-beverage                        veritiv (high)
```

A cassette for any of them would never be consulted. Reaching 10/10 through vision
requires widening the 5b trigger — a policy change about when a vision second
opinion is worth its cost, which is not this cluster's decision to make quietly.

**2. A cassette authored from gold scores the gold answer against itself.** This is
the reason not to route around fact 1. Hand-authoring Complete Beverage's expected
vision output *from* `docs/corpus/gold/complete-beverage.json` and then scoring the
resulting record *against* that same file is circular. The run would go green and
measure nothing — and the failure mode is not that it is wrong, it is that a green
`replay-gold` would become indistinguishable from a working one. `replay-gold` is
the only instrument this project trusts. Inflating it is the most expensive
possible shortcut.

So: the machinery is built and unused, `corpus.json` is checked in **empty**, and
**GUARDRAIL 8** (`tests/adapters/test_cassette_provenance.py`) fails if it gains an
entry not marked `provenance: recorded`. Authoring one remains available — author
it, change that test, write down why. Same rule the gold files live under.

---

## The vision response is a privilege boundary

The persona path's rule is *"the agent writes data, never code"*, enforced by
V1–V13 in `grammar/validator.py`. The vision path needed its own, because a
`VisionResult` is not inert: Stage 5b writes its `fields` into `ExtractedFields`
and its `irregularities` into the document's modifier and tag lists, and Stage 7
routes lanes off those lists. An unfiltered string from a model could therefore
move a document between queues.

`adapters/vision/policy.py` is that boundary. Three rules:

| Rule | Hole it closes |
|---|---|
| Only the requested field names survive; `DERIVED_ONLY` rejected twice | `amount_payable` would hit V10's guard and **crash the stage**; `notes` would put an unknown key on the record |
| Irregularities restricted to `VISION_OBSERVABLE` = `{handwriting_detected, high_skew}` | see below |
| Confidence clamped to `[0, CEILING]` | JSON Schema's supported subset has no `minimum`/`maximum`, so the bound cannot live in the schema |

**The modifier allowlist is where the real thinking is.** Handwriting and skew are
properties of the *image*, so a vision model is the best available witness. The
arithmetic modifiers (`arith_*`, `scanline_mismatch`, `filename_disagree`) are
computed by ops that do real comparisons — delegating them to a model would replace
arithmetic with an opinion. `flattened_annotations` is excluded for a sharper
reason: Stage 6 already detects it structurally from the PDF annotation count, and
it is one of the two `FORCING_MODIFIERS` — admitting it would hand a model the
power to force any document to human review.

Note the property that buys: **neither surviving name is in `FORCING_MODIFIERS`**,
so no vision response can route a lane on its own. It can only lower confidence,
and the gate decides what low confidence means. **GUARDRAIL 7**
(`tests/adapters/test_vision_policy.py`) asserts exactly that intersection is
empty, so a future adapter cannot widen the boundary silently.

`policy.sanitize` runs on **both** paths — live response and cassette replay. A
cassette is a JSON file a human edits, which makes it untrusted input in precisely
the way a model response is.

---

## Design decisions that departed from the plan

**Send the PDF, not rendered PNGs.** The plan said *"renders pages to PNG"*. The
Messages API takes a base64 `document` block natively, so rasterizing would add a
dependency (pdfium/poppler) to produce a strictly worse input: a re-render can drop
the flattened annotation overlays that F3 is entirely about, page indices would
have to be re-derived and kept in step with `page_meta`, and any resampling choice
would silently become part of the extraction's accuracy. Original bytes have none
of those problems. Guarded at 20 MB raw (base64 inflates 4/3 against the API's
32 MB request ceiling).

**`source_path` added to the port.** `PageText` is the *text layer*, and on the two
documents that most need vision it is OCR output — the very thing we are trying to
check. An adapter handed only `PageText` would be doing a text call and calling it
vision. Keyword-only and optional, so `FakeVision` needn't care. There is
deliberately **no text-layer fallback** in `AnthropicVision`: a missing source is a
`PermanentError`, because falling back would return a plausible-looking
`VisionResult` from a model that never saw the page.

**Module named `anthropic_adapter.py`.** The plan's file list says `anthropic.py`,
its interface list says `anthropic_adapter`. A module called `anthropic.py` inside
the package is safe under absolute imports but self-shadows the moment anyone runs
the file directly. Not worth the trap.

**Non-streaming `create` at `max_tokens=16000`.** Thinking is on by default on
Opus 5 and counts against `max_tokens`, so a budget sized for the JSON alone would
truncate mid-answer; 16000 also keeps a non-streaming request inside the SDK's HTTP
timeout. One short response, one code path — streaming would buy nothing and add a
second branch to the fallback path.

**Cassette keys follow content, not path.** Same lesson as the C1a cache-key fix: a
cassette survives the corpus directory moving, and goes stale — as a loud miss — the
moment the PDF changes. A path-keyed cassette does the opposite of both. Source-byte
keys and text-layer keys are domain-separated so they can never collide.

**A replay miss raises.** The tempting alternative — return an empty `VisionResult`
— is the silent-degradation pattern this project keeps removing (C1a's dead cache
bypass; the rejected persona that became a silent vision fallback). An empty result
makes "vision ran and found nothing" indistinguishable from "vision never ran". The
Runner's emit-always guarantee is what makes raising affordable: one dead-lettered
document with an actionable reason (`... re-run with --vision record to record it`),
and `count(intaken) == count(emitted)` still holds. Pinned by a test.

---

## What is not verified

**The live request shape.** `anthropic` is not installed here and no key exists, so
every test injects a fake client. What is pinned is the request we build (model,
`max_tokens`, adaptive thinking, `output_config.effort`, the JSON schema, the
document block's position and base64 encoding, the `fallbacks: "default"` beta
opt-in) and what we do with each response shape (refusal before reading `content`,
`max_tokens` truncation, non-JSON, missing text block, invented fields). What is
**not** pinned is that the SDK accepts that request. First live call should be an
operator running `--vision record` on one document.

Server-side refusal fallbacks (`fallbacks: "default"`, beta
`server-side-fallback-2026-07-01`) are on by default and use the beta endpoint. A
scanned AP invoice will not trip the cyber/bio classifiers in practice, but a
refusal returns HTTP 200 with empty `content`, so handling it is what keeps a
decline from surfacing as a confusing parse error. `AnthropicVision(fallbacks=False)`
turns it off and drops back to `client.messages.create`.

---

## Also in this cluster

- **`s5b` routes an observable irregularity to `add_modifier`, not `add_tag`.**
  Filing `handwriting_detected` as a tag would put the observation on the emitted
  record and leave every field's confidence untouched — honoured in appearance
  only. Anything outside the section 5 enum stays a tag, which is the right home
  for a signal with no defined price.
- **The vision adapters are now under strict mypy** (18 → 24 files). They sit on an
  external SDK boundary where every crossing value is untyped, which is the whole
  point of `policy.py`. `anthropic` gets an `ignore_missing_imports` override —
  note that adding `follow_untyped_imports = true` alongside it *defeats* the
  override, which cost a few minutes to find.
- `FakeVision` gained an `irregularities` argument and records `sources`, so a unit
  test can assert what the port handed the adapter.
