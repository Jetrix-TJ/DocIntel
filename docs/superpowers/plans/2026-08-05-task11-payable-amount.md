# Task 11: The Payable Amount — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-enable `derive_amount_payable` so `derived.amount_payable` is populated
on every processed record, un-skip the two guardrail tests that keep the
derivation honest, and make the scorecard actually measure the new capability.

**Architecture:** `derive_amount_payable` and `resolve_carried_balance`
(`src/docintel/grammar/ops/derive.py`) are already fully implemented, unit-tested,
and registered in the op table (`src/docintel/grammar/ops/__init__.py`). They are
inert today only because no persona's `adjust` list names them. Re-enabling is a
pure **wiring change**: add the two op names to the `total_printed` selector's
`adjust` list in all 10 personas, re-register the `apply_prior_balance_basis`
hook both packs already ship (needed so `resolve_carried_balance` can determine
Centracom's and EDCO's carried balance instead of refusing), add an
`amount_payable` threshold to both packs, and un-skip the two guardrails. No
grammar, pipeline, or contract code changes.

**Tech Stack:** Python 3, pytest, the existing grammar/pack/scorecard modules.

## Global Constraints

- `docs/corpus/gold/*.json` is READ-ONLY. This task changes no gold file — the
  gold files already carry `derived.amount_payable`/`derived.payable_basis` for
  all 11 documents (added when the design doc's printed-fields-only narrowing
  deferred the field, specifically so the evidence for re-enabling stays on
  disk).
- **Baseline to hold or beat:** measure fresh with
  `python3 -m docintel.cli replay-gold` before Task 1 and record the number —
  do not trust a number from this plan or from `.loop/scorecard.json` (stale).
- **Verify with:**
  `python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold`
- Commit after every task. One task, one commit, `type(scope): sentence`
  message style, matching this repo's existing convention.
- Never guess a business fact. `apply_prior_balance_basis`'s convention tables
  already carry the two conventions this task needs (Centracom
  `net_of_payments`, EDCO `gross`) — do not add or change a table entry as part
  of this task.
- Scope boundary, stated so it is not accidentally widened: this task does
  **not** re-enable `infer_currency` or any `crosscheck_*` op, and does **not**
  add `prior_balance_basis` to `scorecard.CHECKED_FIELDS`. Registering
  `apply_prior_balance_basis` is required as a dependency of
  `resolve_carried_balance`, but scoring `fields.prior_balance_basis` itself is
  a separate, later widening — out of scope here.

---

## File Structure

- Modify: `src/docintel/packs/northstar/hooks.py`,
  `src/docintel/packs/digitaldirection/hooks.py` — register
  `apply_prior_balance_basis` at the `afterExtraction` socket.
- Modify: `src/docintel/packs/northstar/personas/*.json` (6 files: `edco`,
  `upak`, `veritiv`, `complete_beverage`, `dtss`, `federal_recycling`),
  `src/docintel/packs/digitaldirection/personas/*.json` (4 files: `centracom`,
  `windstream`, `comcast`, `lumen`) — add `resolve_carried_balance` and
  `derive_amount_payable` to the `total_printed` selector's `adjust` list.
- Modify: `src/docintel/packs/northstar/thresholds.py`,
  `src/docintel/packs/digitaldirection/thresholds.py` — add an
  `amount_payable` threshold.
- Modify: `src/docintel/scorecard.py` — widen `CHECKED_DERIVED`, re-verdict the
  relevant `GOLD_ASSERTION_COVERAGE` entries.
- Modify: `tests/test_f1_antiregression.py`, `tests/test_f1_centracom_trap.py` —
  remove the `pytest.mark.skip`.
- Modify: `tests/test_printed_fields_only_path.py` — replace the test that pins
  the pre-Task-11 behaviour with one pinning the post-Task-11 behaviour.
- Modify: `tests/test_scorecard_coverage.py` — shrink `DEFERRED_DERIVED_KEYS`.
- Test (new): `tests/pipeline/test_s6_capture.py` gains one test asserting
  `apply_prior_balance_basis` actually fires end-to-end (Task 1).

---

### Task 1: Re-register `apply_prior_balance_basis` in both packs

**Files:**
- Modify: `src/docintel/packs/northstar/hooks.py`
- Modify: `src/docintel/packs/digitaldirection/hooks.py`
- Test: `tests/pipeline/test_s6_capture.py`

**Interfaces:**
- Consumes: `packs.northstar.conventions.apply_prior_balance_basis(ctx: JobContext) -> JobContext`, `packs.digitaldirection.conventions.apply_prior_balance_basis(ctx: JobContext) -> JobContext` (both already implemented, unchanged by this task).
- Produces: nothing new — this task only adds a registration call, so `ctx.extracted["prior_balance_basis"]` becomes populated at runtime for documents with a known convention. No other task in this plan calls this function directly; Task 2's `resolve_carried_balance` reads the value through `ctx.extracted.get("prior_balance_basis")`, which is how it already reads everything else.

