"""Digital Direction's field set (pack spec section 3).

**What differs most from the AP pack is identity.** Three of the four carriers
print no invoice number at all, so `account_number` + `bill_date` is the identity
key (F6) - which is why `account_number` is required here and `invoice_number` is
not, the reverse of what an AP pack would say.

Narrowed to printed-fields-only: every name in `FIELDS` is a value that appears
as ink on the page, never one computed from other fields. Three sets per doc
type, and the distinction between them is what V1, V10 and V13 each check:

* `FIELDS` - every name a selector may target (V1)
* `REQUIRED` / `REQUIRED_ANY_OF` - what must be covered before a persona leaves
  `draft` (V13)
* `DERIVED_ONLY` - every name no selector may ever target (V10)

`core.models.DERIVED_ONLY` already covers `amount_payable` and its companions,
and none of them are registered here any more - a derived value has no selector
to write, so there is nothing left for this pack's own `DERIVED_ONLY` to add.
"""

from __future__ import annotations

# Printed identity. `carrier_canonical` is gone: it is the alias table's output,
# resolved by hooks.resolve_carrier_fingerprint, not a string on the page.
_IDENTITY: frozenset[str] = frozenset({
    "account_number",
    "account_name",
    "invoice_number",
    "bill_date",
    "invoice_date",
    "service_period",
    "telephone_number",
    "circuit_id",
})

# Amounts exactly as printed. No derivation: `amount_payable` and
# `carried_balance` are DERIVED_ONLY — no selector may target them. And
# `prior_balance_basis` is a carrier convention's classification of which
# label supplied the balance rather than a figure anyone printed.
_AMOUNTS: frozenset[str] = frozenset({
    "prior_balance",
    "payments_credits",
    "current_charges",
    "total_printed",
    "taxes_and_fees",
    "tax_amount",
    "subtotal",
    "balance_due",
    "please_pay",
    "balance_from_last_statement",
    "amount_previously_due",
    "credits_adjustments",
    "balance",
})

# Allocation - the product. Chargeback is per circuit / service location.
# The vendor-identity tail (legal name, phone, email, website) is gone with it:
# none of those decide where a cost lands.
#
# `vendor_parent_reference` is the exception, and it is registered while
# deliberately unselected. Lumen prints `a CenturyLink company` beside its legal
# name (F5) - literal page text, gold-labelled, and no persona has ever read it.
# That is extraction DEBT rather than a deferral, so `scorecard.CHECKED_FIELDS`
# keeps asserting it and it keeps failing. Registration is what makes the debt
# payable: V1 rejects a selector targeting an unregistered field, so dropping
# the name would have meant nobody could write the selector without first
# undoing this file.
_ALLOCATION: frozenset[str] = frozenset({
    "vendor_parent_reference",
    "service_location",
    "bill_to_name",
    "bill_to_address",
    "bill_to_attention",
    "bill_to_email",
    "remit_payee",
    "remit_address",
    "return_address",
    "vendor_name",
    "vendor_address",
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
# no invoice number (F6), and the field spec measures the carrier account number
# present on 100% of readable invoices.
#
# `bill_to_name` is required even though this pack does not GUARD on it. The two
# are different questions: `claims()` asks "is this document ours", and the answer
# there is the carrier, because the bill-to varies (see `packs/registry.py`). This
# asks "can we use the record", and a telecom bill whose managed client cannot be
# identified is unusable - the charge has nobody to allocate to.
#
# It is load-bearing rather than tidy. Three of these four personas used to carry
# the client's name as a literal pattern; the pack roster replaced them, which also
# removed the per-selector `required: true` that made an empty bill-to visible to
# `core.coverage`. Naming it here restores that: an unrostered client yields an
# empty required field and routes to `review` instead of auto-approving. V13 does
# not demand a selector for it, because `resolve_bill_to_alias` supplies it
# (`schema.OP_SUPPLIED_FIELDS`).
REQUIRED: frozenset[str] = frozenset({"account_number", "bill_to_name"})

# What a flat set cannot say. Each group needs one covered member.
#
#   date    a carrier prints a bill date, an invoice date or a service period,
#           and which one is a house style. Requiring any single name would
#           make some carrier's persona unwritable.
#   amount  the money a bill leads with is `Total Amount Due` on some carriers
#           and `Current Charges` or `Amount Previously Due` on others, so the
#           requirement is that ONE parseable figure is covered, not which.
REQUIRED_ANY_OF: tuple[frozenset[str], ...] = (
    frozenset({"bill_date", "invoice_date", "service_period"}),
    frozenset({"total_printed", "balance_due", "please_pay",
               "current_charges", "amount_previously_due"}),
)

DERIVED_ONLY: frozenset[str] = frozenset()

# No `statement_of_account`, deliberately. See ladder.py - Centracom's page 1 is
# titled `Account Summary` and says "statement" twice.
DOC_TYPES: tuple[str, ...] = ("credit_memo", "disconnect_notice", "telecom_bill", "contract")

# A contract's field shape genuinely differs from a bill's - it carries a
# contracted rate and a term, never a payable total or a line-item table
# (see corpus-analysis.md F20). Until now every function below ignored its
# `doc_type` argument and returned one shared set regardless of type; that was
# fine while every doc_type this pack declared was bill-shaped, but a contract
# is not, so it needs its own branch rather than silently reusing (or
# polluting) the invoice field set.
_CONTRACT_IDENTITY: frozenset[str] = frozenset({
    "account_number", "circuit_id", "contract_number",
})

_CONTRACT_TERMS: frozenset[str] = frozenset({
    "contracted_rate", "rate_basis", "term_start_date", "term_end_date",
    "term_length_months", "effective_date", "signed_date", "auto_renew",
    "signatory_name", "signatory_title", "supersedes_contract_number",
    "minimum_monthly_fee", "monthly_recurring_charge_total", "one_time_charge_total",
})
# `term_end_date` is registered as an ordinary selectable field, NOT
# derived-only: some templates print an explicit end date, others only state
# a term length a human (or a future op) computes from. No op computes it
# today - there is nothing here to derive it FROM the two selector-scoped
# fields alone without one - so forbidding a selector from ever targeting it
# would leave a printed end date unreadable for no reason.

CONTRACT_FIELDS: frozenset[str] = _CONTRACT_IDENTITY | _CONTRACT_TERMS | frozenset({
    "vendor_name", "bill_to_name",
})

# A contract must name at least one party identity key and at least one date
# that anchors it in time - which exact fields are printed varies by whether
# it's a base agreement (contract_number, effective_date) or an amendment
# referencing one (supersedes_contract_number, signed_date).
CONTRACT_REQUIRED: frozenset[str] = frozenset({"bill_to_name"})
CONTRACT_REQUIRED_ANY_OF: tuple[frozenset[str], ...] = (
    frozenset({"contract_number", "supersedes_contract_number"}),
    frozenset({"effective_date", "signed_date"}),
)
CONTRACT_DERIVED_ONLY: frozenset[str] = frozenset()


def fields_for(doc_type: str) -> frozenset[str]:
    return CONTRACT_FIELDS if doc_type == "contract" else FIELDS


def required_fields(doc_type: str) -> frozenset[str]:
    return CONTRACT_REQUIRED if doc_type == "contract" else REQUIRED


def required_any_of(doc_type: str) -> tuple[frozenset[str], ...]:
    return CONTRACT_REQUIRED_ANY_OF if doc_type == "contract" else REQUIRED_ANY_OF


def derived_only_fields(doc_type: str) -> frozenset[str]:
    return CONTRACT_DERIVED_ONLY if doc_type == "contract" else DERIVED_ONLY
