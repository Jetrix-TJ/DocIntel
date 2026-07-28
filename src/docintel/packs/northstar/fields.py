"""Northstar's field set (`docs/packs/northstar-recycling.md` section 2).

Three sets per doc type, and the distinction between them is what V1, V10 and V13
each check:

* `FIELDS` - every name a selector may target (V1)
* `REQUIRED` - every name that must have a selector before a persona leaves
  `draft` (V13)
* `DERIVED_ONLY` - every name no selector may ever target (V10)

`amount_payable` is in `REQUIRED` **and** `DERIVED_ONLY`, which is not a
contradiction: the record must carry it and no selector may read it off a page.
V13 exempts derived-only fields for exactly this reason - without that exemption
the two rules would make every Northstar persona unwritable.
"""

from __future__ import annotations

# Required on every doc type (section 2, "Required - every doc_type").
_CORE: frozenset[str] = frozenset({
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "total_printed",
    "amount_payable",
    "currency",
    "bill_to_name",
})

# Commercial terms. `prior_balance` and `current_charges` are marked optional in
# the spec table because five of six documents do not print them - EDCO does, and
# it is the F1 trap.
_TERMS: frozenset[str] = frozenset({
    "due_date",
    "payment_terms",
    "prior_balance",
    "prior_balance_basis",
    "current_charges",
    "payments_credits",
    "subtotal",
    "tax_amount",
    "tax_id",
    "discount_date",
    "discount_amount",
    "please_pay",
    "balance_due",
    # EDCO prints a billing date and no invoice date; the DD pack uses it too.
    "bill_date",
})

# Allocation: which end site the cost belongs to (F13).
_ALLOCATION: frozenset[str] = frozenset({
    "service_location",
    "vendor_account_number",
    "vendor_account_number_normalized",
    "account_number",
    "account_number_normalized",
})

# Identity and contact detail the gold labels carry.
_IDENTITY: frozenset[str] = frozenset({
    "remit_payee",
    "vendor_legal_name",
    "vendor_address",
    "vendor_phone",
    "vendor_email",
    "vendor_website",
    "vendor_parent_reference",
    "remit_address",
    "return_address",
    "bill_to_address",
    "bill_to_attention",
    "bill_to_email",
    "account_name",
    "billing_group",
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
    _CORE | _TERMS | _ALLOCATION | _IDENTITY | _MATCH_KEYS | _TABLE
)

# What must have a selector before a persona can leave `draft` (V13).
#
# Deliberately much shorter than the spec's "required" table, and each omission
# is a corpus fact rather than a convenience:
#
#   currency        produced by the F14 inference ladder, not by a selector.
#                   Demanding one would force every persona to invent it.
#   invoice_number  three of the ten corpus documents print none at all (F6) -
#                   EDCO among them. That is the entire reason the identity
#                   ladder falls back to account+period, so requiring a selector
#                   here would make the documents F6 was written for unwritable.
#   invoice_date    EDCO prints a billing date and no invoice date.
#   vendor_name     supplied by the alias table's display names when the
#                   letterhead is unreadable, the same way `currency` comes from
#                   the F14 ladder. Veritiv's name shares a flattened line with
#                   the invoice header block; Lumen's letterhead is an IMAGE and
#                   Windstream's text layer breaks the brand mid-word. Demanding a
#                   selector would make those three unwritable.
#
# What remains is what every document in the corpus genuinely carries.
REQUIRED: frozenset[str] = frozenset({
    "total_printed",
    "amount_payable",
    "bill_to_name",
})

# Section 2 marks exactly one field derived-only. `core.models.DERIVED_ONLY`
# already covers `amount_payable` and its companions; this set is for names the
# PACK adds on top, and Northstar adds none.
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


def derived_only_fields(doc_type: str) -> frozenset[str]:
    return DERIVED_ONLY