This task is deliberately isolated from Task 2: registering the hook alone changes
no scored assertion, because nothing yet reads `prior_balance_basis` except a
hook that has never run. It is safe to land and re-baseline on its own before
touching any persona's `adjust` list.

- [ ] **Step 1: Write the failing test**

Add to `tests/pipeline/test_s6_capture.py` (append to the end of the file):

```python
def test_apply_prior_balance_basis_fires_for_centracom_and_edco() -> None:
    """Task 11 prerequisite: resolve_carried_balance needs this hook's output.

    Registering the hook alone must not change any scored assertion - nothing
    yet reads `prior_balance_basis` except this hook itself - so this test
    checks the hook's own effect directly rather than through the scorecard.
    """
    import json
    import os

    from docintel.adapters.vision.fake import FakeVision
    from docintel.pipeline.stages import build_pipeline

    def _run(gold_id: str) -> dict:
        with open(os.path.join("docs", "corpus", "gold", f"{gold_id}.json")) as fh:
            gold = json.load(fh)
        runner = build_pipeline(FakeVision())
        return runner.process(
            document_id=gold["gold_id"],
            source_path=os.path.join("docs", gold["source_file"]),
        )

    centracom = _run("digitaldirection-centracom-0384043574")
    assert centracom["fields"]["prior_balance_basis"] == "net_of_payments"

    edco = _run("northstar-edco-077087")
    assert edco["fields"]["prior_balance_basis"] == "gross"
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python3 -m pytest tests/pipeline/test_s6_capture.py::test_apply_prior_balance_basis_fires_for_centracom_and_edco -v`
Expected: FAIL — `KeyError: 'prior_balance_basis'`, because the hook is not
registered yet.

- [ ] **Step 3: Register the hook in Northstar**

In `src/docintel/packs/northstar/hooks.py`:

1. Update the import at the top (currently `from docintel.packs.northstar import aliases, ladder, references`) to also import `conventions`:

```python
from docintel.packs.northstar import aliases, conventions, ladder, references
```

2. Add a thin hook wrapper next to `collect_references` (same file, after that
   function):

```python
def apply_billing_conventions(ctx: JobContext, next_: Next) -> JobContext:
    """Supply `prior_balance_basis` from the vendor's known convention (F1b)."""
    return next_(conventions.apply_prior_balance_basis(ctx))
```

3. In `register()`, add the new registration at `afterExtraction`, after
   `collect_references`:

```python
def register(registry: HookRegistry) -> None:
    registry.register("classifySignals", northstar_ladder, PACK_NAME)
    registry.register("beforePersonaLookup", resolve_vendor_fingerprint, PACK_NAME)
    registry.register("afterExtraction", collect_references, PACK_NAME)
    registry.register("afterExtraction", apply_billing_conventions, PACK_NAME)
```

4. Update the module docstring's table row (currently `| \`applyBillingConventions\` | deferred: supplies \`prior_balance_basis\`, a derived classification. \`conventions.py\` stays in the tree; see the printed-fields-only spec. |`) to:

```
| `applyBillingConventions` | **here**, at `afterExtraction` |
```

- [ ] **Step 4: Register the hook in Digital Direction**

In `src/docintel/packs/digitaldirection/hooks.py`:

1. Update the import:

```python
from docintel.packs.digitaldirection import aliases, conventions, ladder, references
```

2. Add the wrapper next to `collect_references`:

```python
def apply_billing_conventions(ctx: JobContext, next_: Next) -> JobContext:
    """Supply `prior_balance_basis` from the carrier's known convention (F1b)."""
    return next_(conventions.apply_prior_balance_basis(ctx))
```

3. Register it at `afterExtraction`, alongside `collect_references` and
   `refine_prior_balance_tags` (this pack registers `collect_references` at
   `beforeConfidenceGate`, not `afterExtraction` — see that function's
   docstring for why; the new hook goes at `afterExtraction` regardless,
   because `resolve_carried_balance` runs in Stage 6, after `afterExtraction`
   and before `beforeConfidenceGate`, so it needs the basis set by then):

```python
def register(registry: HookRegistry) -> None:
    registry.register("classifySignals", telecom_ladder, PACK_NAME)
    registry.register("beforePersonaLookup", resolve_carrier_fingerprint, PACK_NAME)
    registry.register("afterExtraction", apply_billing_conventions, PACK_NAME)
    registry.register("beforeConfidenceGate", refine_prior_balance_tags, PACK_NAME)
    registry.register("beforeConfidenceGate", collect_references, PACK_NAME)
```

4. Update the module docstring's line (currently `\`applyBillingConventions\` is deferred by the printed-fields-only narrowing: it supplies \`prior_balance_basis\`, a derived classification. The implementation stays in the tree (\`conventions.py\`).`) to:

