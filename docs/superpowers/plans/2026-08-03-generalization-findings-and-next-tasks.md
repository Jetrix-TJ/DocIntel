# Handoff: Generalization Findings + Task Queue (2026-08-03)

> **For the agent picking this up:** you have no memory of the session that produced this
> document. Everything you need is either written here or pointed to below. Read the
> pointed-to docs first — do not re-derive facts they already contain, and do not repeat
> analysis they already did.

## What this project is

Reads vendor invoices / telecom bills, extracts fields via a per-vendor JSON rule file
("persona") interpreted by one generic engine, routes each document to auto-approve /
review / reject. No AI model runs in the extraction path. Configuration, not code — adding
a vendor means adding a JSON file, not writing a parser.

## Read these first, in this order

1. `docs/STATUS-SUMMARY.md` — current accuracy (203/263, 71.5% defensible figure),
   architecture, full list of known open risks (§4).
2. `docs/superpowers/plans/2026-07-29-weakness-remediation.md` — Wave 1 (shipped) and
   Wave 2 (fully scoped, **not started**) plan. Wave 2's tasks (7, 8, 2, 8c, N1-N4) have
   complete TDD steps, file paths, and commit templates already written. Follow them
   exactly — do not re-plan them.
3. `docs/superpowers/execution/ledger.md` — Wave 1's execution record and findings.
4. **This document** — new findings from a live test run on 2026-08-03, using real
   second-vendor invoices. Nothing below is recorded anywhere else in the repo yet.

## Where today's new test data came from

