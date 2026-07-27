# Document Intelligence — POC documentation

Email attachment → confidence-scored structured record, without a human in the middle.

## Start here

| Document | What it is |
|---|---|
| [`architecture/pipeline-v2.md`](architecture/pipeline-v2.md) | **The spec.** 8 runtime stages, the rule lifecycle, 8 hook sockets, the Stage 8 contract, 12 design decisions. Markdown transcription of the [interactive walkthrough](https://claude.ai/code/artifact/c771b645-8fa5-45fb-8527-e407618eed24). |
| [`corpus-analysis.md`](corpus-analysis.md) | **What the 10 sample PDFs actually taught us.** 21 findings (F1–F20 + F1b), each with evidence, and 13 spec deltas. Read §0 first. |
| [`architecture/selector-grammar.md`](architecture/selector-grammar.md) | The closed grammar the rule agent writes against: selector kinds, regions, patterns, `adjust` ops, confidence modifiers, 13 validation rules. |
| [`packs/northstar-recycling.md`](packs/northstar-recycling.md) | Pack spec — vendor AP invoices (documents 1–6). |
| [`packs/digital-direction.md`](packs/digital-direction.md) | Pack spec — telecom expense (documents 7–10). |
| [`corpus/README.md`](corpus/README.md) | The gold corpus: 10 hand-labelled expected outputs + a self-check validator. |

The 10 source PDFs live in this directory.

## The one thing to know

`Total Amount Due` is a label, not a promise.

| Document | Printed | Payable | Error if you trust the label |
|---|---:|---:|---:|
| CentraCom | $33,876.40 | $13,752.60 | **$20,123.80** |
| EDCO | $367.96 | $69.62 | $298.34 |
| U-Pak | $14,789.77 | $14,740.85 | $48.92 |

The naive "read the biggest bold number" approach is correct on 7 of 10 documents and wrong by
$20,123.80 on the largest one. Everything in `corpus-analysis.md` §F1 and the
`derive_amount_payable` op exists because of this.

## Verify

```bash
python3 docs/corpus/validate_gold.py     # 95 checks, no dependencies
```

## Build order

From `corpus-analysis.md` §4, weighted by evidence:

1. Gold set for all 10 documents — **done**, see `corpus/gold/`
2. `derive_amount_payable` + its eval (F1, F1b) — highest-dollar risk
3. OCR at Level 1.5 with `text_source` on the record (F2) — 20% of the corpus is image-only
4. The three arithmetic cross-checks (F8) — near-zero cost, correctly isolates the one document needing a human
5. `reference_list[]` with provenance (F11) + flattened-annotation tagging (F3)
6. Page roles / `invoice_with_attachment` (F10)
7. Scanline (F7) and filename (F17) cross-checks — scoring only

## Open questions for the business

Carried over from the spec, still unanswered; the provisional values in the pack docs exist so the
gate is testable, not because they are agreed:

- Confidence thresholds per field
- Audit-sample rate for the high lane
- Review SLAs
- Regeneration batch cadence

Plus two the corpus adds:

- **U-Pak's unexplained −$48.92.** `Total Invoice 14,789.77` vs `Please Pay 14,740.85` with zero
  aging. Is this a standing credit arrangement (in which case it is a rule) or a one-off (in which
  case review is correct forever)?
- **Annotated-vs-clean document pairs.** `CANADIAN WITHOUT NOTES` implies a `WITH NOTES` copy exists.
  Are both routinely emailed? If so, deduplication needs to prefer the clean copy, which the current
  design has no way to express.

## Accepted risks

From the spec: portal-link bill volume unmeasured · no retention/PII policy · review-surface build
order unowned.

Added here: the gold set is 10 documents against a target of 20–30 per domain, and reference lists on
6 of them are transcribed for page 1 only (flagged in the data as `reference_list_complete: false`).