```
`applyBillingConventions` is registered here, at `afterExtraction`. It
supplies `prior_balance_basis` from the carrier's known convention
(`conventions.py`), which `resolve_carried_balance` (Stage 6) needs.
```

- [ ] **Step 5: Run the test again to confirm it passes**

Run: `python3 -m pytest tests/pipeline/test_s6_capture.py::test_apply_prior_balance_basis_fires_for_centracom_and_edco -v`
Expected: PASS.

- [ ] **Step 6: Re-baseline**

Run: `python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 -m docintel.cli replay-gold`
Expected: **exactly the pre-Task-1 baseline, zero assertions flipped.** Nothing
yet reads `ctx.extracted.get("prior_balance_basis")` except the hook itself, so
`fields.prior_balance_basis` is not scored (it is not in `CHECKED_FIELDS`, by
this plan's own scope boundary) and no other field changes. If any assertion
moves, stop and investigate before committing — it means something already
depends on `prior_balance_basis` in a way this plan did not account for.

- [ ] **Step 7: Commit**

```bash
git add src/docintel/packs/northstar/hooks.py \
        src/docintel/packs/digitaldirection/hooks.py \
        tests/pipeline/test_s6_capture.py
git commit -m "feat(packs): re-register apply_prior_balance_basis in both packs

Task 11 prerequisite. resolve_carried_balance refuses to compute a carried
balance without prior_balance_basis, and Centracom/EDCO both print a prior
balance - so derive_amount_payable would refuse on exactly the two documents
this task cares about without this hook. Both packs' convention tables
already carry the right answer (Centracom net_of_payments, EDCO gross);
this only wires the lookup back in. Zero corpus assertions change: nothing
else reads prior_balance_basis yet."
```

---

### Task 2: Wire `resolve_carried_balance` + `derive_amount_payable` into all 10 personas, add the threshold, un-skip the guardrails

**Files:**
- Modify: `src/docintel/packs/northstar/personas/edco.json`
- Modify: `src/docintel/packs/northstar/personas/upak.json`
- Modify: `src/docintel/packs/northstar/personas/veritiv.json`
- Modify: `src/docintel/packs/northstar/personas/complete_beverage.json`
- Modify: `src/docintel/packs/northstar/personas/dtss.json`
- Modify: `src/docintel/packs/northstar/personas/federal_recycling.json`
- Modify: `src/docintel/packs/digitaldirection/personas/centracom.json`
- Modify: `src/docintel/packs/digitaldirection/personas/windstream.json`
- Modify: `src/docintel/packs/digitaldirection/personas/comcast.json`
- Modify: `src/docintel/packs/digitaldirection/personas/lumen.json`
- Modify: `src/docintel/packs/northstar/thresholds.py`
- Modify: `src/docintel/packs/digitaldirection/thresholds.py`
- Modify: `tests/test_f1_antiregression.py`
- Modify: `tests/test_f1_centracom_trap.py`
- Modify: `tests/test_printed_fields_only_path.py`

**Interfaces:**
- Consumes: `ops.OPS["resolve_carried_balance"]`, `ops.OPS["derive_amount_payable"]` (unchanged — already implemented and registered, see `src/docintel/grammar/ops/__init__.py`); `ops.ORDER` already places both correctly relative to each other and to `resolve_vendor_alias`/`resolve_bill_to_alias`, so declaration order inside each persona's `adjust` array does not matter.
- Produces: `derived.amount_payable` and `derived.payable_basis` on every processed record (previously absent).

The mechanism (`src/docintel/pipeline/stages/s6_capture.py::_apply_document_ops`)
collects every op name any selector in a persona lists under `adjust`, dedupes,
and runs them in `ops.ORDER` — so it is sufficient to add both names to the
existing `total_printed` selector's `adjust` array, matching where
`resolve_vendor_alias`/`resolve_bill_to_alias` already live on every persona.

- [ ] **Step 1: Write the failing tests — un-skip the two guardrails**

In `tests/test_f1_antiregression.py`, delete lines 18–22 (the
`pytestmark = pytest.mark.skip(...)` block) and the now-unused `import pytest`
if nothing else in the file needs it (check: it does not — the file has no
other `pytest.` usage).

In `tests/test_f1_centracom_trap.py`, delete lines 34–38 (the same
`pytestmark = pytest.mark.skip(...)` block). Keep the `import pytest` — the
file still uses `@pytest.fixture`.

- [ ] **Step 2: Run them, with different expectations for each file**

Run: `python3 -m pytest tests/test_f1_antiregression.py -v`
Expected: **PASS, all 3 tests, immediately.** This file calls
`derive_amount_payable`/`resolve_carried_balance` directly as plain functions
on a synthetic context (see its `_centracom()` fixture) — it never goes through
a persona's `adjust` list, so it does not depend on Step 3 below at all. The
ops themselves were already correct before this plan started; un-skipping this
file only removes a stale gate on already-passing logic. A pass here is the
expected, correct result — not a sign the step was unnecessary.

Run: `python3 -m pytest tests/test_f1_centracom_trap.py -v`
Expected: **FAIL.** This file runs the real pipeline
(`build_pipeline(FakeVision())`) over the actual Centracom gold PDF, so it
*does* depend on Step 3's persona wiring. Expect
`KeyError: 'amount_payable'` (or a `TypeError` reading `None` as a `Decimal`)
until Step 3 lands.

- [ ] **Step 3: Add `resolve_carried_balance` and `derive_amount_payable` to all 10 personas**

Each file's `total_printed` selector currently ends its `adjust` array with
`resolve_vendor_alias`/`resolve_bill_to_alias` (or, for `windstream` and
`federal_recycling`, `resolve_bill_to_alias` alone, since neither declares a
`vendor_name` selector needing alias resolution on `total_printed`). Add the
two new names; final order inside the array does not matter (`ops.ORDER` fixes
runtime order), so append them.

**`src/docintel/packs/northstar/personas/edco.json`** — `total_printed` selector:
```json
{
  "field": "total_printed",
  "region": "header-block",
  "pattern": "currency",
  "adjust": [
    "resolve_vendor_alias",
    "resolve_bill_to_alias",
    "resolve_carried_balance",
    "derive_amount_payable"
  ]
}
```
Also update the persona's `notes` field (currently starts `"THE F1 TRAP. 367.96 is printed in the largest box on the page; the payable is 69.62. Under printed-fields-only this persona emits the printed 367.96 and says nothing about the 69.62 - the gap is downstream's to catch. prior_balance_basis WOULD come from the pack's billing-convention table..."`) to drop the now-false "says nothing about the 69.62" / "WOULD come from" framing:
```
"THE F1 TRAP. 367.96 is printed in the largest box on the page; the payable is 69.62. derive_amount_payable and resolve_carried_balance are wired on total_printed (Task 11); prior_balance_basis comes from the pack's billing-convention table via apply_billing_conventions, registered at afterExtraction."
```

**`src/docintel/packs/northstar/personas/upak.json`** — `total_printed` selector:
```json
{
  "field": "total_printed",
  "region": "totals-block",
  "pattern": "currency",
  "adjust": [
    "resolve_vendor_alias",
    "resolve_bill_to_alias",
    "resolve_carried_balance",
    "derive_amount_payable"
  ]
}
```
Also update the persona's `notes` field (currently ends `"...the aging all zero, nothing on the page explaining the 48.92 - is DEFERRED under printed-fields-only: derive_amount_payable is in no adjust list, so this persona no longer produces amount_payable at all, null or otherwise. The refusal logic and its unit tests are still on disk."`) to:
```
"...the aging all zero, nothing on the page explaining the 48.92 - derive_amount_payable is wired (Task 11) and correctly REFUSES on this document (F8): total_printed and please_pay disagree with nothing on the page explaining it, so derived.amount_payable is null and payable_basis is null, matching gold."
```

**`src/docintel/packs/northstar/personas/veritiv.json`** — `total_printed` selector:
```json
{
  "field": "total_printed",
  "anchor": "Total Amount Due",
  "region": "near-anchor",
  "pattern": "currency",
  "adjust": [
    "resolve_vendor_alias",
    "resolve_bill_to_alias",
    "resolve_carried_balance",
    "derive_amount_payable"
  ]
}
```

**`src/docintel/packs/northstar/personas/complete_beverage.json`** — `total_printed` selector:
```json
{
  "field": "total_printed",
  "anchor": "BALANCE DUE",
  "region": "same-row",
  "pattern": "currency",
  "adjust": [
    "resolve_vendor_alias",
    "resolve_bill_to_alias",
    "resolve_carried_balance",
    "derive_amount_payable"
  ]
}
```

**`src/docintel/packs/northstar/personas/dtss.json`** — `total_printed` selector:
```json
{
  "field": "total_printed",
  "anchor": "Total",
  "region": "near-anchor",
  "pattern": "currency",
  "adjust": [
    "resolve_vendor_alias",
    "resolve_bill_to_alias",
    "resolve_carried_balance",
    "derive_amount_payable"
  ]
}
```

**`src/docintel/packs/northstar/personas/federal_recycling.json`** — `total_printed` selector:
```json
{
  "field": "total_printed",
  "anchor": "Total Amt.",
  "region": "same-row",
  "pattern": "currency",
  "adjust": [
    "resolve_bill_to_alias",
    "resolve_carried_balance",
    "derive_amount_payable"
  ]
}
```

**`src/docintel/packs/digitaldirection/personas/centracom.json`** — `total_printed` selector:
```json
{
  "field": "total_printed",
  "anchor": "Total Amount Due",
  "region": "near-anchor",
  "pattern": "currency",
  "adjust": [
    "resolve_vendor_alias",
    "resolve_bill_to_alias",
    "resolve_carried_balance",
    "derive_amount_payable"
  ]
}
```

**`src/docintel/packs/digitaldirection/personas/windstream.json`** — `total_printed` selector:
```json
{
  "field": "total_printed",
  "anchor": "Total Amount Due",
  "anchor_alts": [
    "TOTAL INVOICE AMOUNT"
  ],
  "region": "near-anchor",
  "pattern": "currency",
  "adjust": [
    "resolve_bill_to_alias",
    "resolve_carried_balance",
    "derive_amount_payable"
  ]
}
```

**`src/docintel/packs/digitaldirection/personas/comcast.json`** — `total_printed` selector:
```json
{
  "field": "total_printed",
  "anchor": "Amount due",
  "region": "near-anchor",
  "pattern": "currency",
  "adjust": [
    "resolve_vendor_alias",
    "resolve_bill_to_alias",
    "resolve_carried_balance",
    "derive_amount_payable"
  ]
}
```

**`src/docintel/packs/digitaldirection/personas/lumen.json`** — `total_printed` selector:
```json
{
  "field": "total_printed",
  "anchor": "Total Amount Due",
  "region": "near-anchor",
  "pattern": "currency",
  "adjust": [
    "resolve_vendor_alias",
    "resolve_bill_to_alias",
    "resolve_carried_balance",
    "derive_amount_payable"
  ]
}
```

- [ ] **Step 4: Add the `amount_payable` threshold to both packs**

`tests/packs/test_registry.py::test_pack_thresholds_cover_the_fields_that_decide_payment`
now activates for both packs (every persona in both packs calls
`derive_amount_payable` after Step 3), and requires `thresholds["amount_payable"] >= 0.95`
and `>= thresholds["total_printed"]`.

In `src/docintel/packs/northstar/thresholds.py`, add to `THRESHOLDS` (after the
existing `"total_printed": 0.95,` line, in the same comment group):
```python
    # The derived payable. Held at the same bar as total_printed - a wrong
    # payable is a wrong payment however it was reached (Task 11).
    "amount_payable": 0.95,
```

In `src/docintel/packs/digitaldirection/thresholds.py`, add to `THRESHOLDS`
(after `"total_printed": 0.93,`):
```python
    # The derived payable. Held higher than total_printed on purpose: this is
    # the pack where a wrong payable is a $20,123.80 error (Centracom), so the
    # derivation is trusted no less than the total it is composed from plus
    # the arithmetic itself (Task 11).
    "amount_payable": 0.95,
```

- [ ] **Step 5: Rewrite the test that pins the pre-Task-11 behaviour**

In `tests/test_printed_fields_only_path.py`, replace
`test_centracom_emits_the_printed_total_not_the_payable` (lines 106–124) with:

```python
def test_centracom_emits_the_derived_payable(centracom_record: dict) -> None:
    """Task 11: the printed total and the derived payable now BOTH appear.

    Centracom prints 33,876.40 and is payable 13,752.60. Before Task 11 the
    pipeline transcribed the printed figure and said nothing about the
    payable; the derivation is now wired, so both are on the record and they
    legitimately disagree - that disagreement is the whole point of F1.

    If this ever starts asserting `"amount_payable" not in centracom_record["derived"]`
    again, derivation was un-wired without reverting GUARDRAIL 2
    (`test_f1_antiregression.py`) and GUARDRAIL 6 (`test_f1_centracom_trap.py`)
    back to skipped - do that together, not this test alone.
    """
    assert centracom_record["fields"]["total_printed"] == "33876.40"
    assert centracom_record["derived"]["amount_payable"] == "13752.60"
    assert centracom_record["derived"]["payable_basis"] == "current_charges"
```

Also update `RETAINED_DERIVED` (line 43) — `amount_payable` and `payable_basis`
are no longer `DERIVED_ONLY` names this module's own `_leaked()` check should
flag as leaking, since they are now the intended, wired output:

```python
RETAINED_DERIVED = {"document_identity", "identity_basis", "amount_payable", "payable_basis"}
```

- [ ] **Step 6: Run the full re-baseline**

Run:
```bash
python3 -m pytest -q
python3 -m mypy
ruff check src tests
python3 docs/corpus/validate_gold.py
python3 -m docintel.cli replay-gold
```

Expected, against the 287-assertion/11-document corpus (current baseline —
re-confirm the exact starting number by running `replay-gold` before this step
if any other change has landed since): the scorecard **rises**, since
`derived.amount_payable`/`derived.payable_basis` are not yet asserted (that is
Task 3) — so this step's `replay-gold` number should be **unchanged from the
Task-1 baseline**; the two guardrail files' tests are what move, from skipped
to passing. Confirm explicitly:

```bash
python3 -m pytest tests/test_f1_antiregression.py tests/test_f1_centracom_trap.py tests/test_printed_fields_only_path.py tests/packs/test_registry.py -v
```
Expected: all pass, 0 skipped in the first two files (previously all skipped).

If `replay-gold`'s total moves, stop and investigate: at this step nothing yet
reads `derived.amount_payable` from the scorecard side, so a moved assertion
means the derivation changed some *other* field's value unexpectedly (check
`current_charges`/`total_printed` on the 10 documents this touches first).

