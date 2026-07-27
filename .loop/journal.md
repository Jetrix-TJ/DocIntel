# Convergence loop journal

Append one entry per iteration. Never edit `docs/corpus/gold/` to make a test
pass — see the guardrails in the plan.

## Iteration 0 — baseline
- Cluster: none (Part A bootstrap complete)
- Score: 0/10 documents green
- Note: skeleton routes every document to the fake vision extractor, so almost
  every assertion fails. Instrument works; needle not yet moved.

### Fix round 1 — assertion set widened (instrument change, not a behaviour change)
- The original CHECKED_FIELDS (12 scalars) plus 4 routing flags measured none
  of ten documented corpus-analysis findings (F1b, F3, F5, F7, F8, F11, F13,
  F14, F18) and none of the fifteen gold tags. A convergence loop could have
  driven this scorecard to 10/10 green while leaving reference_list empty and
  emitting no tags at all — the instrument could not see most of the target.
- Fix: CHECKED_FIELDS grew from 12 to 32 entries (grouped by finding),
  MONEY_FIELDS grew to cover the new monetary fields, and `matches()` gained
  two new comparison kinds: `superset` (every expected member must appear in
  actual, extras allowed) and `set` (exact set equality). Two new assertion
  builders were added: `tags` (superset — packs may add tags gold doesn't
  enumerate) and `reference_list.values` (set when `reference_list_complete`
  is true, superset when false, since 6/10 gold files transcribe page 1 only).
- Explicitly NOT added: `line_items`, `charges`, `scanline`, `sub_account` —
  these gold sections have no corresponding key on the Stage 8 record yet;
  scheduled into cluster C2's brief instead of stubbed here.
- Baseline figures changed for INSTRUMENT reasons, not behaviour reasons:
  assertions_total rose 137 -> 213; assertions_passed held at 27; documents
  green held at 0/10, as expected since nothing in the pipeline itself
  changed. See task-a10-report.md "Fix round 1" for full verification output.
