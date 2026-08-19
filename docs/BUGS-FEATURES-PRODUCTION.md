# Document Intelligence — Bugs, Feature Plan & Production Plan

**Everything below is grounded in documents actually run through the real pipeline this session** — 4 purpose-built synthetic test PDFs, 3 real customer documents, and a 172-document real-world corpus sample. No claim here is theoretical; each one names the exact file, exact field, and exact code path involved.

---

## Part 1 — Synthetic stress test: do the rules generalize, or did they memorize?

Four PDFs were built from scratch, each using a **real shipped persona's actual anchors/labels**, but with dollar figures, dates, and account numbers **never seen during authoring**. The question each answers: does the extraction logic genuinely read the page, or does it only work on the exact training document?

### Test A — DTSS invoice, brand-new numbers

| Field | Result |
|---|---|
| `vendor_name`, `invoice_number`, `bill_to_name`, `payment_terms`, `total_printed` | ✅ Extracted correctly on entirely new values (`DT-990112`, `640.50`, etc.) |
| `amount_payable` (derived) | ✅ Correctly `640.50` — no prior balance, so payable = printed |
| `invoice_date` | ❌ **Missing.** The selector is region-only (`top-right`, no anchor) — my synthetic layout didn't place the date in the literal top-right quadrant. Correctly surfaced as `missing_required`, correctly routed to `review`. |
| `vendor_address` | 🐞 **Bug.** Captured almost the entire page — vendor address, invoice number, bill-to block, and payment terms all joined into one string, at **0.99 confidence**. |
| `bill_to_address` | 🐞 **Same bug.** Bled into the line-items table and the total line. |
| `line_items` | 🐞 **Same bug, table form.** A 4th, bogus row `{"description": "Total 640.50"}` was appended after the 3 real rows — the table-break detector didn't stop at the last real item. |

### Test B — Centracom, a brand-new F1 trap

New account number, new dates, new dollar figures (`prior_balance=45,678.90`, `current_charges=8,765.43`, `total_printed=54,444.33`), and a customer name in no roster.

| Result | |
|---|---|
| **`amount_payable = 8,765.43`, `payable_basis = "current_charges"`** | ✅ **This is the important one.** The F1 derivation logic correctly ignored the misleading printed total and derived the true payable amount — on numbers it has never seen. This is genuine generalization, not memorization. |
| `bill_to_mismatch` tag fired | ✅ Correct — an unrostered customer name correctly triggers the wrong-inbox guard. |
| `document_identity` fell back to `account_number\|bill_date` | ✅ Correct — no invoice number was printed, and the composite-identity fallback (F6) worked exactly as designed. |
| `vendor_address`, `bill_to_address` | 🐞 **Same overcapture bug as Test A** — both fields swallowed unrelated document content (account numbers, dates, charge lines) at 0.99 confidence. |

### Test C — EDCO, correctly *not* claimed

| Result | |
|---|---|
| `sender_fingerprint = "unknown\|unknown"`, tag `unclaimed_document` | ✅ **Confirmed correct, not a bug.** Verified directly against `northstar/classification.json`'s claim rule: Northstar's guard requires seeing **Northstar's own name/address** on the page (`"northstar recycling"`, `"po box 188 east longmeadow"`, etc.) — because this pack is Northstar's own AP department, and the guard's job is confirming "is this billed to us," not just "which vendor is this." My synthetic EDCO document never mentioned Northstar anywhere, so it was correctly left unclaimed. This is deliberate, documented design (the spec's own `_why` field cites a real 2026-08-07 incident this exact precision was tuned to prevent). |
| Fell through to Stage 5b (vision) | 🐞 **Dead-lettered** — same empty-cassette gap as every other unrecognized document this session. |

### Test D — Windstream, deliberately reworded labels

Same carrier, same document shape, but every label reworded (`Acct No:` instead of `Account number`, `Amount Due Now:` instead of `Total Amount Due`, etc.) — none of which match any registered anchor *or* `anchor_alt`.

| Result | |
|---|---|
| `vendor_name = "Windstream Enterprise"` | ✅ Correctly read (this one label happened to match). |
| Every money/date field | ❌ Correctly empty — no anchor matched, so nothing was guessed. |
| `amount_payable = null` | ✅ **Correct refusal** — with no `total_printed`, the F1 derivation correctly produced nothing rather than fabricating a value. |
| `lane = "low"`, `regen_flag = true` | ✅ Correct top-level outcome — this is exactly the "vendor redesigned their template" signal the gate is supposed to raise. |
| `remit_address` | 🐞 **Same overcapture bug, third occurrence** — garbled nonsense joining account number, dates, and charge amounts into one string. |
| **Stage 5b (vision) never triggered, despite 12 of 14 declared fields missing** | 🐞 **A real architectural gap, confirmed by reading the code directly** — see Bug #1 below. |

