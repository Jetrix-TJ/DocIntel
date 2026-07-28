"""The op registry against the enum the validator accepts (V2).

The two-way equality below is the point of this file. `schema.BASE_ADJUST_OPS`
is what `validate_persona` checks a persona's `adjust` names against; `ops` is
what Stage 6 can actually run. If they drift, one of two silent failures follows:

* declared but not implemented - the validator accepts the persona and Stage 6
  quietly skips the op, so a document is scored as if a cross-check passed when
  nothing ran
* implemented but not declared - the op is unreachable, because no persona can
  name it without being rejected

Neither surfaces anywhere else, so it is asserted here in both directions.
"""

from __future__ import annotations

import pytest

from docintel.core.models import new_context
from docintel.grammar import ops
from docintel.grammar.schema import BASE_ADJUST_OPS


def test_every_declared_op_is_implemented() -> None:
    missing = sorted(BASE_ADJUST_OPS - ops.ALL_OP_NAMES)
    assert not missing, f"declared in the grammar but not implemented: {missing}"


def test_every_implemented_op_is_declared() -> None:
    extra = sorted(ops.ALL_OP_NAMES - BASE_ADJUST_OPS)
    assert not extra, f"implemented but not in the grammar's closed enum: {extra}"


def test_value_ops_and_document_ops_do_not_overlap() -> None:
    """One name, one shape. An op that was both would run twice, differently."""
    assert not (set(ops.base.VALUE_OPS) & set(ops.OPS))


def test_document_identity_is_not_an_adjust_op() -> None:
    """It is an unconditional Stage 6 step. `validate_record` requires the
    identity on every processed record, so a persona must not be able to opt out
    of it by leaving a name out of its `adjust` list."""
    assert "derive_document_identity" not in ops.ALL_OP_NAMES
    assert "derive_document_identity" not in BASE_ADJUST_OPS


# --------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------


def test_the_f1_dependency_order_is_pinned() -> None:
    """A persona listing these backwards must not break the derivation."""
    requested = ["derive_amount_payable", "resolve_carried_balance", "normalize_credit_sign"]
    assert ops.ordered(requested) == [
        "normalize_credit_sign", "resolve_carried_balance", "derive_amount_payable",
    ]


def test_current_charges_are_computed_before_the_payable_reads_them() -> None:
    result = ops.ordered(["derive_amount_payable", "subtract_prior_balance_if_present"])
    assert result.index("subtract_prior_balance_if_present") < result.index(
        "derive_amount_payable"
    )


def test_crosschecks_run_after_every_derivation() -> None:
    """Scoring only, so they must never run before the values they score exist."""
    result = ops.ordered(list(ops.OPS))
    last_derive = max(
        result.index(n) for n in
        ("normalize_credit_sign", "resolve_carried_balance", "derive_amount_payable")
    )
    first_crosscheck = min(
        i for i, n in enumerate(result) if n.startswith("crosscheck_")
    )
    assert last_derive < first_crosscheck


def test_ordered_deduplicates() -> None:
    """Two selectors may both declare the same document op; it runs once."""
    assert ops.ordered(["infer_currency", "infer_currency"]) == ["infer_currency"]


def test_ordered_keeps_unknown_names_last_rather_than_dropping_them() -> None:
    """Losing a name silently would be worse than running it late; the validator
    is what rejects unknown ops, and it has already run by this point."""
    result = ops.ordered(["zzz_unregistered", "resolve_carried_balance"])
    assert result[-1] == "zzz_unregistered"


def test_every_document_op_appears_in_order() -> None:
    """An op absent from ORDER would sort to the end on a name tiebreak, which is
    a silent ordering decision rather than a stated one."""
    assert set(ops.ORDER) == set(ops.OPS)


# --------------------------------------------------------------------------
# Uniform safety
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(ops.OPS))
def test_every_document_op_survives_an_empty_context(name: str) -> None:
    """Stage 6 runs whatever the persona declared, on whatever was extracted -
    including nothing, which is the state of every document until C5."""
    ctx = new_context("d", "/x.pdf")
    result = ops.OPS[name](ctx)
    assert result is ctx, f"{name} must mutate and return the same context"