- [ ] **Step 7: Commit**

```bash
git add src/docintel/packs/northstar/personas/edco.json \
        src/docintel/packs/northstar/personas/upak.json \
        src/docintel/packs/northstar/personas/veritiv.json \
        src/docintel/packs/northstar/personas/complete_beverage.json \
        src/docintel/packs/northstar/personas/dtss.json \
        src/docintel/packs/northstar/personas/federal_recycling.json \
        src/docintel/packs/digitaldirection/personas/centracom.json \
        src/docintel/packs/digitaldirection/personas/windstream.json \
        src/docintel/packs/digitaldirection/personas/comcast.json \
        src/docintel/packs/digitaldirection/personas/lumen.json \
        src/docintel/packs/northstar/thresholds.py \
        src/docintel/packs/digitaldirection/thresholds.py \
        tests/test_f1_antiregression.py \
        tests/test_f1_centracom_trap.py \
        tests/test_printed_fields_only_path.py
git commit -m "feat(packs): re-enable derive_amount_payable on all 10 personas

Task 11. Wires resolve_carried_balance + derive_amount_payable into every
persona's total_printed selector - the op itself and its guardrails
(test_f1_antiregression.py, test_f1_centracom_trap.py) were already fully
implemented and unit-tested, just unreferenced by any adjust list since the
printed-fields-only narrowing. Un-skips both guardrails. Adds the
amount_payable threshold both packs' pack-thresholds guard now requires.
derived.amount_payable is not yet scored by the corpus scorecard - that is
the next commit."
```

