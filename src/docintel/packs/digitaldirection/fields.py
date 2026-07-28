"""Digital Direction's field set (pack spec section 3).

**What differs most from the AP pack is identity.** Three of the four carriers
print no invoice number at all, so `account_number` + `bill_date` is the identity
key (F6) - which is why `account_number` is required here and `invoice_number` is
not, the reverse of what an AP pack would say.
"""

from __future__ import annotations

_IDENTITY: frozenset[str] = frozenset({
    "account_number",
    "account_number_normalized",
    "account_name",
    "invoice_number",
    "bill_date",
    "invoice_date",
    "service_period",
    "telephone_number",
    "circuit_id",
    "billing_group",
})

# The F1 core. All four amounts matter on every bill, because the whole point of
# this pack is that they differ.
_AMOUNTS: frozenset[str] = frozenset({
    "prior_balance",
    "prior_balance_basis",
    "payments_credits",
    "current_charges",
    "total_printed",
    "amount_payable",
    "taxes_and_fees",
    "tax_amount",
    "subtotal",
    "balance_due",
    "please_pay",
    "balance_from_last_statement",
    "amount_previously_due",
    "credits_adjustments",
    "balance",
    "currency",
})

# Allocation - the product. Chargeback is per circuit / service location.
_ALLOCATION: frozenset[str] = frozenset({
    "service_location",
    "bill_to_name",
    "bill_to_address",
    "bill_to_attention",
    "bill_to_email",
    "remit_payee",
    "remit_address",
    "return_address",
    "carrier_canonical",
    "vendor_name",
    "vendor_legal_name",
    "vendor_address",
    "vendor_phone",
    "vendor_email",
    "vendor_website",
    "vendor_parent_reference",
})

_DATES: frozenset[str] = frozenset({
    "due_date", "payment_terms", "discount_date", "discount_amount",
    "payments_included_through", "order_date", "service_dates",
})

# Row-group column names. V1 checks a row group's columns against the field set.
_TABLE: frozenset[str] = frozenset({
    "label", "amount", "description", "quantity", "unit_price", "charges",
    "payments", "date", "reference", "item_code", "id", "name", "address",
    "sale_type", "total_weight", "taxable", "unit_of_measure", "weight",
    "trans_no", "service_date", "quantity_ordered", "quantity_shipped",
})

FIELDS: frozenset[str] = _IDENTITY | _AMOUNTS | _ALLOCATION | _DATES | _TABLE

# `account_number` rather than `invoice_number`: three of the four carriers print
# no invoice number, and the identity ladder falls back to account+period for
# exactly that reason (F6).
REQUIRED: frozenset[str] = frozenset({
    "account_number",
    "bill_date",
    "total_printed",
    "amount_payable",
    "bill_to_name",
})

# Populated when the field set narrows to printed values only. Empty here means
# V13's any-of clause is a no-op, so this task changes no behaviour.
REQUIRED_ANY_OF: tuple[frozenset[str], ...] = ()

DERIVED_ONLY: frozenset[str] = frozenset()

# No `statement_of_account`, deliberately. See ladder.py - Centracom's page 1 is
# titled `Account Summary` and says "statement" twice.
DOC_TYPES: tuple[str, ...] = ("credit_memo", "disconnect_notice", "telecom_bill")


def fields_for(doc_type: str) -> frozenset[str]:
    return FIELDS


def required_fields(doc_type: str) -> frozenset[str]:
    return REQUIRED


def required_any_of(doc_type: str) -> tuple[frozenset[str], ...]:
    return REQUIRED_ANY_OF


def derived_only_fields(doc_type: str) -> frozenset[str]:
    return DERIVED_ONLY
