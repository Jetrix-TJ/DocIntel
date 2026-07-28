"""Northstar's field set (`docs/packs/northstar-recycling.md` section 2).

Narrowed to printed-fields-only: every name in `FIELDS` is a value that
appears as ink on the page, never one computed from other fields. Three sets
per doc type, and the distinction between them is what V1, V10 and V13 each
check:

* `FIELDS` - every name a selector may target (V1)
* `REQUIRED` - every name that must have a selector before a persona leaves
  `draft` (V13)
* `DERIVED_ONLY` - every name no selector may ever target (V10)

`core.models.DERIVED_ONLY` already covers `amount_payable` and its
companions, and none of them are registered here any more - a derived value
has no selector to write, so there is nothing left for this pack's own
`DERIVED_ONLY` to add on top of the core set.
"""

from __future__ import annotations

# Printed identity. `vendor_name` is registered but never required - see
# REQUIRED_ANY_OF's absence of it and hooks.resolve_vendor_fingerprint.
#
# `tax_id` is registered and deliberately unselected. U-PAK prints an H.S.T.
# number (`123142812RT0001`) which gold labels and no persona has ever read - it
# is the F14 anchor hazard's own value, since `H.S.T.` is also what tells the
# currency ladder the invoice is Canadian. That is extraction DEBT, not a
# deferral, so `scorecard.CHECKED_FIELDS` keeps asserting it and it keeps
# failing. Registration is what makes the debt payable: V1 rejects a selector
# targeting an unregistered field, so dropping the name here would have meant
# nobody could write the selector without first undoing this file.
_IDENTITY: frozenset[str] = frozenset({
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "bill_date",
    "tax_id",
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

# Periods and line-item column names. Column names live in the field set because
# V1 checks a row group's columns against it too.
_TABLE: frozenset[str] = frozenset({
    "service_period",
    "service_dates",
    "order_date",
    "sale_type",
    "total_weight",
    "balance",
    "description",
    "quantity",
    "quantity_ordered",
    "quantity_shipped",
    "unit_price",
    "amount",
    "charges",
    "payments",
    "weight",
    "unit_of_measure",
    "item_code",
    "trans_no",
    "reference",
    "date",
    "service_date",
    "taxable",
    "label",
    "work_order",
    "id",
    "name",
    "address",
})

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

DOC_TYPES: tuple[str, ...] = (
    "credit_memo",
    "contra_invoice",
    "invoice_with_attachment",
    "statement_of_account",
    "own_paperwork",
    "standard_invoice",
)


def fields_for(doc_type: str) -> frozenset[str]:
    """Every field name a selector may target. Uniform across Northstar's types.

    The six doc types differ in how they are *classified* and *routed*, not in
    what they contain: a contra invoice has the same fields as a standard one
    with the signs reversed. Splitting the field set per type would invite a
    persona that works on `standard_invoice` and fails validation the month a
    vendor issues a credit.
    """
    return FIELDS


def required_fields(doc_type: str) -> frozenset[str]:
    return REQUIRED


def required_any_of(doc_type: str) -> tuple[frozenset[str], ...]:
    return REQUIRED_ANY_OF


def derived_only_fields(doc_type: str) -> frozenset[str]:
    return DERIVED_ONLY