---

### Task 3: Widen the scorecard to measure `amount_payable`/`payable_basis`

**Files:**
- Modify: `src/docintel/scorecard.py`
- Modify: `tests/test_scorecard_coverage.py`

**Interfaces:**
- Consumes: `scorecard.CHECKED_DERIVED: tuple[str, ...]`, `scorecard.GOLD_ASSERTION_COVERAGE: dict[str, str]` (existing module-level tables, unchanged shape).
- Produces: nothing new — this task only changes which gold-derived keys the existing `assertions_for()` loop (`scorecard.py:579-585`) turns into scored `Assertion` objects.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_scorecard_coverage.py`, after
`test_every_gold_derived_key_is_asserted_or_explicitly_deferred` (around line 452):

```python
def test_amount_payable_and_payable_basis_are_asserted() -> None:
    """Task 11: the scorecard must actually measure the newly-wired capability.

    Re-enabling derive_amount_payable without widening CHECKED_DERIVED would
    make the pipeline compute the right answer while the scorecard kept
    silently ignoring it - the exact class of blind spot this file exists to
    catch (see the module docstring).
    """
    from docintel.scorecard import CHECKED_DERIVED

    assert "amount_payable" in CHECKED_DERIVED
    assert "payable_basis" in CHECKED_DERIVED
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python3 -m pytest tests/test_scorecard_coverage.py::test_amount_payable_and_payable_basis_are_asserted -v`
Expected: FAIL — `AssertionError: assert 'amount_payable' in ('document_identity', 'identity_basis')`.

- [ ] **Step 3: Widen `CHECKED_DERIVED`**

In `src/docintel/scorecard.py`, replace line 234–238:

```python
# `amount_payable` and `payable_basis` left with the printed-fields-only
# narrowing. These two stay because core/contract.py requires their PRESENCE on
# every processed record - they are provenance, not a claim about what the
# document printed.
CHECKED_DERIVED = ("document_identity", "identity_basis")
```

with:

```python
# `document_identity`/`identity_basis` stay because core/contract.py requires
# their PRESENCE on every processed record - they are provenance, not a claim
# about what the document printed. `amount_payable`/`payable_basis` re-joined
# this tuple in Task 11: both are now wired on every persona
# (grammar/ops/derive.py::derive_amount_payable), and gold already carries the
# expected answer for all 11 documents.
CHECKED_DERIVED = ("document_identity", "identity_basis", "amount_payable", "payable_basis")
```

- [ ] **Step 4: Re-verdict the `GOLD_ASSERTION_COVERAGE` entries this newly covers**

In `src/docintel/scorecard.py`, replace lines 268–284:

```python
    # -- the payable, and the arithmetic behind it (F1, F1b, F8) -------------
    # Every entry down to `prior_balance_is_net` asserts a DERIVED value or an
    # arithmetic closure, so all of them are deferred together. The gold files
    # still record the answers; only the expectation is retired.
    "amount_payable": DEFERRED_REASON,
    "amount_payable_is_null": DEFERRED_REASON,
    "payable_basis": DEFERRED_REASON,
    "payable_mismatch": DEFERRED_REASON,
    "payable_composition": DEFERRED_REASON,
    "balance_composition": DEFERRED_REASON,
    "prior_balance_found_and_cleared": DEFERRED_REASON,
    "total_composition": DEFERRED_REASON,
    "current_charges_composition": DEFERRED_REASON,
    "new_charges_composition": DEFERRED_REASON,
    "line_sum": DEFERRED_REASON,
    "line_extended": DEFERRED_REASON,
    "arith_balance_mismatch_applied": DEFERRED_REASON,
