# Grammar vocabulary (generated from the code, not from prose)

Anything not on these lists is rejected by the schema before your persona ever runs.

## Regions

- `any-page`
- `first-page`
- `header-block`
- `label-block`
- `last-page`
- `last-table-row`
- `line_items`
- `near-anchor`
- `remittance-block`
- `same-cell`
- `same-row`
- `top-center`
- `top-left`
- `top-right`
- `totals-block`

## Named pattern kinds

- `account_number`
- `currency`
- `currency_signed`
- `date`
- `date_loose`
- `decimal`
- `digits_run`
- `integer`
- `phone`
- `postal_code`
- `tax_id`
- `text`
- `text_block`

You may also supply a regex instead of a named kind. It must describe the
SHAPE of the value, not contain the value.

## Adjust ops

- `collapse_internal_spaces`
- `crosscheck_balance_composition`
- `crosscheck_duplicate_anchor`
- `crosscheck_filename`
- `crosscheck_line_sum`
- `crosscheck_scanline`
- `crosscheck_total_composition`
- `dedupe_preserve_order`
- `derive_amount_payable`
- `infer_currency`
- `join_lines_comma`
- `lowercase`
- `normalize_credit_sign`
- `normalize_date_iso`
- `parens_to_negative`
- `prefer_current_charges_line`
- `resolve_bill_to_alias`
- `resolve_carried_balance`
- `resolve_vendor_alias`
- `strip_currency_symbols`
- `strip_internal_whitespace`
- `subtract_prior_balance_if_present`
- `trailing_cr_to_negative`
- `trim`
- `uppercase`

## Doc types declared by the `northstar` pack

- `contra_invoice`
- `credit_memo`
- `invoice_with_attachment`
- `own_paperwork`
- `standard_invoice`
- `statement_of_account`

## Field names declared by the `northstar` pack

- `account_number`
- `address`
- `amount`
- `balance`
- `balance_due`
- `bill_date`
- `bill_to_address`
- `bill_to_attention`
- `bill_to_email`
- `bill_to_name`  **(required)**
- `bol_number`
- `charges`
- `current_charges`
- `customer_po`
- `date`
- `description`
- `discount_amount`
- `discount_date`
- `due_date`
- `id`
- `invoice_date`
- `invoice_number`
- `item_code`
- `label`
- `name`
- `order_date`
- `payment_terms`
- `payments`
- `payments_credits`
- `please_pay`
- `prior_balance`
- `quantity`
- `quantity_ordered`
- `quantity_shipped`
- `reference`
- `remit_address`
- `remit_payee`
- `return_address`
- `sale_type`
- `seal_number`
- `service_date`
- `service_dates`
- `service_location`
- `service_period`
- `subtotal`
- `tax_amount`
- `tax_id`
- `taxable`
- `total_printed`
- `total_weight`
- `trans_no`
- `unit_of_measure`
- `unit_price`
- `vendor_account_number`
- `vendor_address`
- `vendor_name`
- `weight`
- `work_order`