A user-supplied drop (`all-docs/*.zip`) was searched for a second invoice per vendor
(the #1 item in STATUS-SUMMARY §6). Real second samples were found for 7 of 10 vendors;
the full pool sits in `all-docs/second-samples/<vendor>/`. 26 of those (4 per vendor, or
all available if fewer — lumen only had 2) were copied into `docs/` (same folder as the
original 10 samples) and run through `python3 -m docintel.cli process --json`
(**not** `replay-gold` — no gold labels exist for these). No hand-labeling was done; all
findings below come from a cheap cross-check (comparing the extracted amount/account
number against the real value embedded in each file's name) plus reading the raw output.
Treat these as strong leads, not gold-verified facts, until confirmed by fixing and
re-running.

The 26 new files, still sitting in `docs/` as untracked (confirm with
`git status --porcelain docs/`):

```
_AP Invoice 13307OCT25      Edco Waste & Recycling Services Inc. 1618.27000.pdf
_AP Invoice 15570AUG25      Edco Waste & Recycling Services Inc. 894.98000.pdf
_AP Invoice 15570SEPT25     Edco Waste & Recycling Services Inc. 1405.43000.pdf
_AP Invoice 159507OCT25     Edco Waste & Recycling Services Inc. 580.42000.pdf
_AP Invoice 32389 Complete Beverage Destruction 2253.30000.pdf
_AP Invoice 32390 Complete Beverage Destruction 1887.67000.pdf
_AP Invoice 32395 Complete Beverage Destruction 1480.05000.pdf
_AP Invoice 32473 Complete Beverage Destruction -2249.00000.pdf
_AP Invoice 4421470 U-Pak 1360.60000.pdf
_AP Invoice 4444058 U-Pak 4476.34000.pdf
_AP Invoice 4488728 U-Pak 1695.00000.pdf
_AP Invoice 4489772 U-Pak 2833.29000.pdf
_AP Invoice 6025DTSS        D.T.S.S. Inc. 1800.00000.pdf
_AP Invoice 6025DTSSA       D.T.S.S. Inc. 500.00000.pdf
_AP Invoice 6026DTSS        D.T.S.S. Inc. 699.00000.pdf
_AP Invoice 6027DTSS        D.T.S.S. Inc. 1430.00000.pdf
_AP Invoice 689-37525600    Veritiv Operating Company 3312.50000.pdf
_AP Invoice 689-37578305    Veritiv Operating Company 3312.50000.pdf
_AP Invoice 689-37584900    Veritiv Operating Company 625.00000.pdf
_AP Invoice 715-33921625    Veritiv Operating Company 9375.00000.pdf
Lumen_5-2N8BFFLC_09012025_BILL.pdf
Lumen_5-DK176HGT_09012025_BILL.pdf
Windstream_021942648_09022025_BILL.pdf
Windstream_205577168_08222025_BILL.pdf
Windstream_216713099_08272025_BILL.pdf
Windstream_2389882_08272025_BILL.pdf
```

2 of these are currently `dead_letter` under `--vision cassette` (default mode — no
recorded cassette entry for them): `_AP Invoice 32473 ... .pdf` and
`Windstream_2389882_08272025_BILL.pdf`. That's a test-infra limitation (offline replay has
nothing recorded for these two), not a persona bug. Leave them as-is unless told to record
a live cassette entry (costs real API calls — get sign-off first).

The wider pool at `all-docs/second-samples/<vendor>/` has more samples than what's copied
in (e.g. edco has 28 total, only 4 copied) if you need more to confirm a fix generalizes.

## New findings — not yet in any test or gold label

### Finding 1 — Veritiv `invoice_number` selector is hardcoded to one prefix (CONFIRMED BUG)

`src/docintel/packs/northstar/personas/veritiv.json:9-12`:
```json
{ "field": "invoice_number", "region": "header-block", "pattern": "(715-[0-9]{8})" }
```
The original single sample (`715-33905296`) starts with `715-`. Real invoices don't all:
3 of the 4 new samples are `689-`-prefixed (`689-37525600`, `689-37578305`,
`689-37584900`) and `invoice_number` comes back missing (`missing_required`) on all three.
The 4th (`715-33921625`) extracts correctly, which is exactly why this was invisible on a
single sample.

**Fix:** read what's actually printed on a `689-` invoice's header block (don't guess a
regex blind) and broaden the pattern to match the real structure rather than a literal
prefix. Verify against all 4 new veritiv files, not just the one that already worked.

### Finding 2 — Edco `vendor_account_number` selector is hardcoded to one prefix (CONFIRMED BUG)

`src/docintel/packs/northstar/personas/edco.json:13-18`:
```json
{ "field": "vendor_account_number", "anchor": "FOR BILLING INQUIRIES OR SERVICE,",
  "region": "any-page", "pattern": "(25-3A [0-9]{6})" }
```
Same shape of bug. All 4 new Edco invoices (`13307OCT25`, `15570AUG25`, `15570SEPT25`,
`159507OCT25`) come back missing this required field. Read the actual account-number
format on a couple of the new PDFs before writing a new pattern — do not assume `25-3A`
is the only prefix that occurs.

Note: Edco's `remit_address` selector (`edco.json:87-95`, anchor `"P.O. BOX 5488"`) is a
**separate, already-tracked** issue — it's the documented `ANCHOR_IN_VALUE_DEBT` entry
that Wave 2's Task 8c (nth-occurrence primitive) exists to fix. Don't duplicate that work
here; it's already scoped in the Wave 2 plan.

### Finding 3 — Windstream: near-total extraction collapse on 2 of 4 new invoices (NOT YET ROOT-CAUSED)

`Windstream_205577168_08222025_BILL.pdf` and `Windstream_216713099_08272025_BILL.pdf`
each extracted only 1 of ~12 fields, and that one field was garbled boilerplate text, not
real content. Both were tagged `page_role_fallback` (one also `promo_content`). These
bills are addressed to a different end customer (Golub Corporation, via what looks like an
MSP-managed account) than the original sample — the page-1 *layout*, not just the
customer name, may differ from what `windstream.json`'s selectors assume.

**This needs investigation before a fix, not a patch.** Start by reading both PDFs
directly and comparing page-1 structure against `windstream.json`'s `region`/`anchor`
values (`src/docintel/packs/digitaldirection/personas/windstream.json`). Two of the four
new Windstream samples *did* extract normally (`021942648`, and the dead-lettered
`2389882` is untested) — compare a working one against a broken one side by side.

### Finding 4 — Empirically confirms Wave 2's N1 (no new task — just raises its priority)

On this same Windstream batch, `bill_to_mismatch` never fired even though these bills are
addressed to a different company than our roster — because `windstream.json` has no
`bill_to_name` selector (one of the 5 personas called out in STATUS-SUMMARY §4.1). The one
document that extracted enough to reach the check simply came back with `bill_to_name`
empty, which happened to still route to `review` — but only by accident of a missing
required field, not because the wrong-inbox guard actually worked. Compare against
**Lumen** in this same batch, which *does* have a `bill_to_name` selector and correctly
raised `bill_to_mismatch` on both of its cross-customer invoices (`bill_to_name` extracted
as `"THE GOLUB CORPORATION"` / `"TOPS MARKETS LLC"`, basis `"printed"`).

No new task — this is Wave 2's existing N1 item (`_roster_match` needs a head-of-line
requirement). But do N1 **before** the rule-writing pass in the existing plan's §5
priority order — this is no longer a theoretical risk, it's reproduced on real data.

