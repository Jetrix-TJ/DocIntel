# Printed Fields Only — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Narrow both packs' extraction scope to values printed on the document, deferring all derived work without deleting it.

**Architecture:** Six tasks, ordered so the tree is green after every one. The grammar gains a `REQUIRED_ANY_OF` group mechanism first; the scorecard's derived *expectations* are retired next; then each pack's field sets, personas and hooks are narrowed; then the vendor-name-from-sender path; then whole-path tests and docs. Every derived module and its unit tests stay on disk — only wiring, field sets and scorecard verdicts change.

**Tech Stack:** Python 3, pytest, mypy, ruff. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-28-printed-fields-only-design.md`

## Global Constraints

- **`docs/corpus/gold/*.json` is READ-ONLY.** A test byte-compares all ten every run. Never edit a gold file in this plan.
- **Never delete a derived module or its unit tests.** Deferred means unregistered and unasserted, not removed. `grammar/ops/derive.py`, `grammar/ops/crosscheck.py` and both packs' `conventions.py` stay exactly as they are.
- **`core/models.py:DERIVED_ONLY` keeps all five entries** — `amount_payable`, `payable_basis`, `document_identity`, `identity_basis`, `carried_balance`. The names stay reserved so no selector can ever target them.
- **`derive_document_identity` stays wired.** `core/contract.py:140-149` requires the *presence* of `document_identity` and `identity_basis` on every processed record. Removing it raises `ContractError` on all ten documents and breaks `count(intaken) == count(emitted)`.
- **Verification command**, run at the end of every task — all four must be clean:
  ```bash
  python3 -m pytest -q && python3 -m mypy && ruff check src tests \
    && python3 docs/corpus/validate_gold.py
  ```
- `python3 -m docintel.cli replay-gold` **exits 1 while any document fails**. That is expected, not a broken build. Read its printed score, don't gate on its exit code.
- Money is `Decimal` throughout, never `float`.
- Commit after every task.

---

### Task 1: `REQUIRED_ANY_OF` and the V13 any-of clause

The field spec says "**any** parseable date" and "**at least one** money amount". V13 checks set membership, which cannot express either. Encoding the literal names would make EDCO unwritable (it prints a billing date and no invoice date) and every vendor printing no parseable total unwritable too.

Nothing consumes the new mechanism in this task. It is additive, and the tree stays green.

**Files:**
- Modify: `src/docintel/grammar/schema.py` (the `Pack` Protocol, around line 109)
- Modify: `src/docintel/grammar/validator.py:321-338` (`_check_required_coverage`)
- Modify: `src/docintel/packs/registry.py:72-74` (the registry's structural protocol)
- Modify: `src/docintel/packs/northstar/__init__.py`, `src/docintel/packs/digitaldirection/__init__.py` (satisfy the protocol)
- Modify: `src/docintel/packs/northstar/fields.py`, `src/docintel/packs/digitaldirection/fields.py` (empty tuple for now)
- Modify: `tests/grammar/test_validator.py:48` (the test double)
- Test: `tests/grammar/test_validator.py`

**Interfaces:**
- Produces: `Pack.required_any_of(doc_type: str) -> tuple[frozenset[str], ...]` — each group needs at least one covered member. Empty tuple means no any-of requirement. Tasks 3 and 4 populate it.
- Produces: `fields.REQUIRED_ANY_OF: tuple[frozenset[str], ...]` and `fields.required_any_of(doc_type) -> tuple[frozenset[str], ...]` in both packs.

- [ ] **Step 1: Write the failing tests**

Add to `tests/grammar/test_validator.py`. The existing test double at line 48 needs the new method — add it there first so these tests can construct a pack.

```python
def test_v13_any_of_passes_when_one_group_member_is_covered() -> None:
    """EDCO's shape: a bill_date selector and no invoice_date."""
    pack = FakePack(
        fields={"bill_date", "invoice_date", "total_printed"},
        required=frozenset(),
        any_of=(frozenset({"invoice_date", "bill_date"}),),
    )
    persona = {
        "status": "active",
        "doc_type": "standard_invoice",
        "field_selectors": [
            {"field": "bill_date", "region": "top-right", "pattern": "date"},
        ],
    }
    validate_persona(persona, pack)  # must not raise


def test_v13_any_of_fails_when_no_group_member_is_covered() -> None:
    pack = FakePack(
        fields={"bill_date", "invoice_date", "total_printed"},
        required=frozenset(),
        any_of=(frozenset({"invoice_date", "bill_date"}),),
    )
    persona = {
        "status": "active",
        "doc_type": "standard_invoice",
        "field_selectors": [
            {"field": "total_printed", "region": "first-page", "pattern": "currency"},
        ],
    }
    with pytest.raises(ValidationError, match="any of"):
        validate_persona(persona, pack)


def test_v13_any_of_is_skipped_for_draft_personas() -> None:
    pack = FakePack(
        fields={"invoice_date", "bill_date"},
        required=frozenset(),
        any_of=(frozenset({"invoice_date", "bill_date"}),),
    )
    persona = {"status": "draft", "doc_type": "standard_invoice", "field_selectors": []}
    validate_persona(persona, pack)  # must not raise


def test_v13_any_of_group_of_only_derived_names_is_not_a_trap() -> None:
    """A group whose every member is derived-only cannot be satisfied by any
    selector, so it must be skipped rather than making the persona unwritable —
    the same reasoning that exempts derived-only names from flat REQUIRED."""
    pack = FakePack(
        fields={"total_printed"},
        required=frozenset(),
        any_of=(frozenset({"amount_payable", "carried_balance"}),),
    )
    persona = {
        "status": "active",
        "doc_type": "standard_invoice",
        "field_selectors": [
            {"field": "total_printed", "region": "first-page", "pattern": "currency"},
        ],
    }
    validate_persona(persona, pack)  # must not raise
```

Update the existing test double so it accepts the new argument. Find `FakePack` near `tests/grammar/test_validator.py:48` and add:

```python
    def __init__(
        self,
        fields: set[str],
        required: frozenset[str] = frozenset(),
        derived_only: frozenset[str] = frozenset(),
        any_of: tuple[frozenset[str], ...] = (),
    ) -> None:
        self._fields = frozenset(fields)
        self._required = required
        self._derived_only = derived_only
        self._any_of = any_of

    def required_any_of(self, doc_type: str) -> tuple[frozenset[str], ...]:
        return self._any_of
```

Keep the existing `fields_for` / `required_fields` / `derived_only_fields` / `adjust_ops` methods as they are, returning the stored values. If the current double takes different constructor arguments, preserve every existing call site — read the whole class before editing it.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m pytest tests/grammar/test_validator.py -k any_of -v
```

Expected: FAIL. The first two fail because no any-of clause exists yet, so nothing raises and nothing checks. Confirm the *failure reason* is a missing clause, not a `TypeError` from the double's constructor — if it is a `TypeError`, fix the double first.

- [ ] **Step 3: Add `required_any_of` to both protocols**

In `src/docintel/grammar/schema.py`, add to the `Pack` Protocol after `required_fields`:

```python
    def required_any_of(self, doc_type: str) -> tuple[frozenset[str], ...]:
        """Groups where at least one member must have a selector. Backs V13's
        any-of clause.

        A flat `required_fields` cannot express "any parseable date" or "at least
        one money amount" — both of which the field spec states outright, and both
        of which name fields that a fifth of real documents do not print. Each
        group here is satisfied by one covered member.
        """
        ...
```

In `src/docintel/packs/registry.py`, add the same signature to the structural protocol near line 72:

```python
    def required_any_of(self, doc_type: str) -> tuple[frozenset[str], ...]: ...
```

- [ ] **Step 4: Add the V13 clause**

Replace `_check_required_coverage` in `src/docintel/grammar/validator.py:321-338` with:

```python
def _check_required_coverage(
    persona: Mapping[str, Any], pack: Pack, covered: set[str], doc_type: str
) -> None:
    """V13: every required field has a selector, unless the write stays `draft`.

    Derived-only required fields are exempt: `amount_payable` is both required
    and forbidden to select, so demanding a selector for it would make V10 and
    V13 jointly unsatisfiable.

    Two shapes of requirement. A flat name in `required_fields` must be covered.
    An any-of group in `required_any_of` needs one covered member — which is how
    "any parseable date" and "at least one money amount" are expressed, since
    neither can be pinned to a single field name that every document prints.
    """
    if persona.get("status") == "draft":
        return
    exempt = DERIVED_ONLY | pack.derived_only_fields(doc_type)
    missing = sorted(pack.required_fields(doc_type) - covered - exempt)
    if missing:
        raise ValidationError(
            f"persona status is {persona.get('status')!r} but required fields have no "
            f"selector: {missing} (V13). Leave the write as 'draft' until they do"
        )

    for group in pack.required_any_of(doc_type):
        satisfiable = group - exempt
        # A group of nothing but derived-only names cannot be met by any selector.
        # Raising would make the persona unwritable, which is the same trap the
        # `exempt` subtraction above exists to avoid.
        if not satisfiable:
            continue
        if not (satisfiable & covered):
            raise ValidationError(
                f"persona status is {persona.get('status')!r} but no selector covers "
                f"any of {sorted(satisfiable)} (V13 any-of). Leave the write as "
                "'draft' until one does"
            )
```

- [ ] **Step 5: Give both packs an empty `REQUIRED_ANY_OF`**

Tasks 3 and 4 populate these. Empty now keeps behaviour identical.

In `src/docintel/packs/northstar/fields.py`, after `REQUIRED`:

```python
# Populated when the field set narrows to printed values only. Empty here means
# V13's any-of clause is a no-op, so this task changes no behaviour.
REQUIRED_ANY_OF: tuple[frozenset[str], ...] = ()


def required_any_of(doc_type: str) -> tuple[frozenset[str], ...]:
    return REQUIRED_ANY_OF
```

Add the identical block to `src/docintel/packs/digitaldirection/fields.py`.

In both `src/docintel/packs/northstar/__init__.py` and `src/docintel/packs/digitaldirection/__init__.py`, add after `required_fields`:

```python
    def required_any_of(self, doc_type: str) -> tuple[frozenset[str], ...]:
        return fields.required_any_of(doc_type)
```

- [ ] **Step 6: Run the full verification**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests \
  && python3 docs/corpus/validate_gold.py
```

Expected: all clean. The four new tests pass; nothing else changed behaviour because both `REQUIRED_ANY_OF` values are empty.

- [ ] **Step 7: Commit**

```bash
git add src/docintel/grammar/schema.py src/docintel/grammar/validator.py \
  src/docintel/packs/registry.py src/docintel/packs/northstar \
  src/docintel/packs/digitaldirection tests/grammar/test_validator.py
git commit -m "feat(grammar): REQUIRED_ANY_OF groups and a V13 any-of clause

A flat required-field set cannot express the field spec's own wording -
'any parseable date', 'at least one money amount'. Pinning those to
literal names would make EDCO unwritable (bill_date, no invoice_date) and
every vendor printing no parseable total too.

Both packs get an empty group tuple, so this changes no behaviour yet.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Retire the derived expectations

Remove the *expectations* before removing the *capability*. This is the only ordering where every task leaves a green tree: the derived ops still run after this task, they are simply no longer asserted.

No new classification mechanism is needed. `GOLD_ASSERTION_COVERAGE` already carries a **`deferred:<why>`** verdict prefix, listed at `scorecard.py:222` as "needs a capability that does not exist yet", and `VERDICT_PREFIXES` in the coverage test already accepts it.

**Files:**
- Modify: `src/docintel/scorecard.py:204` (`CHECKED_DERIVED`), `:223+` (`GOLD_ASSERTION_COVERAGE`), and the assertion builders that emit derived and arithmetic checks
- Modify: `tests/test_f1_antiregression.py` (guardrail 2 → skip)
- Modify: `tests/test_f1_centracom_trap.py` (guardrail 6 → skip)
- Test: `tests/test_scorecard_coverage.py` (guardrail 3 must stay green unmodified where possible)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `DEFERRED_REASON = "deferred:printed-fields-only"` in `scorecard.py`, used as the verdict string by every re-verdicted entry.

- [ ] **Step 1: Read the three files end to end before editing**

```bash
python3 -m pytest tests/test_scorecard_coverage.py -q
python3 -m docintel.cli replay-gold 2>&1 | tail -20
```

Record the current score — **274/339 assertions, 1/10 documents green** at the time of writing. You need the before-number to report the after-number honestly. Also read `scorecard.py:444-497` (`_closure_assertions`) and `:506-658` (`assertions_for`) in full; the derived and arithmetic assertions are emitted there and you must know every name before re-verdicting any.

- [ ] **Step 2: Write the failing test for the new invariant**

Add to `tests/test_scorecard_coverage.py`:

```python
DEFERRED_REASON = "deferred:printed-fields-only"


def test_no_derived_only_field_is_asserted_by_the_scorecard() -> None:
    """The printed-fields-only rule, in machine-checkable form.

    `document_identity` and `identity_basis` are the exception and stay: they are
    Stage 8 contract keys carrying pipeline provenance, required to be PRESENT by
    core/contract.py, and they live under `derived` rather than `fields` — which
    is where the record already draws this line.
    """
    from docintel.core.models import DERIVED_ONLY

    retained = {"document_identity", "identity_basis"}
    asserted = {a.name for gold in GOLD for a in assertions_for(gold)}
    for name in DERIVED_ONLY - retained:
        offenders = [a for a in asserted if a.endswith(f".{name}") or a == name]
        assert not offenders, f"{name} is derived-only but still asserted: {offenders}"


def test_every_deferred_verdict_names_this_spec() -> None:
    """A bare `deferred:` tells a later reader nothing about what to re-enable."""
    for check, verdict in GOLD_ASSERTION_COVERAGE.items():
        if verdict.startswith("deferred:"):
            assert verdict == DEFERRED_REASON or "printed-fields-only" not in verdict, (
                f"{check} has an ad-hoc deferral reason {verdict!r}; use "
                f"{DEFERRED_REASON!r} so all of them are greppable together"
            )
```

- [ ] **Step 3: Run it to verify it fails**

```bash
python3 -m pytest tests/test_scorecard_coverage.py -k "derived_only_field_is_asserted or deferred_verdict" -v
```

Expected: `test_no_derived_only_field_is_asserted_by_the_scorecard` FAILS, listing `amount_payable`, `payable_basis` and `carried_balance` assertions.

- [ ] **Step 4: Narrow `CHECKED_DERIVED` and stop emitting the derived assertions**

In `src/docintel/scorecard.py`, add near the top of the coverage table:

```python
# Why every derived and arithmetic assertion below is deferred rather than
# deleted. See docs/superpowers/specs/2026-07-28-printed-fields-only-design.md.
# The gold files still record the derived answers, so re-enabling is a wiring
# change and not a re-labelling project.
DEFERRED_REASON = "deferred:printed-fields-only"
```

Narrow line 204:

```python
# `amount_payable` and `payable_basis` left with the printed-fields-only
# narrowing. These two stay because core/contract.py requires their PRESENCE on
# every processed record - they are provenance, not a claim about what the
# document printed.
CHECKED_DERIVED = ("document_identity", "identity_basis")
```

Then, in `assertions_for` and `_closure_assertions`, stop emitting every assertion whose observable is a derived-only value or an arithmetic closure. Re-verdict each corresponding `GOLD_ASSERTION_COVERAGE` entry to `DEFERRED_REASON`. Working from the table at `scorecard.py:223-244`, that is at minimum:

```python
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
    "prior_balance_is_net": DEFERRED_REASON,
```

Leave `"prior_balance_derivation": "covered:fields.prior_balance"` and `"amount_previously_due_is_zero"` and `"discount_is_one_percent"` alone — those assert **printed** fields. Leave every `documentation` verdict alone.

Read the rest of the table past line 244 and apply the same test to each entry: does its observable come from a `DERIVED_ONLY` name or an arithmetic closure? If yes, re-verdict. If it names a printed field, leave it.

- [ ] **Step 5: Skip guardrails 2 and 6 with the reason as the message**

At the top of `tests/test_f1_antiregression.py`, after the imports:

```python
pytestmark = pytest.mark.skip(
    reason="printed-fields-only: derive_amount_payable is deferred, not deleted. "
    "See docs/superpowers/specs/2026-07-28-printed-fields-only-design.md. "
    "Re-enable this guardrail in the same change that re-registers the op."
)
```

Add the identical block to `tests/test_f1_centracom_trap.py`. **Do not delete either file** — a skip with a reason is greppable and recoverable; a deletion is neither.

- [ ] **Step 6: Run the full verification and record the new score**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests \
  && python3 docs/corpus/validate_gold.py
python3 -m docintel.cli replay-gold 2>&1 | tail -20
```

Expected: all four clean. Two test files report as skipped. The denominator drops from 339 as the derived assertions leave. Write both numbers into the commit message.

**Do not measure this task against the spec's 175–200 of ~230.** That is the *end-state* prediction, after Tasks 3 and 4 unwire the ops. Every assertion retired here was already passing, so the numerator cannot fall in this task — retiring a passing expectation removes it from both sides of the fraction. A numerator that *does* fall here means a printed-field assertion was deferred by mistake.

The honest check for this task is the reverse of the spec's: **numerator drop should equal denominator drop.** If they differ, something that was failing got deferred, which hides a real gap.

- [ ] **Step 7: Commit**

```bash
git add src/docintel/scorecard.py tests/test_scorecard_coverage.py \
  tests/test_f1_antiregression.py tests/test_f1_centracom_trap.py
git commit -m "refactor(scorecard): defer every derived and arithmetic assertion

Retires the expectations before the capability, which is the only order
where each step leaves a green tree - the ops still run here, they are
just no longer asserted.

Uses the deferred:<why> verdict GOLD_ASSERTION_COVERAGE already had, so
GUARDRAIL 3 stays green without being weakened. CHECKED_DERIVED narrows
to the two contract keys core/contract.py requires the presence of.

Guardrails 2 and 6 are skipped with the reason as the message, not
deleted.

Score: <before> -> <after> assertions, <n>/10 documents green.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Narrow the Northstar pack

**Files:**
- Modify: `src/docintel/packs/northstar/fields.py`
- Modify: `src/docintel/packs/northstar/hooks.py:72-76` (drop one registration)
- Modify: `src/docintel/packs/northstar/thresholds.py` (drop entries for dropped fields)
- Modify: all six of `src/docintel/packs/northstar/personas/*.json`
- Test: `tests/packs/test_northstar_fields.py` (create if absent)

**Interfaces:**
- Consumes: `fields.REQUIRED_ANY_OF` and `required_any_of()` from Task 1.
- Produces: the narrowed `FIELDS`, `REQUIRED`, `REQUIRED_ANY_OF` that Task 6's whole-path test asserts against.

- [ ] **Step 1: Write the failing tests**

Create `tests/packs/test_northstar_fields.py`:

```python
"""The printed-fields-only rule, asserted structurally rather than per document."""

from __future__ import annotations

from docintel.core.models import DERIVED_ONLY
from docintel.packs.northstar import fields


def test_no_registered_field_is_derived_only() -> None:
    """The machine-checkable form of the whole printed-fields-only design.

    V10 already stops a selector targeting a derived name at validation time.
    This is stricter and earlier: the name is not even registered, so a persona
    author cannot write the selector in the first place.
    """
    assert not (fields.FIELDS & DERIVED_ONLY)


def test_required_is_a_subset_of_fields() -> None:
    assert fields.REQUIRED <= fields.FIELDS


def test_every_any_of_group_is_non_empty_and_registered() -> None:
    assert fields.REQUIRED_ANY_OF, "an empty group tuple makes V13's clause a no-op"
    for group in fields.REQUIRED_ANY_OF:
        assert group, "an empty group can never be satisfied"
        assert group <= fields.FIELDS, f"{sorted(group - fields.FIELDS)} not registered"


def test_the_inference_ladder_outputs_are_gone() -> None:
    """`currency` comes from the F14 ladder and `prior_balance_basis` from a
    vendor convention. Neither is ink on the page."""
    for name in ("currency", "prior_balance_basis"):
        assert name not in fields.FIELDS


def test_normalized_names_are_gone() -> None:
    """A normalized account number is computed from the printed one."""
    assert not {n for n in fields.FIELDS if n.endswith("_normalized")}


def test_bill_to_name_is_unconditionally_required() -> None:
    """It carries the guard that the billed party resolves to Northstar, which is
    what stops another company's invoice being processed as ours."""
    assert "bill_to_name" in fields.REQUIRED
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/packs/test_northstar_fields.py -v
```

Expected: FAIL on `test_no_registered_field_is_derived_only` (`amount_payable` is registered), on the any-of test (tuple is empty from Task 1), and on the ladder-outputs test.

- [ ] **Step 3: Rewrite the field sets**

Replace the set definitions in `src/docintel/packs/northstar/fields.py`. Keep the module docstring's explanatory style; update it to describe the printed-only rule.

```python
# Printed identity. `vendor_name` is registered but never required - see
# REQUIRED_ANY_OF's absence of it and hooks.resolve_vendor_fingerprint.
_IDENTITY: frozenset[str] = frozenset({
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "bill_date",
})

# Amounts exactly as printed. No derivation: `amount_payable` and
# `carried_balance` are DERIVED_ONLY and no longer registered anywhere.
_AMOUNTS: frozenset[str] = frozenset({
    "total_printed",
    "subtotal",
    "tax_amount",
    "prior_balance",
    "current_charges",
    "payments_credits",
    "please_pay",
    "balance_due",
    "discount_amount",
})

_TERMS: frozenset[str] = frozenset({
    "due_date",
    "payment_terms",
    "discount_date",
})

# Allocation: which end site the cost belongs to (F13).
_ALLOCATION: frozenset[str] = frozenset({
    "service_location",
    "vendor_account_number",
    "account_number",
})

# Addresses and payee, all printed blocks.
_ADDRESSES: frozenset[str] = frozenset({
    "bill_to_name",
    "bill_to_address",
    "bill_to_attention",
    "bill_to_email",
    "remit_payee",
    "remit_address",
    "return_address",
    "vendor_address",
})

# Match keys carried as scalar fields rather than in reference_list (F11).
_MATCH_KEYS: frozenset[str] = frozenset({
    "customer_po",
    "seal_number",
    "bol_number",
})
```

Leave `_TABLE` exactly as it is — every name in it is a printed column header or cell value.

```python
FIELDS: frozenset[str] = (
    _IDENTITY | _AMOUNTS | _TERMS | _ALLOCATION | _ADDRESSES | _MATCH_KEYS | _TABLE
)

# The only unconditional requirement. Printed on 94.4% of documents, and it
# carries the guard that the billed party resolves to Northstar - which is what
# stops another company's invoice being processed as ours.
REQUIRED: frozenset[str] = frozenset({"bill_to_name"})

# What a flat set cannot say. Each group needs one covered member.
#
#   date    EDCO prints a billing date and no invoice date. Requiring
#           `invoice_date` by name would make its persona unwritable.
#   amount  the total's LABEL is present on 92.2% of invoices but its VALUE
#           parses on 77.2%. Requiring `total_printed` by name would make every
#           vendor printing no parseable total unwritable.
REQUIRED_ANY_OF: tuple[frozenset[str], ...] = (
    frozenset({"invoice_date", "bill_date"}),
    frozenset({"total_printed", "balance_due", "please_pay",
               "current_charges", "subtotal"}),
)

DERIVED_ONLY: frozenset[str] = frozenset()
```

Removed from the previous `FIELDS`: `amount_payable`, `currency`, `prior_balance_basis`, `vendor_account_number_normalized`, `account_number_normalized`, `vendor_parent_reference`, `billing_group`, `account_name`, `vendor_legal_name`, `vendor_phone`, `vendor_email`, `vendor_website`, `tax_id`.

- [ ] **Step 4: Drop the derived hook**

In `src/docintel/packs/northstar/hooks.py`, remove the `apply_billing_conventions` registration from `register` (line 75) and the function itself. **Leave `conventions.py` in the tree** — it is deferred, not deleted. Add to the module docstring table:

```
| `applyBillingConventions` | deferred: supplies `prior_balance_basis`, a derived classification. `conventions.py` stays in the tree; see the printed-fields-only spec. |
```

Keep all three other registrations. `resolve_vendor_fingerprint` becomes *more* load-bearing, not less — it is half the vendor-name path.

- [ ] **Step 5: Prune the six personas**

For each of `complete_beverage.json`, `dtss.json`, `edco.json`, `federal_recycling.json`, `upak.json`, `veritiv.json`:

1. Delete any selector whose `field` is no longer in `FIELDS`.
2. From every remaining selector's `adjust` array, delete these ops: `resolve_carried_balance`, `derive_amount_payable`, `infer_currency`, `crosscheck_filename`, `crosscheck_scanline`, `crosscheck_balance_composition`, `crosscheck_total_composition`, `crosscheck_line_sum`.
3. **Keep** these ops: `join_lines_comma`, `normalize_date_iso`, `resolve_vendor_alias`, `normalize_credit_sign`, `strip_internal_whitespace`. Each normalizes a printed value rather than deriving a new one.
4. If an `adjust` array becomes empty, remove the key entirely rather than leaving `"adjust": []`.
5. Leave `layout_fingerprint`, `row_group` selectors and `notes` untouched.

Verify no persona lost its any-of coverage:

```bash
python3 -c "
import json,glob
from docintel.packs.northstar import fields
for f in sorted(glob.glob('src/docintel/packs/northstar/personas/*.json')):
    d=json.load(open(f))
    cov={s['field'] for s in d['field_selectors'] if 'field' in s}
    unregistered = cov - fields.FIELDS
    print(f.split('/')[-1], 'UNREGISTERED:' , sorted(unregistered) or 'none')
    for g in fields.REQUIRED_ANY_OF:
        assert g & cov, f'{f} covers no member of {sorted(g)}'
    assert fields.REQUIRED <= cov, f'{f} misses {sorted(fields.REQUIRED-cov)}'
print('all six satisfy V13')
"
```

Every line must print `UNREGISTERED: none` and the script must reach its final print.

- [ ] **Step 6: Drop thresholds for dropped fields**

Read `src/docintel/packs/northstar/thresholds.py` in full. Remove entries whose field is no longer in `FIELDS` — `amount_payable` at minimum. Leave the comment style intact and update any comment that references a removed field.

- [ ] **Step 7: Run the full verification**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests \
  && python3 docs/corpus/validate_gold.py
python3 -m docintel.cli replay-gold 2>&1 | tail -20
```

Expected: all four clean. **`tests/test_personas_validate.py` (guardrail 5) must stay green** — it is the test that catches a pruned `FIELDS` rejecting a persona, and a rejected persona is a lookup *miss* that silently drops the document to vision. If it fails, a selector still targets an unregistered field; go back to Step 5.

- [ ] **Step 8: Commit**

```bash
git add src/docintel/packs/northstar tests/packs/test_northstar_fields.py
git commit -m "feat(northstar): narrow the field set to printed values

Drops amount_payable, currency, prior_balance_basis, the *_normalized
names and the unprinted vendor-identity tail. REQUIRED becomes
bill_to_name alone - it carries the guard that the billed party resolves
to Northstar - with the date and money requirements moved to
REQUIRED_ANY_OF so EDCO's bill_date-only shape stays writable.

Personas lose the derive and crosscheck ops and keep the normalizers.
apply_billing_conventions is unregistered; conventions.py stays.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Narrow the Digital Direction pack

Same shape as Task 3, with one extra removal: DD registers `refine_prior_balance_tags` at `beforeConfidenceGate`, and it retags on `carried_balance` — which no longer exists.

**Files:**
- Modify: `src/docintel/packs/digitaldirection/fields.py`
- Modify: `src/docintel/packs/digitaldirection/hooks.py:72-77` (drop two registrations)
- Modify: `src/docintel/packs/digitaldirection/thresholds.py`
- Modify: all four of `src/docintel/packs/digitaldirection/personas/*.json`
- Test: `tests/packs/test_digitaldirection_fields.py` (create)

**Interfaces:**
- Consumes: `fields.required_any_of()` from Task 1.
- Produces: the narrowed sets Task 6's whole-path test asserts against.

- [ ] **Step 1: Write the failing tests**

Create `tests/packs/test_digitaldirection_fields.py` with the same six tests as Task 3 Step 1, importing `from docintel.packs.digitaldirection import fields`, and with the last one replaced by:

```python
def test_account_number_is_unconditionally_required() -> None:
    """DD's identity key, not `invoice_number`: three of the four carriers print
    no invoice number at all (F6), and the field spec measures the carrier
    account number present on 100% of readable invoices."""
    assert "account_number" in fields.REQUIRED
    assert "invoice_number" not in fields.REQUIRED


def test_the_row_classifications_are_not_registered() -> None:
    """Service type, charge type and the C/S/U row flag are closed-list
    classifications of a row, not printed values - so they are deferred with the
    rest of the derived work rather than added."""
    for name in ("service_type", "charge_type", "row_type"):
        assert name not in fields.FIELDS
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/packs/test_digitaldirection_fields.py -v
```

Expected: FAIL on the derived-only test (`amount_payable` registered) and the any-of test (empty tuple).

- [ ] **Step 3: Rewrite the field sets**

In `src/docintel/packs/digitaldirection/fields.py`, remove from `_IDENTITY`: `account_number_normalized`. Remove from `_AMOUNTS`: `amount_payable`, `currency`, `prior_balance_basis`. Remove from `_ALLOCATION`: `carrier_canonical`, `vendor_legal_name`, `vendor_phone`, `vendor_email`, `vendor_website`, `vendor_parent_reference`. Remove `billing_group` from `_IDENTITY`. Leave `_DATES` and `_TABLE` as they are.

Then:

```python
# `account_number` rather than `invoice_number`: three of the four carriers print
# no invoice number (F6), and the field spec measures the carrier account number
# present on 100% of readable invoices.
REQUIRED: frozenset[str] = frozenset({"account_number"})

REQUIRED_ANY_OF: tuple[frozenset[str], ...] = (
    frozenset({"bill_date", "invoice_date", "service_period"}),
    frozenset({"total_printed", "balance_due", "please_pay",
               "current_charges", "amount_previously_due"}),
)
```

- [ ] **Step 4: Drop the two derived hooks**

In `src/docintel/packs/digitaldirection/hooks.py`, remove the `apply_billing_conventions` registration (line 75) and its function, and the `refine_prior_balance_tags` registration (line 77) and its function. Leave `conventions.py` and `ladder.retag_prior_balance` in the tree. Record both in the module docstring:

```
`applyBillingConventions` and `refineProseBalanceTags` are both deferred by the
printed-fields-only narrowing: the first supplies `prior_balance_basis`, a derived
classification, and the second retags on `carried_balance`, which Stage 6 no
longer produces. Both implementations stay in the tree.
```

Keep `telecom_ladder`, `resolve_carrier_fingerprint` and `collect_references`. The comment at `hooks.py:51-59` explaining why `collect_references` sits at `beforeConfidenceGate` rather than `afterExtraction` still holds — verify it after the change, since it reasons about `account_number_normalized`, which is now gone. If that reasoning no longer applies, update the comment rather than silently leaving a stale explanation.

- [ ] **Step 5: Prune the four personas**

For `centracom.json`, `comcast.json`, `lumen.json`, `windstream.json`, apply the identical procedure as Task 3 Step 5 — same op removal list, same keep list, same empty-array cleanup.

Then run the same verification, with the import changed:

```bash
python3 -c "
import json,glob
from docintel.packs.digitaldirection import fields
for f in sorted(glob.glob('src/docintel/packs/digitaldirection/personas/*.json')):
    d=json.load(open(f))
    cov={s['field'] for s in d['field_selectors'] if 'field' in s}
    unregistered = cov - fields.FIELDS
    print(f.split('/')[-1], 'UNREGISTERED:', sorted(unregistered) or 'none')
    for g in fields.REQUIRED_ANY_OF:
        assert g & cov, f'{f} covers no member of {sorted(g)}'
    assert fields.REQUIRED <= cov, f'{f} misses {sorted(fields.REQUIRED-cov)}'
print('all four satisfy V13')
"
```

- [ ] **Step 6: Drop thresholds for dropped fields**

Read `src/docintel/packs/digitaldirection/thresholds.py` in full and remove entries for names no longer in `FIELDS`.

- [ ] **Step 6b: Narrow `CHECKED_FIELDS` — both packs, once, here**

Deliberately deferred to this task rather than split across Tasks 3 and 4. `CHECKED_FIELDS` (`scorecard.py:155`) is scorecard-global, so narrowing it while only one pack had changed would have been a global edit for a pack-local reason. Both packs are narrowed now, so the full set of no-longer-extracted fields is finally knowable.

Compute it rather than guessing:

```bash
python3 -c "
import json,glob
from docintel.scorecard import CHECKED_FIELDS
from docintel.packs.northstar import fields as ns
from docintel.packs.digitaldirection import fields as dd
extractable = ns.FIELDS | dd.FIELDS
gone = sorted(n for n in CHECKED_FIELDS if n not in extractable)
in_gold = set()
for f in glob.glob('docs/corpus/gold/*.json'):
    in_gold |= set(json.load(open(f)).get('fields') or {})
print('no longer extractable:', gone)
print('...and still present in gold:', sorted(set(gone) & in_gold))
"
```

Remove the first list from `CHECKED_FIELDS`. The second list is the subset that will then trip `test_every_gold_field_is_either_asserted_or_declared_prose` — those gold facts still exist and must be accounted for.

Account for them the way Task 2 accounted for the derived keys, mirroring `DEFERRED_DERIVED_KEYS`. In `tests/test_scorecard_coverage.py`:

```python
# Gold records these, and the documents really do print some of them, but no
# pack extracts them under printed-fields-only: `currency` comes from the F14
# inference ladder and `prior_balance_basis` from a vendor convention. Gold is
# read-only and keeps the evidence, so re-enabling is a wiring change.
DEFERRED_FIELDS: frozenset[str] = frozenset({ ... })  # the computed list
```

Extend `test_every_gold_field_is_either_asserted_or_declared_prose` to accept a third account — `name in DEFERRED_FIELDS` — and add the pin that keeps the allowance honest, mirroring `test_the_deferred_derived_list_holds_only_derived_only_names`:

```python
def test_the_deferred_field_list_holds_only_unextractable_names() -> None:
    """An entry here for a field a pack still extracts is a free pass, not a
    deferral — it would hide a real extraction failure behind a spec decision."""
    from docintel.packs.northstar import fields as ns
    from docintel.packs.digitaldirection import fields as dd

    assert not (DEFERRED_FIELDS & (ns.FIELDS | dd.FIELDS))
    assert not (DEFERRED_FIELDS & set(CHECKED_FIELDS))
```

**Do not widen `PROSE_FIELDS`** to absorb these — it is capped at two entries and every member must end in `_note`, and both guards exist to stop exactly this kind of drift.

- [ ] **Step 7: Run the full verification**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests \
  && python3 docs/corpus/validate_gold.py
python3 -m docintel.cli replay-gold 2>&1 | tail -20
```

Guardrail 5 must stay green. **Guardrail 6 is already skipped** from Task 2, which is what stops Centracom's trap test failing here.

- [ ] **Step 8: Commit**

```bash
git add src/docintel/packs/digitaldirection tests/packs/test_digitaldirection_fields.py
git commit -m "feat(digitaldirection): narrow the field set to printed values

Same narrowing as the Northstar pack. REQUIRED becomes account_number
alone - DD's identity key, since three of four carriers print no invoice
number (F6) - with date and money moved to REQUIRED_ANY_OF.

Also unregisters refine_prior_balance_tags, which retagged on
carried_balance and now has no input. Implementation stays in the tree.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `vendor_name` from the sender, with the aggregator guard

`vendor_name` is registered but never required. Two corpus documents cannot supply it from the text layer at all: Lumen's letterhead is an image, and Windstream's text layer breaks the brand mid-word as `Windstre am`.

`pipeline-v2.md:169` requires that aggregator senders be keyed by printed vendor name and **never** by the shared email domain — otherwise every invoice routed through bill.com resolves to one vendor. That is specified but **implemented nowhere in `src/`**, and no corpus document arrives from an aggregator. This task keeps the gap honest with a test rather than leaving it silent.

**Files:**
- Create: `src/docintel/packs/registry.py` addition — or a new `src/docintel/core/senders.py` if `registry.py` is already dense; read it first and follow whichever the file's existing shape suggests
- Modify: `src/docintel/packs/northstar/hooks.py` (`resolve_vendor_fingerprint`)
- Modify: `src/docintel/packs/digitaldirection/hooks.py` (`resolve_carrier_fingerprint`)
- Test: `tests/test_aggregator_guard.py` (create)

**Interfaces:**
- Consumes: `JobContext.sender_email`, confirmed present at `src/docintel/core/models.py:155` as `sender_email: str | None = None`. **It is optional and defaults to `None`**, so every call site must coerce: `ctx.sender_email or ""`.
- Produces: `AGGREGATOR_DOMAINS: frozenset[str]` and `is_aggregator(sender_email: str) -> bool`.

- [ ] **Step 1: Confirm nothing already sets a vendor name from the domain**

```bash
grep -rn "sender_email" src/docintel/ | grep -v "models.py"
```

If a resolver already reads it, extend that code rather than adding a second path — two places deciding a vendor name is how the two disagree. If nothing reads it, proceed to Step 2.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_aggregator_guard.py`:

```python
"""The guard on an unimplemented branch.

pipeline-v2.md:169 requires aggregator senders be keyed by printed vendor name
and never by the shared email domain: without this, every invoice routed through
bill.com resolves to one vendor. No corpus document arrives from an aggregator,
so nothing here would fail if the branch were simply missing - which is exactly
why the test exists.
"""

from __future__ import annotations

import pytest

from docintel.core.senders import AGGREGATOR_DOMAINS, is_aggregator


@pytest.mark.parametrize("email", [
    "ap@bill.com",
    "noreply@ariba.com",
    "invoices@quickbooks.com",
    "AP@BILL.COM",
    "  ap@bill.com  ",
])
def test_known_aggregators_are_recognized(email: str) -> None:
    assert is_aggregator(email)


@pytest.mark.parametrize("email", [
    "billing@acmehauling.com",
    "ar@dtss.com",
    "",
    "not-an-email",
])
def test_direct_senders_are_not_aggregators(email: str) -> None:
    assert not is_aggregator(email)


def test_a_subdomain_of_an_aggregator_still_counts() -> None:
    """mail.bill.com is bill.com's mail, not a vendor called mail.bill.com."""
    assert is_aggregator("ap@mail.bill.com")


def test_a_domain_merely_containing_an_aggregator_name_does_not() -> None:
    """`notbill.com` and `bill.com.example.org` are different senders."""
    assert not is_aggregator("ap@notbill.com")
    assert not is_aggregator("ap@bill.com.example.org")


def test_the_denylist_is_not_empty() -> None:
    """An empty list makes every check above vacuously false."""
    assert AGGREGATOR_DOMAINS
```

- [ ] **Step 3: Run to verify failure**

```bash
python3 -m pytest tests/test_aggregator_guard.py -v
```

Expected: FAIL with `ModuleNotFoundError: docintel.core.senders`.

- [ ] **Step 4: Implement**

Create `src/docintel/core/senders.py`:

```python
"""Which senders are aggregators, and therefore cannot supply a vendor name.

`pipeline-v2.md:169`: aggregator senders are keyed by the printed vendor name,
never by the shared email domain. Without that rule every invoice routed through
bill.com collapses onto one vendor identity.

No corpus document arrives from an aggregator, so this module is guarded by
`tests/test_aggregator_guard.py` rather than exercised by the gold set. That is
deliberate: an unimplemented branch nothing tests is the failure mode this file
exists to avoid.
"""

from __future__ import annotations

# Deliberately short. A domain earns a place here only when a real document has
# arrived through it, because a false entry costs a vendor name on every
# document from that sender.
AGGREGATOR_DOMAINS: frozenset[str] = frozenset({
    "bill.com",
    "ariba.com",
    "quickbooks.com",
    "intuit.com",
    "coupahost.com",
})


def is_aggregator(sender_email: str) -> bool:
    """Does this sender forward other companies' invoices?

    Matched on the domain and its subdomains, never on a substring: `notbill.com`
    is a different sender from `bill.com`, and `bill.com.example.org` is a
    lookalike rather than a match.
    """
    if not sender_email or "@" not in sender_email:
        return False
    domain = sender_email.strip().rsplit("@", 1)[1].lower().rstrip(".")
    return any(
        domain == known or domain.endswith(f".{known}")
        for known in AGGREGATOR_DOMAINS
    )
```

- [ ] **Step 5: Run to verify the tests pass**

```bash
python3 -m pytest tests/test_aggregator_guard.py -v
```

Expected: PASS, all cases.

- [ ] **Step 6: Wire it into both fingerprint resolvers**

In both `resolve_vendor_fingerprint` (Northstar) and `resolve_carrier_fingerprint` (DD), the existing behaviour already reads canonical vendor from **page text** and is correct as-is. Add the sender-domain fallback *after* it, guarded:

```python
    canonical = aliases.canonical(primary_text(ctx))
    if canonical is None and not is_aggregator(ctx.sender_email or ""):
        # The letterhead was unreadable - Lumen's is an image, Windstream's text
        # layer breaks the brand mid-word. The sender domain is weaker evidence
        # than a printed name, but it is evidence, and it is the only thing left.
        canonical = aliases.canonical_from_domain(ctx.sender_email or "")
    if canonical is not None:
        ctx.sender_fingerprint = f"{PACK_NAME}|{canonical}"
    return next_(ctx)
```

This needs `aliases.canonical_from_domain(sender_email: str) -> str | None` in both packs' `aliases.py`. Read each `aliases.py` first: if it already maps domains, reuse that map. If it maps only printed names, add a small explicit domain map beside it — do **not** derive a canonical key by string-munging the domain, because `acmehauling.com` and the canonical key for Acme Hauling are only coincidentally similar.

If a pack has no domain evidence for any of its vendors, leave `canonical_from_domain` returning `None` for everything and say so in a comment. An honest no-op beats a guess.

- [ ] **Step 7: Full verification**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests \
  && python3 docs/corpus/validate_gold.py
python3 -m docintel.cli replay-gold 2>&1 | tail -20
```

- [ ] **Step 8: Commit**

```bash
git add src/docintel/core/senders.py src/docintel/packs tests/test_aggregator_guard.py
git commit -m "feat(packs): vendor name from the sender domain, with an aggregator guard

vendor_name is registered but never required, and two corpus documents
cannot supply it from the text layer at all - Lumen's letterhead is an
image and Windstream's text layer breaks the brand mid-word.

The aggregator rule at pipeline-v2.md:169 was specified and implemented
nowhere. No corpus document arrives through an aggregator, so nothing
would have failed if the branch stayed missing - hence a test rather than
a silent gap. Matches on domain and subdomain, never substring.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Whole-path tests and documentation

Standing rule 10: a cluster that changes a pipeline capability finishes with one whole-path test. C2b's worst defect passed all 42 unit tests and was caught only end to end.

**Files:**
- Test: `tests/test_printed_fields_only_path.py` (create)
- Modify: `docs/superpowers/RESUME.md`
- Modify: `docs/packs/northstar-recycling.md` §2, `docs/packs/digital-direction.md` §3
- Modify: `docs/superpowers/execution/ledger.md`

**Interfaces:**
- Consumes: the narrowed field sets from Tasks 3 and 4, `is_aggregator` from Task 5.

- [ ] **Step 1: Write the whole-path test**

Create `tests/test_printed_fields_only_path.py`. Read an existing whole-path test first (the C2b one referenced in RESUME.md) and follow its fixture and runner conventions exactly rather than inventing new ones.

```python
"""One real PDF per pack, all the way to a validated Stage 8 record.

Unit tests confirm the units. Only the whole path shows what the units compose
into - which is how C2b's line_items selector swallowing the totals block got
caught after passing all 42 of its unit tests.
"""

from __future__ import annotations

from docintel.core.models import DERIVED_ONLY

# Use whatever runner/fixture the existing whole-path test uses.
NORTHSTAR_PDF = "docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf"
DIGITALDIRECTION_PDF = "docs/Centracom_0384043574_01012026_BILL.pdf"

RETAINED_DERIVED = {"document_identity", "identity_basis"}


def test_northstar_record_carries_no_derived_field(run_pipeline) -> None:
    record = run_pipeline(NORTHSTAR_PDF)
    assert record["disposition"] == "processed"
    leaked = (set(record["fields"]) | set(record.get("derived", {}))) & (
        DERIVED_ONLY - RETAINED_DERIVED
    )
    assert not leaked, f"derived values reached the record: {sorted(leaked)}"


def test_northstar_record_still_carries_the_identity_contract_keys(run_pipeline) -> None:
    """core/contract.py requires their PRESENCE - None is a valid value, absence
    is not. Dropping them would break count(intaken) == count(emitted)."""
    record = run_pipeline(NORTHSTAR_PDF)
    for key in RETAINED_DERIVED:
        assert key in record["derived"]


def test_northstar_total_is_the_printed_figure(run_pipeline) -> None:
    """DTSS prints a single total and no prior balance, so printed and payable
    were never in tension here - which makes it the honest place to assert that
    total_printed is transcribed rather than adjusted."""
    record = run_pipeline(NORTHSTAR_PDF)
    assert record["fields"]["total_printed"] == "699.00"


def test_centracom_emits_the_printed_total_not_the_payable(run_pipeline) -> None:
    """The consequence this design accepts, asserted so it cannot drift silently.

    Centracom prints 33,876.40 and is payable 13,752.60. Under printed-only the
    pipeline transcribes the printed figure faithfully and says nothing about the
    payable - the $20,123.80 gap is downstream's to catch. If this ever starts
    returning 13,752.60, derivation has been re-enabled without re-enabling
    guardrails 2 and 6.
    """
    record = run_pipeline(DIGITALDIRECTION_PDF)
    assert record["fields"]["total_printed"] == "33876.40"
    assert "amount_payable" not in record.get("derived", {})


def test_both_records_are_schema_valid(run_pipeline) -> None:
    from docintel.core.contract import validate_record

    for pdf in (NORTHSTAR_PDF, DIGITALDIRECTION_PDF):
        validate_record(run_pipeline(pdf))  # must not raise
```

Confirm the two expected money strings against the gold files before asserting them — `docs/corpus/gold/northstar-dtss-6060.json` and `docs/corpus/gold/digitaldirection-centracom-0384043574.json`. Do not guess a format; match whatever the record actually carries (string vs `Decimal`).

- [ ] **Step 2: Run it**

```bash
python3 -m pytest tests/test_printed_fields_only_path.py -v
```

Fix the implementation, not the assertion, if `test_centracom_emits_the_printed_total_not_the_payable` fails — unless the gold says the printed figure is formatted differently, in which case fix the literal.

- [ ] **Step 3: Update both pack specs**

`docs/packs/northstar-recycling.md` §2 and `docs/packs/digital-direction.md` §3 both still list the old required tables. Replace each with the narrowed sets, and add a line at the top of the section pointing at `docs/superpowers/specs/2026-07-28-printed-fields-only-design.md` as the reason. Keep every table's existing anchor/pattern column — that information is still correct for the fields that remain.

- [ ] **Step 4: Update `RESUME.md`**

Rewrite "State in one block" with the real measured numbers, and add to "Where the work stopped":

```markdown
- **printed-fields-only** — both packs narrowed to values printed on the
  document. `REQUIRED_ANY_OF` + a V13 any-of clause, so EDCO's bill_date-only
  shape stays writable. Derived work is **deferred, not deleted**: every module
  and unit test is on disk, guardrails 2 and 6 are `skip` with the reason as the
  message, and gold still records the derived answers. Re-enabling is a wiring
  change. See `specs/2026-07-28-printed-fields-only-design.md`.
```

Add a standing rule, since this plan's ordering was chosen to avoid a real trap:

```markdown
11. **Retire expectations before capabilities.** Narrowing `FIELDS` before
   re-verdicting the scorecard leaves the tree red for two whole tasks, and worse:
   V1 rejects the personas, a rejected persona is a lookup MISS, and all ten
   documents silently fall back to vision. Scorecard first, then field sets, then
   personas — in the same commit as their field set.
```

- [ ] **Step 5: Append to the ledger**

Add a dated entry to `docs/superpowers/execution/ledger.md` recording: the narrowing, the two spec errata found during planning (the derived work lives in persona `adjust` lists rather than hooks; `GOLD_ASSERTION_COVERAGE` already had a `deferred:` verdict so no new mechanism was needed), the third finding that four of DD's eight "Required" spec fields are not printed values, and the before/after assertion counts.

- [ ] **Step 6: Final verification**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests \
  && python3 docs/corpus/validate_gold.py
python3 -m docintel.cli replay-gold 2>&1 | tail -20
```

All four clean. Record the final score.

- [ ] **Step 7: Commit**

```bash
git add tests/test_printed_fields_only_path.py docs/
git commit -m "test(path): whole-path assertions for printed-fields-only, and docs

One real PDF per pack to a validated Stage 8 record, asserting no
DERIVED_ONLY name reaches it and that the two identity contract keys
still do.

Pins the consequence this design accepts: Centracom emits the printed
33,876.40 and says nothing about the payable 13,752.60. If that assertion
ever flips, derivation was re-enabled without its guardrails.

Score: <before> -> <after> assertions, <n>/10 documents green.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage.** §1 rule → Tasks 3/4 field sets + the structural tests. §2 what leaves scope → Tasks 3/4 Step 3. §3 `REQUIRED_ANY_OF` → Task 1. §3 both packs' sets → Tasks 3/4. §4 vendor-name-from-sender + aggregator guard → Task 5. §5 ops removed from `adjust` lists → Tasks 3/4 Step 5; hooks removed → Tasks 3 Step 4 and 4 Step 4; `derive_document_identity` retained → Global Constraints + Task 6 test. §6 personas → Tasks 3/4 Step 5, with guardrail 5 as the check. §7 gold read-only → Global Constraints; scorecard re-verdicting → Task 2; guardrails 2/6 skipped → Task 2 Step 5. §8 all six test items → Task 1 (any-of both directions), Tasks 3/4 (field-set unit tests, guardrail 5), Task 5 (aggregator), Task 6 (whole path, `validate_record`). §9 risks → the Centracom assertion in Task 6 pins the first; Task 5 pins the second.

**Gap found and closed:** §8 item 6 asks that `count(intaken) == count(emitted)` remain untouched. No task modifies the invariant's test, and Task 6 Step 6 runs the full suite which includes it — but nothing states it explicitly. Added to Global Constraints via the `derive_document_identity` constraint, which is the only change in this plan that could have broken it.

**Placeholder scan.** Three deliberate `<before>`/`<after>`/`<n>` placeholders in commit messages — these are measurements that do not exist until the task runs, and each has an explicit step that produces the number. Task 5 Step 6 and Task 6 Step 1 say "read the existing file and follow its conventions" rather than showing code: that is intentional, because inventing a fixture signature that contradicts the repo's would be worse than instructing the implementer to read. Both carry a stop-and-report condition.

**Type consistency.** `required_any_of` returns `tuple[frozenset[str], ...]` in `schema.py`, `registry.py`, both packs' `__init__.py`, both `fields.py`, and the test double — checked, consistent. `REQUIRED_ANY_OF` is the module constant, `required_any_of()` the function; both spelled the same way at every site. `is_aggregator(sender_email: str) -> bool` and `AGGREGATOR_DOMAINS: frozenset[str]` match between `senders.py`, the tests and both hook call sites. `DEFERRED_REASON` is defined in `scorecard.py` and re-declared in the coverage test — flagged deliberately: the test asserts the value the source uses, so importing it would make the test tautological.