```

with:

```python
    # -- the payable (F1, F8) — wired in Task 11 -----------------------------
    # All three check names are observations of the SAME record value,
    # derived.amount_payable: a correct payable, a correctly-null payable
    # (U-PAK's F8 refusal), and a mismatched pair that also produces a null
    # payable. One assertion measures all three; nothing further to wire.
    "amount_payable": "wired:derived.amount_payable",
    "amount_payable_is_null": "wired:derived.amount_payable",
    "payable_basis": "wired:derived.payable_basis",
    "payable_mismatch": "wired:derived.amount_payable",
    # Arithmetic compositions whose every input is independently asserted
    # elsewhere (current_charges, prior_balance, total_printed all in
    # CHECKED_FIELDS; amount_payable now in CHECKED_DERIVED) but whose
    # composition itself has no separate observable on the record - same
    # class as `every_line_qty_times_price` below.
    "payable_composition": "documentation",
    "balance_composition": "documentation",
    # -- the arithmetic Task 11 does NOT wire (crosscheck_* ops, infer_currency,
    # still deferred) ---------------------------------------------------------
    "prior_balance_found_and_cleared": DEFERRED_REASON,
    "total_composition": DEFERRED_REASON,
    "current_charges_composition": DEFERRED_REASON,
    "new_charges_composition": DEFERRED_REASON,
    "line_sum": DEFERRED_REASON,
    "line_extended": DEFERRED_REASON,
    "arith_balance_mismatch_applied": DEFERRED_REASON,