### The one clear pattern across all four tests

**The same failure mode appeared independently in three of four tests (A, B, D), on three different personas, on two different region types (`label-block`/`text_block` fields and a row-group table).** That repetition, not any single instance, is what makes it a confirmed bug rather than a fluke — see Bug #2.

---

## Part 2 — Full bug list (this session, consolidated)

Ranked by how much damage each one does, not by discovery order.

### Bug 1 — Vision escalation is blind to *how much* is missing, only to *how confident* what little exists is

**Severity: high — silently forgoes the one safety net designed for exactly this case.**

Confirmed by reading `pipeline/stages/s5b_vision.py` directly:

```python
def _collapsed(ctx: JobContext) -> bool:
    if not ctx.extracted.match_quality:
        return True
    weak = [q for q in ctx.extracted.match_quality.values() if q < COLLAPSE_THRESHOLD]
    return len(weak) >= 2
```

This only looks at the confidence of fields that *did* get a value. Test D populated only 2 of 14 declared fields, both confidently — so `_collapsed()` returns `False`, and the vision fallback (Stage 5b) never runs, even though **86% of the expected data is simply absent.** Meanwhile Stage 7 (the confidence gate) *does* look at coverage and correctly raises `regen_flag`. The result: the system correctly recognizes "these rules are broken for this document" but never actually attempts the one thing that could rescue this specific document in the meantime — because the two stages use two different definitions of "collapsed."

**Fix:** `_collapsed()` should also trigger on a coverage/miss-share basis (the same `core.coverage.Coverage.miss_share` the gate already computes), not confidence alone.

### Bug 2 — `label-block`/`text_block` region capture has no principled stopping point

**Severity: high — produces wrong data at full (0.99) confidence, not an honest miss.**

Confirmed independently in Test A (`vendor_address`, `bill_to_address`), Test B (`vendor_address`, `bill_to_address`), and Test D (`remit_address`) — three different personas, three different documents. In every case, the field meant to hold a short address instead absorbed several unrelated subsequent lines (account numbers, dates, charge amounts, even a line-items table).

This is the most dangerous class of bug in the whole system: unlike a missing field (which correctly triggers `missing_required` → review), a garbled-but-present field looks legitimate at a glance and carries full confidence. It's the same failure shape as the real garbled OCR address I found earlier on a genuine Lumen document (`"461 NOTT ST, SCHENECTADY NY 12308-1812, Bod fualggfAYE..."`) — meaning this isn't only a synthetic-test artifact; it has a live, confirmed real-world instance too.

**Fix:** the region's stopping heuristic needs a harder, more explicit boundary condition (e.g., stop at the first line matching a *different* declared anchor/label, not just a whitespace/pitch gap) rather than relying on geometric spacing that a slightly different real layout can easily fail to provide.

### Bug 3 — The row-group table-break detector has the same "keeps reading" failure mode

**Severity: medium — same root cause as Bug 2, smaller blast radius.**

Confirmed in Test A: a 4th, bogus line-item row (`{"description": "Total 640.50"}`, every other column null) was appended after the 3 real rows. The table-break heuristic (a gap exceeding a computed threshold based on median row pitch) didn't fire because the gap in my synthetic layout wasn't wide enough — again, a plausible real-world spacing choice could trigger the identical failure.

**Fix:** the same anchor-boundary approach as Bug 2 — a table should also stop at any line matching a *different* declared field's anchor, not rely on spacing alone.

### Bug 4 — The `pdfplumber` recursion crash (confirmed systemic, not a one-off)

**Severity: high for one entire document category.**

First found on a single real signed SD-WAN contract; confirmed across **15 of 172** real documents in the full corpus sample — every one of them a signed contract, order, or amendment. Root cause: `pdfplumber`'s `page.annots` property recursively resolves the PDF's internal object graph with no depth guard, and e-signature-tool-generated PDFs commonly have exactly the annotation structure that trips it.

The good news, confirmed: `RecursionError` is still caught by `Runner.process()`'s catch-all and degrades to a clean dead letter — the emit-always invariant held even here. The bad news: the given reason (`"maximum recursion depth exceeded"`) is the least actionable message of any dead-letter reason seen this session.

**Fix:** guard the `page.annots` call in `extract/pdf.py:read_meta()` specifically, catching `RecursionError` and falling back to `annot_count=0` rather than failing the whole document.

### Bug 5 — The vision fallback has never been exercised against a real model

**Severity: critical — this is the dominant real-world failure mode, by volume.**

Not new this session, but now quantified precisely: **138 of 172 real documents (80%)** and both Tests C and D above dead-lettered purely because the shipped vision cassette is empty (`{}`). Every one of these is an otherwise-correct "I don't recognize this vendor, let me try the AI fallback" path — that path has simply never been proven to work.