### Finding 5 — Edco arithmetic anomaly on 2 of 4 new invoices (minor, lowest priority)

`total_printed` doesn't equal `prior_balance + current_charges` on account `15570`'s two
consecutive months (`15570AUG25`, `15570SEPT25`), though the other two Edco accounts in
this batch compute correctly. Looks like a stray value is being picked up from elsewhere
on the page for this specific account. Investigate only after Findings 1–3 and the Wave 2
queue below.

## Recommended task order

1. **Finding 1** (Veritiv `invoice_number`) — isolated, low risk, quick.
2. **Finding 2** (Edco `vendor_account_number`) — isolated, low risk, quick.
3. **Wave 2, in the existing plan's specified order**: Task 7 → Task 8 → Task 2 → then
   Task 8c + N1 + N2 together (they share one re-baseline — see the plan for why). N1 is
   now higher-confidence-urgent per Finding 4 above.
4. **Finding 3** (Windstream layout investigation) — likely intersects Wave 2's 8c/N1
   re-baseline since it also touches `windstream.json`; sequence accordingly once you
   understand the root cause.
5. **Finding 5** (Edco arithmetic) — lowest priority, do last.
6. **N3** (gate's forced-review-vs-collapse ordering) and **N4** (identity-capture timing
   relative to `beforeEmit`) — small, low-risk, can be done whenever convenient.

## Worth raising with the user before doing (do not just do it)

We now have real second invoices for 7 of 10 vendors. Hand-labeling even a handful of the
26 already sitting in `docs/` would convert today's informal cross-check into permanent
regression coverage in the real 263-assertion scorecard. This is a real scope decision —
`docs/corpus/gold/*.json` is otherwise READ-ONLY per the plan's Global Constraints, and
hand-labeling is genuine effort, not a mechanical step. Confirm with the user before
adding to it.

## Standing constraints (from the existing Wave 2 plan — still apply, unchanged)

- `docs/corpus/gold/*.json` is READ-ONLY. A gold change requires re-reading the source PDF
  and a written justification.
- Never classify or extract from a filename.
- Corpus-only tests confirm corpus-fit, not corpus-overfit — every task that changes
  behaviour needs at least one synthetic fixture.
- No assertion may pass against an empty record (`tests/test_scorecard_coverage.py`,
  GUARDRAIL 3).
- **Baseline to hold or beat: 203/263 assertions, 1/10 documents green.** Get the live
  figure with `python3 -m docintel.cli replay-gold` — `.loop/scorecard.json` is stale, do
  not trust it.
- **Verify with:**
  `python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold`
- Commit after every task. One task, one commit, `type(scope): sentence` message style.
- Use `superpowers:test-driven-development` and `superpowers:subagent-driven-development`
  (or `executing-plans`) to work through this — the existing Wave 2 plan already follows
  that discipline; match it, don't deviate.