```

Leave `prior_balance_is_net` (line ~289) and everything from `currency_inferred`
onward untouched — both depend on capabilities out of this task's scope
(`prior_balance_basis` field-level scoring, `infer_currency`).

- [ ] **Step 5: Shrink `DEFERRED_DERIVED_KEYS` in the coverage test**

In `tests/test_scorecard_coverage.py`, replace line 46–49:

```python
# Gold `derived` keys the printed-fields-only narrowing retired. Both are
# DERIVED_ONLY names; the gold files still record their answers, so the evidence
# for re-enabling stays on disk and this list is what points at it.
DEFERRED_DERIVED_KEYS = frozenset({"amount_payable", "payable_basis"})
```

with:

```python
# Gold `derived` keys the printed-fields-only narrowing retired. Empty since
# Task 11 re-enabled both of DERIVED_ONLY's non-identity names. Kept as a
# named, typed constant (rather than deleted) so a future deferral has an
# obvious place to add a key, and so `test_the_deferred_derived_list_holds_only_derived_only_names`
# keeps meaning something.
DEFERRED_DERIVED_KEYS: frozenset[str] = frozenset()
```

- [ ] **Step 6: Update `test_no_derived_only_field_is_asserted_by_the_scorecard`**

In `tests/test_scorecard_coverage.py`, this test (around line 193–207) currently
asserts that no `DERIVED_ONLY` name outside `{"document_identity", "identity_basis"}`
is ever asserted. `amount_payable`/`payable_basis` are `DERIVED_ONLY` names and
are now intentionally asserted (Step 3), so the `retained` set must grow to
match — otherwise this test now correctly fails, since it is doing its job.
Change line 203:

```python
    retained = {"document_identity", "identity_basis"}
```

to:

```python
    retained = {"document_identity", "identity_basis", "amount_payable", "payable_basis"}
```

Update the function's docstring too (it currently says `` `document_identity`
and `identity_basis` are the exception and stay``) to:

```python
    """`document_identity`/`identity_basis` are Stage 8 contract keys carrying
    pipeline provenance, required to be PRESENT by core/contract.py.
    `amount_payable`/`payable_basis` are the other two names DERIVED_ONLY has
    ever held, and Task 11 wired them back into the scorecard on purpose -
    both are exceptions for a reason, not by oversight.
    """
