"""Northstar's confidence thresholds (pack spec section 6).

**Provisional.** The spec parks these with the business as an open question and
sets them so the gate is testable from day one. Expect the numbers to move; what
should not move is the shape of the reasoning, which is written next to each one.

One consequence worth stating because it is easy to trip over: the gate's default
threshold is 0.90 and a `draft` persona applies `draft_rules` (x0.85) to every
field, so **a draft persona can never reach the `high` lane**. Every shipped
Northstar persona is therefore `active`. A draft persona is for authoring, not
for production.
"""

from __future__ import annotations

THRESHOLDS: dict[str, float] = {
    # A wrong total is a wrong payment. Highest bar in the pack.
    "total_printed": 0.95,
    # The derived payable. Held at the same bar as total_printed - a wrong
    # payable is a wrong payment however it was reached (Task 11).
    "amount_payable": 0.95,
    # The dedup key. A wrong one merges two invoices or splits one.
    "invoice_number": 0.92,
    # Downstream vendor resolution can recover from a near-miss.
    "vendor_name": 0.90,
    "remit_payee": 0.90,
    # Dates drive payment timing, not payment amount.
    "invoice_date": 0.88,
    "bill_date": 0.88,
    "due_date": 0.88,
    # The Northstar guard. Wrong here means the invoice is not ours at all, so
    # it is held to the same bar as the vendor name.
    "bill_to_name": 0.90,
    # An allocation hint a human corrects routinely (F13).
    "service_location": 0.80,
    # Held as high as the total: a wrong one is a wrong payment amount, printed
    # fields only or not.
    "current_charges": 0.95,
    "prior_balance": 0.95,
    "payments_credits": 0.92,
    # Components, guarded independently by the F8 closure checks.
    "subtotal": 0.85,
    "tax_amount": 0.85,
    "discount_amount": 0.85,
    "please_pay": 0.95,
    # Match keys (F11). A list, and downstream matching tolerates extras.
    "customer_po": 0.85,
    "seal_number": 0.85,
    "bol_number": 0.85,
    # Account identity, which the F6 identity ladder falls back to.
    "vendor_account_number": 0.90,
    "account_number": 0.90,
    # Contact and address detail: useful, never load-bearing.
    "vendor_address": 0.75,
    "remit_address": 0.80,
    "bill_to_address": 0.80,
    "payment_terms": 0.85,
}

# Applied to every line-item column. The line-sum check guards these
# independently, so the per-cell bar is lower than a scalar field's.
LINE_ITEM_THRESHOLD = 0.85

_LINE_ITEM_COLUMNS = (
    "description", "quantity", "quantity_ordered", "quantity_shipped",
    "unit_price", "amount", "charges", "payments", "balance", "weight",
    "unit_of_measure", "item_code", "trans_no", "reference", "date",
    "service_date", "taxable", "label",
)

for _column in _LINE_ITEM_COLUMNS:
    THRESHOLDS.setdefault(_column, LINE_ITEM_THRESHOLD)
