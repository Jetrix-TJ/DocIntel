# Cluster C4 — the confidence gate

**Delivers:** a real `s7_gate` with four lanes, forced-review overrides,
deterministic audit sampling, and `tests/test_f3_forced_review.py`
(**GUARDRAIL 4**).

Executed inline. No fix rounds. One real bug, found by the end-to-end check and
not by 34 passing unit tests.

```
tests     1,101 passing in 7.8s      (1,061 -> 1,101; 40 new)
mypy      strict, 18 files           0 errors
ruff      src + tests                clean
gold      validate_gold.py           95 checks green
scorecard 0/10 documents, 42/339 assertions   (was 41/339)
```

**The +1 is the deliverable the resume doc had owed since C1b.** Federal
Recycling's `lane` now passes: the F3 chain works end to end, across three
clusters — `annotations.detect_flattened` (C1b) → the
`has_flattened_annotations` tag → the `flattened_annotations` modifier (C3) →
forced review and the `review` lane (C4).

---

## Four lanes, not three

The spec's Stage 7 table lists High, Medium/Low and Very Low. Two gold files
expect a fourth, `review`, and gold is the objective function.

**SPEC ERRATUM.** The fourth lane earns its place rather than being a synonym for
`medium`. Federal Recycling's fields may extract perfectly; the reason a human
must look is that the page carries values invisible to the text layer. Filing it
under `medium` would put it in the queue for documents whose *numbers* look
shaky, which is a different queue with a different fix.

| Lane | Meaning | Flags |
|---|---|---|
| `high` | Every field cleared its threshold | audit sample only |
| `medium` | Fields fell short, but the shortfall is explained | review |
| `review` | Something mandates a human regardless of confidence | review |
| `low` | Systemic collapse — the rules are wrong, not this document | review + regen |

Corpus distribution: 7 `high`, 1 `medium` (Complete Beverage), 2 `review`
(Federal Recycling, U-PAK), 0 `low`. `low` exists for the plan's systemic-failure
case and is not exercised by the corpus.

---

## Two dimensions, because counting is not enough

The gate inherited a single rule: `low` when the *share* of short fields reaches
0.60. That cannot work, and Complete Beverage is the proof.

A document-wide modifier — `ocr_source`, `draft_rules`, `handwriting_detected` —
penalizes **every** field equally. So the share of short fields is always 0.0 or
1.0, and `medium` is unreachable for any document whose only penalties are
document-wide. Complete Beverage is exactly that: OCR plus handwritten supporting
pages gives `0.90 x 0.60 = 0.54` on every field, and its gold expects `medium`
with regen `False`. The share rule alone routes it to `low` and raises a regen
flag telling someone to rewrite a persona that is working correctly.

So `low` now additionally requires most fields to fall below `VERY_LOW_FLOOR`
(0.50) — genuinely collapsed, not merely penalized.

**0.50 is chosen to sit below 0.60, the harshest single modifier in the §5 enum
(`handwriting_detected`).** One harsh signal must never on its own read as "the
rules are broken", because the fix for a handwritten page is not a new persona.
Regen requires a collapse across several signals. There is a test asserting that
relationship rather than the bare number, so moving either forces a re-think.

---

## The bug: forcing must read modifiers, not a boolean

The first implementation treated a pre-existing `ctx.review_flag` as a forcing
reason, on the strength of C3's own handover note ("the gate should treat it as an
input it may raise but must never clear").

**All 34 gate unit tests passed. All ten corpus documents came out `review`** —
including DTSS, which has no tags, no modifiers and nothing wrong with it.

The cause is `s5c_agent`, which sets `review_flag` for every hard miss. That is
correct: spec Part 3 says a first-time sender "emits anyway with the one-shot
result and a review flag". And with no personas yet, *every* document is a
first-time sender.

`review_flag` is simply too coarse to route on. "We have no rules for this sender
yet" is not the same statement as "this document has a problem", and putting them
in one queue would bury Federal Recycling's invisible overlays under every new
vendor the system ever sees.

Forcing now reads the closed §5 modifier enum instead:

```
flattened_annotations   0.75  F3 -> "also forces review, unconditionally"
arith_balance_mismatch  0.80  F8 -> "also raises review"
```

`arith_balance_mismatch` is what `derive_amount_payable` applies on each of its
three refusals, so U-PAK reaches `review` through evidence rather than through a
flag anyone could have set. Its lane correctly **fails today** and will pass when
C5 gives it a persona — which is the honest state, and is why the numerator went
to 42 rather than 43.

The flag itself is still never cleared. There is a test for that, and a separate
one asserting a bare upstream flag does *not* choose the lane, with the reason
written out.

**This is standing rule 9 earning its keep on the cluster right after it was
written.** Every link in the F3 chain had passing unit tests while the chain was
broken; only running a real PDF through all eight stages showed it.

---

## Other decisions

**A systemic collapse outranks a forced review.** Both can be true. `low` carries
the actionable signal — regenerate the rules — and `review_flag` is set either
way, so nothing is lost by preferring it.

**A forced review outranks an empty confidence map.** A forcing reason is a fact
about the *document*, not about whether extraction ran: Federal Recycling carries
invisible overlay values whether or not a persona ever executed. Without this,
its lane would read `low` today and the F3 chain would be untestable until C5.

**An empty confidence map never raises regen.** "There are no rules yet" is not
"the rules are wrong". This also protects ten currently-passing `regen_flag`
assertions from flipping to failure for a reason that says nothing about the
pipeline.

**Audit sampling never fires outside `high`.** A document already going to a human
does not need to be sampled into review, and marking it `audit_sample` would
corrupt the statistic the sample exists to produce. It also deliberately does not
change the lane: the document is genuinely clean and the record should say so.

**`handwriting_detected` now fires on `handwritten_supporting`** (a one-line change
in C3's Stage 6). §5 defines it as "Primary page has handwriting" and the tag says
the opposite, so C3 had not applied it — but Complete Beverage's gold routing
depends on it, its `expected_routing.reason` names it explicitly, and it is the
better reading: a supporting page exists to corroborate the primary one (F10), so
handwritten corroboration is weaker evidence. Recorded as a second erratum.

---

## What C4 did not do

- **Pack-supplied thresholds.** `ConfidenceGate(thresholds=...)` accepts them and
  nothing supplies them; every field uses the 0.90 default. The pack registry is
  C5. This matters more than it sounds: the seven `high` documents cannot reach
  `high` while a `draft` persona applies `draft_rules` (0.85) to every field, so
  **C5's personas must reach `active` status, or must ship thresholds below 0.85.**
- **The audit rate** is 0.0 in the default pipeline, which keeps `replay-gold`
  deterministic. Choosing a real rate is one of the open business questions in
  `docs/README.md`.

---

## Notes for C5

- The scoreboard is now concrete: 297 of 339 assertions fail, and essentially all
  of them are waiting on personas.
- `lane` passes for 1 of 10. The other nine need fields to extract.
- Mind `draft_rules`: a draft persona caps every field at 0.85 and the default
  threshold is 0.90, so a draft persona can never produce a `high` lane. Seven
  documents expect one.
- Complete Beverage's arithmetic is worth re-reading before writing its persona:
  it wants `medium`, which means its fields must extract *and* land between 0.50
  and 0.90. `ocr_source x handwriting_detected` = 0.54 does that on its own.
- Adding any scorecard assertion now has to pass GUARDRAIL 3, including the
  empty-record rule.
