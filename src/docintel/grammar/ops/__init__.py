"""The closed `adjust`-op enum (`selector-grammar.md` section 4).

Two shapes, because section 4 describes two genuinely different kinds of work:

* **Value ops** (§4.1) transform one field's value: `strip_internal_whitespace`,
  `parens_to_negative`, `trim`. They are `Callable[[Any], Any]` and live in
  `base.VALUE_OPS`, keyed by name. Which field they apply to comes from the
  selector that declared them.
* **Document ops** (§4.2–4.4) reason across fields: `derive_amount_payable` needs
  the prior balance, the current charges and the printed total together. They are
  `Callable[[JobContext], JobContext]` and live in `OPS`.

`ALL_OP_NAMES` is the union and must equal `schema.BASE_ADJUST_OPS`, which is
what the validator checks a persona against (V2). A test asserts that equality
in both directions, so an op cannot be implemented without being declared or
declared without being implemented.

Ordering matters and is not alphabetical. `normalize_credit_sign` must run before
anything that adds a payment to a balance, and `resolve_carried_balance` must run
before `derive_amount_payable` reads its result. `ORDER` states that dependency
once so `s6_capture` does not have to know about it.
"""

from __future__ import annotations

from collections.abc import Callable

from docintel.core.models import JobContext
from docintel.grammar.ops import base, crosscheck, derive, infer, pricing

DocumentOp = Callable[[JobContext], JobContext]

OPS: dict[str, DocumentOp] = {
    # 4.2 derivation - the F1 machinery
    "normalize_credit_sign": derive.normalize_credit_sign,
    "resolve_carried_balance": derive.resolve_carried_balance,
    "derive_amount_payable": derive.derive_amount_payable,
    "subtract_prior_balance_if_present": derive.subtract_prior_balance_if_present,
    "prefer_current_charges_line": derive.prefer_current_charges_line,
    # weight-tiered manufacturing pricing - a second derivation family,
    # unrelated to telecom F1 (see grammar/ops/pricing.py's own docstring)
    "derive_price_per_foot": pricing.derive_price_per_foot,
    # 4.3 consistency - scoring only, never value-changing
    "crosscheck_line_sum": crosscheck.crosscheck_line_sum,
    "crosscheck_total_composition": crosscheck.crosscheck_total_composition,
    "crosscheck_balance_composition": crosscheck.crosscheck_balance_composition,
    "crosscheck_scanline": crosscheck.crosscheck_scanline,
    "crosscheck_duplicate_anchor": crosscheck.crosscheck_duplicate_anchor,
    "crosscheck_filename": crosscheck.crosscheck_filename,
    # 4.4 inference
    "infer_currency": infer.infer_currency,
    "resolve_vendor_alias": infer.resolve_vendor_alias,
    "resolve_bill_to_alias": infer.resolve_bill_to_alias,
}

ALL_OP_NAMES: frozenset[str] = frozenset(base.VALUE_OPS) | frozenset(OPS)

# Dependency order for the document ops. Anything not named here runs afterwards
# in declaration order; these are the ones whose relative order is load-bearing.
#
#   normalize_credit_sign     a credit must be negative before it is added to
#                             a balance, or F1b computes the carried balance
#                             with the payment pointing the wrong way
#   subtract_prior_balance    supplies current_charges when it is not printed,
#                             so it has to precede the op that reads it
#   resolve_carried_balance   produces carried_balance
#   derive_amount_payable     consumes carried_balance
#   crosscheck_*              scoring only, so they run last and can never
#                             change a value another op already decided
#
# `derive.derive_document_identity` is deliberately NOT in this registry. It is
# an unconditional Stage 6 step, not an `adjust` op a persona may reference: the
# identity exists so downstream dedup works for the 3 of 10 corpus documents
# that print no invoice number (F6), and `validate_record` requires it on every
# processed record. A persona must not be able to opt out of it by omitting an
# op name - and keeping it out of the enum also keeps `BASE_ADJUST_OPS` at the
# 23 names section 4 actually lists.
ORDER: tuple[str, ...] = (
    "normalize_credit_sign",
    "prefer_current_charges_line",
    "resolve_carried_balance",
    "subtract_prior_balance_if_present",
    "derive_amount_payable",
    # No dependency on anything above or below - a self-contained formula
    # over its own pack-supplied inputs (see pricing.py's own docstring).
    # Positioned here rather than appended at the very end only because
    # `test_every_document_op_appears_in_order` requires every OPS name to
    # appear in ORDER at all, not because relative order matters here.
    "derive_price_per_foot",
    "infer_currency",
    "resolve_vendor_alias",
    # After the vendor, before the cross-checks: it only reads page text and the
    # already-extracted bill_to_name, so nothing it produces is an input to a
    # derivation - but a cross-check may want the party it resolved.
    "resolve_bill_to_alias",
    "crosscheck_line_sum",
    "crosscheck_total_composition",
    "crosscheck_balance_composition",
    "crosscheck_scanline",
    "crosscheck_duplicate_anchor",
    "crosscheck_filename",
)


def ordered(names: list[str]) -> list[str]:
    """Sort requested document-op names into dependency order, keeping unknowns last.

    Declaration order within a persona is preserved for ops whose order does not
    matter; the ones in `ORDER` are pinned regardless of how a persona author
    happened to list them. A persona should not be able to break the F1
    derivation by writing its ops in the wrong sequence.
    """
    index = {name: i for i, name in enumerate(ORDER)}
    return sorted(dict.fromkeys(names), key=lambda n: (index.get(n, len(ORDER)), n))


__all__ = [
    "ALL_OP_NAMES",
    "OPS",
    "ORDER",
    "DocumentOp",
    "base",
    "crosscheck",
    "derive",
    "infer",
    "ordered",
]
