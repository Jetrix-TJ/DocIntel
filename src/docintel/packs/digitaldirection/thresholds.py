"""Digital Direction's confidence thresholds (pack spec section 6).

**Provisional**, parked with the business. Higher than Northstar's throughout,
and the reason is one document: Centracom is a $20,123.80 error waiting to happen.
"""

from __future__ import annotations

THRESHOLDS: dict[str, float] = {
    # Held at the top of the pack even with the payable deferred: on Centracom
    # this is the figure the right answer is composed from, and a wrong one is a
    # wrong payment however the payable is eventually reached.
    "current_charges": 0.95,
    # A missed prior balance silently reintroduces the F1 bug.
    "prior_balance": 0.95,
    # Scanline-corroborated on all four bills (F7).
    "total_printed": 0.93,
    # The identity key when there is no invoice number (F6).
    "account_number": 0.95,
    # Also part of the identity key, so a weak date makes the key weak.
    "bill_date": 0.93,
    "invoice_number": 0.92,
    "due_date": 0.88,
    # The chargeback key. Human-correctable, so a lower bar (F13).
    "service_location": 0.85,
    "circuit_id": 0.85,
    "taxes_and_fees": 0.85,
    "payments_credits": 0.92,
    "subtotal": 0.85,
    "tax_amount": 0.85,
    "bill_to_name": 0.90,
    "vendor_name": 0.90,
    "remit_payee": 0.90,
    "telephone_number": 0.85,
    "payment_terms": 0.85,
    # Addresses and contact detail: useful, never load-bearing.
    "bill_to_address": 0.80,
    "remit_address": 0.80,
    "vendor_address": 0.75,
    "service_period": 0.85,
}

LINE_ITEM_THRESHOLD = 0.85

for _column in ("label", "amount", "description", "quantity", "unit_price",
                "charges", "payments", "date", "reference"):
    THRESHOLDS.setdefault(_column, LINE_ITEM_THRESHOLD)