```

- [ ] **Step 7: Run every scorecard-coverage test and the new assertion test**

Run: `python3 -m pytest tests/test_scorecard_coverage.py -v`
Expected: all pass, including
`test_amount_payable_and_payable_basis_are_asserted`,
`test_every_verdict_is_one_of_the_four_kinds`,
`test_the_coverage_table_has_no_stale_entries`,
`test_every_deferred_verdict_names_this_spec`, and
`test_the_deferred_derived_list_holds_only_derived_only_names` (trivially true
of an empty set).

If `test_every_verdict_is_one_of_the_four_kinds` fails on a new verdict
string, the prefix is wrong — verdicts must start with one of `covered:`,
`wired:`, `documentation`, `deferred:` (no trailing content required after
`documentation`).

- [ ] **Step 8: Full re-baseline and record the new numbers**

Run:
```bash
python3 -m pytest -q
python3 -m mypy
ruff check src tests
python3 docs/corpus/validate_gold.py
python3 -m docintel.cli replay-gold
```

Expected: the assertion **denominator rises** (up to 2 new assertions per gold
document that carries both `derived.amount_payable` and `derived.payable_basis`
— all 11 do, per the investigation: U-PAK's is `null`/`null`, everyone else is a
real value/basis pair) and the **numerator rises by the same amount on every
document except any where the derivation produces a wrong answer** — expect
zero wrong answers, since `derive_amount_payable`'s logic was already fully
unit-tested and unchanged by this plan; Task 1/2 only wired existing, correct
logic in. Record the exact before/after numbers in the commit message — do not
round or estimate them.

- [ ] **Step 9: Commit**

```bash
git add src/docintel/scorecard.py tests/test_scorecard_coverage.py
git commit -m "feat(scorecard): measure derived.amount_payable and payable_basis

Task 11, final step. Re-enabling the derivation (previous commit) without
this would leave the pipeline computing the right answer while the
scorecard kept silently ignoring it. Widens CHECKED_DERIVED, re-verdicts
the six affected GOLD_ASSERTION_COVERAGE entries from deferred to
wired/documentation, and empties DEFERRED_DERIVED_KEYS now that both
DERIVED_ONLY names it tracked are asserted again.

<record the exact replay-gold before -> after numbers here>"
```

---

## Eng review: test coverage of every codepath this plan adds

```
[+] hooks.py::apply_billing_conventions (both packs)   (Task 1, direct test)
[+] personas/*.json adjust wiring                       (Task 2, guardrails 2+6 + full re-baseline)
[+] thresholds.py amount_payable entries                 (Task 2, test_registry.py's dormant invariant)
[+] scorecard.py CHECKED_DERIVED / GOLD_ASSERTION_COVERAGE (Task 3, direct test + coverage guardrails)
```

## Eng review: what already exists and is NOT touched by this plan

| Component | Why untouched |
|---|---|
| `grammar/ops/derive.py::derive_amount_payable`, `resolve_carried_balance` | Already fully implemented and unit-tested; this plan only wires existing, correct logic in |
| `packs/*/conventions.py` | Already correct (Centracom `net_of_payments`, EDCO `gross`); this plan only registers the hook that calls it |
| `core/contract.py`, `core/models.py::DERIVED_ONLY` | `amount_payable`/`payable_basis` were always reserved names; no schema change needed |

## Eng review: NOT in scope

| Item | Where it belongs |
|---|---|
| Scoring `fields.prior_balance_basis` (adding it to `CHECKED_FIELDS`) | A later, separate widening — see this plan's Global Constraints |
| Re-enabling `infer_currency`, any `crosscheck_*` op | Separate deferred capabilities, not part of "the payable amount" |
| Confidence recalibration (Task 10 in the Wave 3 plan) | Explicitly sequenced after this task in the user's own priority order — Task 10's own framing says bands should be re-measured after this kind of change lands |

## Self-Review

**Placeholder scan.** Every step carries real, current file content (read live
from the repo during planning) and a real diff — no "add appropriate handling"
steps. The one place a number is deliberately left open is Task 3 Step 9's
commit message, which requires running `replay-gold` and recording the actual
output — that is not a placeholder, it is a value that can only exist after
running the step immediately before it.

**Type consistency.** `apply_prior_balance_basis(ctx: JobContext) -> JobContext`
is used with that exact signature in both packs' `conventions.py` (unchanged)
and both packs' new `hooks.py` wrapper (Task 1). `CHECKED_DERIVED: tuple[str, ...]`
and `DEFERRED_DERIVED_KEYS: frozenset[str]` keep their existing declared types
across Task 3.

**Sequencing risk.** Task 2 depends on Task 1 landing first — without the hook
registered, `resolve_carried_balance` refuses on Centracom and EDCO (both print
a `prior_balance`), which would make Task 2's guardrail tests fail for a
different reason than the one they exist to catch. Task 3 depends on Task 2 —
widening `CHECKED_DERIVED` before any persona produces `derived.amount_payable`
would make every document's new assertion fail (expected `None` vs whatever a
still-unwired op returns), corrupting the baseline. The plan's task order is
load-bearing; do not reorder or parallelize these three tasks.

## GSTACK REVIEW REPORT

Not run — this plan was authored directly against live repository state (all
file contents, line numbers, and test names read fresh during planning, not
recalled from an earlier report) and reviewed against the spec documents it
depends on (`docs/superpowers/specs/2026-07-28-printed-fields-only-design.md`,
`docs/superpowers/plans/2026-07-29-weakness-remediation.md` Task 11).