**Fix:** record one real cassette entry against a live Anthropic key and inspect the output by eye — see the Feature Plan.

### Bug 6 — Contracts/CSRs/amendments get misclassified as bills, quietly

**Severity: medium — produces low-value "processed" records that look plausible.**

Of 18 real documents that *did* process in the corpus sample, all but 2 were contracts, amendments, or Customer Service Records — none of which are bills — matched to a carrier's billing persona purely because the carrier's name appears on the page, then run through billing-shaped extraction (total-due, prior-balance logic) that has nothing to match. All 16 landed in the `low` lane, which is the correct symptom, but the root cause (this document type doesn't exist in the domain model at all) isn't visible anywhere in the record.

**Fix:** a real `contract` document type — see the Feature Plan.

### Bug 7 — A cross-platform test bug (already fully diagnosed, trivial fix)

**Severity: low.** `tests/extract/test_annotations.py:10` hardcodes a forward-slash path constant compared against a backslash-returning `glob()` result on Windows. The detection logic under test is correct; only the string comparison fails. One-line fix: normalize both sides with `os.path.normpath()` before comparing.

---

## Part 3 — Feature plan

In the order that unblocks the most value fastest.

1. **Fix the recursion crash (Bug 4).** Small, contained, unblocks an entire real document category (signed contracts/orders) from crashing at Stage 2.
2. **Record a real vision cassette (Bug 5).** The single highest-leverage item in the whole plan — resolves 80% of real-world dead letters and answers whether the fallback path is trustworthy at all.
3. **Harden `label-block`/`text_block` capture and the table-break detector (Bugs 2 & 3).** These fail *silently and confidently*, which is strictly worse than failing loudly — this is worth prioritizing above adding new features.
4. **Fix the vision-escalation collapse check to use coverage, not just confidence (Bug 1).** Small, precise change to `s5b_vision.py`'s `_collapsed()`.
5. **Add a real `contract` document type** — new classification signal, new field set (account/circuit ID, contracted rate, term start/end, signatory), reusing the exact same selector-grammar mechanism bills already use.
6. **Build the invoice-to-contract reconciliation layer** (as its own downstream consumer, not inside the fast lane) — cross-reference by `(carrier, account/circuit_id)`, flag `no_matching_contract` / `rate_mismatch` / `billed_after_contract_expiry`.
7. **Implement `soft_miss`** — Stage 4 currently only ever produces `hit`/`hard_miss`; a template that's drifted slightly (not absent, not identical) has no distinct handling today.
8. **Real-time, multi-document upload** — object storage → jobs table → upload API → worker pools (cheap + vision-rate-limited) → status streaming, exactly as previously designed, still pending.
9. **Build the rule-lifecycle agent** — deliberately last, since it needs a proven vision path (item 2) and real correction data to regenerate from.

---

## Part 4 — Production plan

1. **Fix the one failing test** (Bug 7) and stand up CI running the existing 1812 tests + ruff + mypy on every change.
2. **Swap the Flask dev server for a production WSGI server** (`gunicorn`/`waitress`) — Flask's own banner already warns against the dev server in production.
3. **Promote the persona store and duplicate index to shared, persistent storage** — required the moment there's more than one worker process (see the real-time plan).
4. **Add structured logging and alerting on the emit-always invariant** — currently the one guarantee the whole design rests on has no operational visibility if it ever breaks.
5. **Add auth to the web UI / upload API** the moment either is reachable beyond localhost.
6. **Containerize** with two entrypoints (`api`, `worker`) so the cheap and vision-bound worker pools can scale independently.
7. **Add a cost budget and concurrency cap around the vision adapter** before any real volume hits it — this only matters once item 2 above (recording a real cassette) proves the path is worth using at scale.

---

## What's still genuinely pending / unresolved

Being honest about what doesn't have a clean answer yet, even after everything above:

- **Multiple contracts per account over time** (renewals, amendments) — "latest wins" isn't correct; a real customer relationship in the test data (Golub Corporation) already has a 24-month contract, a 36-month contract, and several amendments layered on top of each other.
- **Cross-document ID matching** — an invoice may print an account number where a contract only prints a circuit ID or order number; there's no existing alias/roster mechanism for this the way there is for vendor names.
- **The recursion-crash fix is a real engineering decision, not just a patch** — work around `pdfplumber` locally, or report the issue upstream? Worth deciding deliberately given how common signed telecom paperwork is in this exact domain.
- **How aggressively to harden Bugs 2/3** — a stricter stopping rule reduces overcapture but risks new false negatives (a legitimately long address correctly cut short); this needs real before/after measurement against the gold corpus, not a blind tightening.
- **Whether "low + regen_flag" is sufficient signal for Bug 1's fix**, or whether a document that's mostly missing but confidently-so deserves its own distinct lane rather than being folded into the existing collapse path.
