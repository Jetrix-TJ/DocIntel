"""Run the gold corpus through the real pipeline and score the result.

This is the objective function for the Part B convergence loop. It reads
docs/corpus/gold/*.json and never writes to it.
"""

from __future__ import annotations

import glob
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from docintel.core.confidence import MODIFIERS

GOLD_DIR = os.path.join("docs", "corpus", "gold")
DOCS_DIR = "docs"


@dataclass(frozen=True)
class Assertion:
    name: str
    expected: Any
    getter: Callable[[dict[str, Any]], Any]
    kind: str = "exact"       # "exact" | "money"


def matches(expected: Any, actual: Any, kind: str) -> bool:
    """Compare a gold expectation against a record value.

    Five comparison kinds:
      exact    - plain equality. For our own vocabulary: enums, basis strings.
      text     - transcribed text, case-insensitive and whitespace-collapsed.
                 See the block below for why, and for what was rejected.
      address  - a postal address, compared on alphanumeric content alone.
                 Forgives the punctuation gold inserts; still catches wrong,
                 extra or missing content.
      money    - value equality via Decimal. Gold holds 33876.4 (JSON drops the
                 trailing zero) while the record serializes Decimal("33876.40")
                 as "33876.40"; both denote the same amount.
      superset - every expected member must be present in actual, extras allowed.
                 Used where a pack may legitimately contribute MORE than the gold
                 label records, e.g. tags, or references on a document whose gold
                 label is transcribed for only some pages.
      set      - exact set equality, used where the gold label is complete.
    """
    if kind == "money":
        if expected is None or actual is None:
            return expected == actual
        try:
            return Decimal(str(expected)) == Decimal(str(actual))
        except (InvalidOperation, ValueError):
            return False
    if kind == "text":
        # Transcribed text, compared case-insensitively and whitespace-collapsed.
        #
        # DECIDED IN C5b, and the alternative was worse. EDCO prints
        # `EDCO WASTE & RECYCLING SERVICE` while its gold label reads `EDCO Waste
        # & Recycling Service`: the document is all-caps and the labeller
        # title-cased it. The extraction is CORRECT, and a scorecard that fails on
        # case is measuring the labeller's typing.
        #
        # The rejected alternative was a `title_case` adjust op, which would be
        # ACTIVELY WRONG: `LLC` -> `Llc`, `P.O. Box` -> `P.o. Box`, `OCC` -> `Occ`.
        # Correct title-casing of company names needs an exceptions list, which is
        # the same unbounded-enumeration trap the C1b review already refused for
        # totals phrases - and it would mean transforming real data to match a
        # label's cosmetic convention.
        #
        # Punctuation is deliberately NOT normalized. `260 S Pacific St, San
        # Marcos, CA 92078` and the same string missing a comma are different
        # transcriptions, and collapsing that difference would stop the assertion
        # measuring anything about how well an address was captured.
        if expected is None or actual is None:
            return expected == actual
        return _text_key(expected) == _text_key(actual)
    if kind == "address":
        # An address, compared on its alphanumeric content alone.
        #
        # Gold systematically inserts a comma between city and state that the
        # documents do not print: `DURANT OK 74702-1550` is labelled
        # `Durant, OK 74702-1550`, `LINDON UT 84042-1960` becomes
        # `Lindon, UT 84042-1960`. It is the same class of labelling convention as
        # the casing decided in C5b - a transcription choice, not a fact about the
        # document - and `join_lines_comma` joins LINES, so no op can insert a
        # comma inside one.
        #
        # An address is the same address whichever way the punctuation falls. What
        # this must NOT forgive is different CONTENT, and it does not: extra or
        # missing tokens change the alphanumeric string, so an over-reaching
        # capture like `5555 PERIMETER DR, DUBLIN OH 43017-3219, How to reach...`
        # still fails. That property is what keeps the assertion meaningful.
        if expected is None or actual is None:
            return expected == actual
        return _alnum_key(expected) == _alnum_key(actual)
    if kind == "superset":
        if actual is None:
            return not expected
        return set(expected) <= set(actual)
    if kind == "set":
        if actual is None:
            return not expected
        return set(expected) == set(actual)
    return expected == actual


def _text_key(value: Any) -> str:
    return " ".join(str(value).split()).casefold()


def _alnum_key(value: Any) -> str:
    """Alphanumeric content only: no case, no punctuation, no whitespace."""
    return "".join(ch for ch in str(value).casefold() if ch.isalnum())


# Fields whose value is a postal address or a site description. Compared on
# content rather than punctuation - see the `address` kind in `matches`.
ADDRESS_FIELDS: frozenset[str] = frozenset({
    "bill_to_address", "vendor_address", "remit_address", "return_address",
    "service_location",
})


# Fields whose value is OUR OWN vocabulary rather than text transcribed off a
# page. These stay case-sensitive: `payable_basis` is an enum the pipeline emits,
# and a scorecard that accepted `Current_Charges` for `current_charges` would stop
# catching a typo in code we wrote.
EXACT_TEXT_FIELDS: frozenset[str] = frozenset({
    "prior_balance_basis", "currency", "currency_basis", "sale_type",
})


def load_gold() -> list[dict[str, Any]]:
    out = []
    for path in sorted(glob.glob(os.path.join(GOLD_DIR, "*.json"))):
        with open(path) as fh:
            out.append(json.load(fh))
    return out


MONEY_FIELDS = frozenset({
    "total_printed", "current_charges", "prior_balance", "payments_credits",
    "subtotal", "tax_amount", "balance_due", "please_pay", "amount_payable",
    "taxes_and_fees", "discount_amount", "balance_from_last_statement",
    "amount_previously_due", "credits_adjustments", "balance", "total_weight",
})

# Every entry here is tied to a finding in docs/corpus-analysis.md. An earlier
# draft asserted only 12 scalar fields, which left the loop blind to ten
# documented findings and all fifteen tags - it could have reached "10/10 green"
# with an empty reference_list and no tags at all.
CHECKED_FIELDS = (
    # amounts, and the F1/F1b machinery that decides what is actually payable
    "total_printed", "current_charges", "prior_balance", "prior_balance_basis",
    "payments_credits", "subtotal", "tax_amount", "taxes_and_fees", "please_pay",
    "balance_due",
    # identity (F5, F6)
    "invoice_number", "vendor_name", "remit_payee", "carrier_canonical",
    "account_number", "vendor_account_number", "telephone_number", "circuit_id",
    # dates and terms (F18)
    "invoice_date", "bill_date", "due_date", "payment_terms",
    "discount_date", "discount_amount",
    # allocation and guards (F13)
    "bill_to_name", "service_location",
    # currency (F14)
    "currency",
    # match keys carried as scalar fields (F11)
    "customer_po", "seal_number", "bol_number",

    # --- added in C3b -----------------------------------------------------
    # A coverage audit found 29 gold field names present across 73 occurrences
    # that this tuple never listed, so nothing checked them. The largest were
    # `bill_to_address` and `currency_basis`, both in all ten gold files - and
    # `currency_basis` is C3's own output, which makes it the same class of miss
    # as the tags / reference_list / page_roles / lane gaps before it.
    #
    # Only the two `*_note` fields are deliberately excluded: they are the
    # labeller's prose explaining a judgement, not a value a pipeline produces.

    # currency provenance (F14) - the ladder rung that answered
    "currency_basis",
    # the money fields MONEY_FIELDS already declared but nothing asserted
    "amount_previously_due", "balance", "balance_from_last_statement",
    "credits_adjustments", "total_weight",
    # normalized identity forms (F6). The printed form and the joinable form are
    # different facts and a record that carries only one has lost the other.
    "account_number_normalized", "vendor_account_number_normalized",
    # allocation and remittance addresses - where the money goes and who owes it
    "bill_to_address", "bill_to_attention", "bill_to_email",
    "vendor_address", "vendor_legal_name", "vendor_parent_reference",
    "remit_address", "return_address",
    # vendor contact details
    "vendor_phone", "vendor_email", "vendor_website",
    # account structure and periods
    "account_name", "billing_group", "service_period", "service_dates",
    "payments_included_through", "order_date", "sale_type",
    # the H.S.T. number itself, which is the F14 anchor hazard's own value
    "tax_id",
)

CHECKED_DERIVED = ("amount_payable", "payable_basis", "document_identity", "identity_basis")

# Every `check` name appearing in any gold file's `assertions` array, and what
# this scorecard does about it. 55 names, 68 entries.
#
# This table exists because the array was read by nothing at all until C3b, and
# that was invisible: no test failed, no count looked wrong, and the loop could
# have reached 10/10 while the entire confidence-modifier mechanism went
# unchecked. `tests/test_scorecard_coverage.py` asserts this table's key set
# equals the set of check names actually present in gold, so a new gold file - or
# a new assertion in an existing one - fails loudly until somebody classifies it.
#
# Four verdicts:
#   covered:<name>   an assertion this scorecard already emits checks the same
#                    fact. Listing it here is the record of having checked that.
#   wired:<name>     newly asserted in C3b.
#   documentation    narrative, or arithmetic whose components are each asserted
#                    individually, with no distinct observable on the record.
#   deferred:<why>   needs a capability that does not exist yet.
GOLD_ASSERTION_COVERAGE: dict[str, str] = {
    # -- the payable, and the arithmetic behind it (F1, F1b, F8) -------------
    "amount_payable": "covered:derived.amount_payable",
    "amount_payable_is_null": "covered:derived.amount_payable",
    "payable_basis": "covered:derived.payable_basis",
    "payable_mismatch": "covered:derived.amount_payable",
    "payable_composition": "wired:arithmetic.balance_closed",
    "balance_composition": "wired:arithmetic.balance_closed",
    "prior_balance_found_and_cleared": "wired:arithmetic.balance_closed",
    "total_composition": "wired:arithmetic.total_closed",
    "current_charges_composition": "wired:arithmetic.total_closed",
    "new_charges_composition": "wired:arithmetic.total_closed",
    "line_sum": "wired:arithmetic.lines_closed",
    "line_extended": "wired:arithmetic.lines_closed",
    "arith_balance_mismatch_applied": "wired:confidence_modifiers",
    "prior_balance_is_net": "covered:fields.prior_balance_basis",
    "prior_balance_derivation": "covered:fields.prior_balance",
    "amount_previously_due_is_zero": "covered:fields.amount_previously_due",
    "discount_is_one_percent": "covered:fields.discount_amount",
    "every_line_qty_times_price": "documentation",
    "occ_line_math": "documentation",
    "payable_is_date_dependent": "documentation",
    # `no_prior_balance` is deliberately NOT wired. An "this field must be
    # absent" assertion is satisfied by a pipeline that extracts nothing, so it
    # would have been a free pass rather than a measurement.
    "no_prior_balance": "documentation",

    # -- identity (F5, F6) --------------------------------------------------
    "identity_basis": "covered:derived.identity_basis",
    "identity_fallback": "covered:derived.identity_basis",
    "account_whitespace_stripped": "covered:fields.account_number_normalized",
    "alias_collapse": "wired:derived.vendor_canonical",
    "alias_collapse_three_names": "wired:derived.vendor_canonical",
    "vendor_alias": "wired:derived.vendor_canonical",
    "payee_preferred_over_logo": "covered:fields.remit_payee",
    "state_entity_pattern": "covered:reference_list.values",

    # -- signs, currency, tax (F4, F14) -------------------------------------
    "credit_parsed_negative": "covered:fields.payments_credits",
    "credit_suffix_parsed": "covered:fields.payments_credits",
    "parens_parsed_negative": "covered:line_items.amounts",
    "total_is_positive_despite_contra": "covered:fields.total_printed",
    "currency_inferred": "covered:fields.currency",
    "hst_anchor_hazard": "covered:fields.tax_id",

    # -- the scan line (F7) -------------------------------------------------
    "scanline_agrees_with_printed_total": "wired:arithmetic.scanline_agrees",
    "scanline_three_way": "wired:arithmetic.scanline_agrees",

    # -- tables and rows (F15, F19) -----------------------------------------
    "empty_amount_cell_not_a_failure": "covered:line_items.amounts",
    "zero_value_row_preserved": "covered:line_items.count",

    # -- classification and routing -----------------------------------------
    "not_a_batch": "covered:doc_type",
    "not_misclassified_as_statement": "covered:doc_type",
    "past_due_is_a_tag_not_a_type": "covered:tags",
    "review_forced": "covered:review_flag",
    "review_not_needed": "covered:review_flag",
    "values_never_from_supporting": "covered:page_roles",
    "totals_not_on_page_1": "covered:fields.total_printed",

    # -- fields ------------------------------------------------------------
    "service_location_captured": "covered:fields.service_location",
    "due_date_unparsed": "covered:fields.due_date",
    "reference_dedupe": "covered:reference_list.values",

    # -- what must NOT be captured (F3) -------------------------------------
    # Federal Recycling's flattened annotations are invisible to the text layer,
    # so "the overlay value was not captured" needs a pack that knows which
    # values are overlays. That is C5.
    "annotation_dates_not_captured": "deferred:C5 pack annotation exclusion",
    "annotation_values_excluded": "deferred:C5 pack annotation exclusion",
    "promo_block_ignored": "documentation",
    "watermark_not_captured": "documentation",

    # -- corroboration whose only observable is folded into confidence ------
    # `ctx.boosts` is not emitted on the record; a boost shows up only as a
    # slightly higher confidence number, which no gold label predicts.
    "duplicate_anchor_agrees": "documentation",
    "filename_crosscheck": "wired:derived.filename_crosscheck",
}

# Columns of a line-item row that hold an amount rather than a rate or a count.
# `unit_price`, `quantity`, `weight` and `quantity_ordered` are deliberately
# absent: summing unit prices is meaningless, and including them would make the
# assertion fail for reasons that say nothing about extraction quality.
#
# Column names come from the PERSONA, and the expectations here come from the
# hand-written gold label, so the two have to agree. That coupling is
# deliberate - it is what forces a C5 persona to describe the table the way the
# document actually prints it (F19) rather than inventing its own vocabulary.
LINE_ITEM_AMOUNT_COLUMNS = frozenset({"amount", "charges", "balance", "total"})


def _money_key(value: Any) -> str:
    """Canonical string for a money value, so 140.9 and "140.90" compare equal.

    Gold holds JSON numbers (which drop trailing zeros) while a record holds the
    string a Decimal serialized to. `normalize` collapses both to the same
    representation; `format(..., "f")` keeps it out of scientific notation.
    """
    if value is None:
        return ""
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except (InvalidOperation, ValueError):
        return str(value)


def _line_item_amounts(rows: Any) -> list[str]:
    """Every amount in a table, as a sorted multiset.

    The plan called for a signed *sum*. A multiset is used instead because it
    catches everything a sum does and one thing a sum cannot: two rows whose
    amounts are swapped, or a pair of compensating errors, net to the same total
    and would pass silently. It costs nothing extra to compare.

    A sum would also have implied an arithmetic claim the corpus does not
    support. EDCO's statement table carries its own `CURRENT CHARGES:` summary
    row *inside* the table body, so its amounts total 437.58 against a printed
    total of 367.96. That is the table faithfully transcribed, not an error -
    proving closure is `crosscheck_line_sum`'s job at Stage 6, and it reports a
    confidence modifier rather than a scorecard failure.
    """
    out: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for column, value in row.items():
            if column in LINE_ITEM_AMOUNT_COLUMNS and value is not None:
                out.append(_money_key(value))
    return sorted(out)


def _pairs(rows: Any, first: str, second: str) -> list[tuple[str, str]]:
    """A row list reduced to two named columns, sorted - order is not asserted."""
    out: list[tuple[str, str]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        out.append((str(row.get(first, "")), _money_key(row.get(second))))
    return sorted(out)


def _id_name_pairs(rows: Any) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        out.append((str(row.get("id", "")), str(row.get("name", ""))))
    return sorted(out)


def _field_kind(name: str, expected: Any) -> str:
    """How a gold field should be compared: money, transcribed text, or exactly."""
    if name in MONEY_FIELDS:
        return "money"
    if name in ADDRESS_FIELDS:
        return "address"
    if isinstance(expected, str) and name not in EXACT_TEXT_FIELDS:
        return "text"
    return "exact"


def _field_value(record: dict[str, Any], name: str) -> Any:
    """A gold-labelled field, wherever the pipeline chose to put it.

    Gold labels a *fact about the document* and does not say whether a pipeline
    should read it off the page or compute it. `currency` is the clear case: an
    ISO code printed on the invoice is extracted, while U-PAK's CAD is inferred
    from its H.S.T. line, so `infer_currency` writes both it and `currency_basis`
    to `derived` - correctly, because nothing read them off a page. Gold puts both
    under `fields`.

    Looking in `fields` first and then `derived` means the scorecard scores the
    answer rather than the provenance. Provenance is not unmeasured: it is exactly
    what `currency_basis` and `payable_basis` record, and those are asserted too.
    """
    value = record.get("fields", {}).get(name)
    if value is None:
        value = record.get("derived", {}).get(name)
    return value


def _expected_modifiers(gold: dict[str, Any]) -> list[str]:
    """Confidence modifiers this document's gold label implies (spec section 5).

    The whole section 5 mechanism - 16 modifiers - was unasserted before C3b.
    Nothing in the scorecard would have noticed if `arith_balance_mismatch`
    stopped being applied, which is the one that decides whether a human ever
    looks at U-PAK's unexplained 48.92.

    Derived from three gold signals rather than a hand-written list, so a new
    gold file gets its expectations for free:

    * `classification.text_source == "ocr"` -> `ocr_source` (F2)
    * an `ocr_only` / `has_flattened_annotations` tag -> the matching modifier
    * any `assertions` entry named `<modifier>_applied` with `equals: true`

    `handwritten_supporting` deliberately implies nothing: section 5's
    `handwriting_detected` is about handwriting on a *primary* page, and that tag
    says the opposite.
    """
    cls = gold["classification"]
    tags = set(cls.get("tags", []))
    expected: set[str] = set()

    if cls.get("text_source") == "ocr" or "ocr_only" in tags:
        expected.add("ocr_source")
    if "has_flattened_annotations" in tags:
        expected.add("flattened_annotations")

    for entry in gold.get("assertions") or []:
        check = str(entry.get("check", ""))
        if check.endswith("_applied") and entry.get("equals") is True:
            expected.add(check[: -len("_applied")])

    return sorted(expected & set(MODIFIERS))


def _closure_assertions(gold: dict[str, Any]) -> list[Assertion]:
    """Composite "the arithmetic ran and closed" assertions.

    Each gold `*_composition` / `line_sum` / `scanline_agrees_*` entry documents
    arithmetic whose components are already asserted individually. What was NOT
    observable is whether the pipeline *checked* it: the cross-check ops report a
    modifier, and nothing asserted modifiers.

    These are deliberately **composite** - "the enabling value exists AND no
    mismatch modifier was applied" - rather than a bare "modifier is absent". A
    bare absence check passes trivially on a pipeline that computed nothing,
    which would have added eight free passes to the numerator and made the score
    read better while measuring nothing. Paired this way each one fails until the
    op genuinely runs and closes.
    """
    checks = {str(a.get("check")) for a in (gold.get("assertions") or [])}
    items: list[Assertion] = []

    if "balance_composition" in checks:
        items.append(Assertion(
            "arithmetic.balance_closed", True,
            lambda r: (
                r.get("derived", {}).get("amount_payable") is not None
                and "arith_balance_mismatch" not in r.get("confidence_modifiers", [])
            ),
        ))
    if {"total_composition", "current_charges_composition",
            "new_charges_composition"} & checks:
        items.append(Assertion(
            "arithmetic.total_closed", True,
            lambda r: (
                _field_value(r, "total_printed") is not None
                and "arith_total_mismatch" not in r.get("confidence_modifiers", [])
            ),
        ))
    if {"line_sum", "line_extended"} & checks:
        items.append(Assertion(
            "arithmetic.lines_closed", True,
            lambda r: (
                bool(r.get("line_items"))
                and "arith_lines_mismatch" not in r.get("confidence_modifiers", [])
            ),
        ))
    if any(c.startswith("scanline_agrees") for c in checks):
        items.append(Assertion(
            "arithmetic.scanline_agrees", True,
            lambda r: (
                r.get("scanline") is not None
                and "scanline_mismatch" not in r.get("confidence_modifiers", [])
            ),
        ))
    return items


def _assertion_equals(gold: dict[str, Any], *checks: str) -> Any:
    """The `equals` value of the first named gold assertion present, or None."""
    for entry in gold.get("assertions") or []:
        if str(entry.get("check")) in checks and "equals" in entry:
            return entry["equals"]
    return None


def assertions_for(gold: dict[str, Any]) -> list[Assertion]:
    cls = gold["classification"]
    fields = gold.get("fields", {})
    derived = gold.get("derived", {})
    routing = gold["expected_routing"]

    items: list[Assertion] = [
        Assertion("doc_type", cls["doc_type"], lambda r: r["doc_type"]),
        Assertion("text_source", cls["text_source"], lambda r: r["text_source"]),
        Assertion("review_flag", routing["review_flag"], lambda r: r["review_flag"]),
        Assertion("regen_flag", routing["regen_flag"], lambda r: r["regen_flag"]),
        # `lane` is specified in all ten gold files and was never asserted - the
        # same blind-spot class as the tags/reference_list/page_roles gaps before
        # it. The lane IS the routing decision, so a scorecard that checks the
        # two boolean flags but not which lane a document landed in cannot tell
        # a correctly-routed document from a wrongly-routed one. Implementing it
        # is C4's job (`s7_gate` is still a stub); measuring it starts now, so
        # C4 has a visible target instead of an unstated one.
        Assertion("lane", routing["lane"], lambda r: r.get("lane")),
        # F10 / page_roles: this appears on every emitted record and in every
        # gold file, but was never asserted here - the same blind-spot class
        # as the tags/reference_list gap noted above. kind="exact" (not
        # "set") because order and page count both matter: U-PAK's five
        # primary pages and Complete Beverage's primary+3 supporting are
        # only distinguishable if position is checked, not just membership.
        Assertion("page_roles", cls["page_roles"], lambda r: r.get("page_roles"), kind="exact"),
    ]

    for name in CHECKED_FIELDS:
        if fields.get(name) is not None:
            items.append(Assertion(
                f"fields.{name}", fields[name],
                lambda r, n=name: _field_value(r, n),
                kind=_field_kind(name, fields[name]),
            ))

    for name in CHECKED_DERIVED:
        if name in derived:
            items.append(Assertion(
                f"derived.{name}", derived[name],
                lambda r, n=name: r["derived"].get(n),
                kind="money" if name in MONEY_FIELDS else "exact",
            ))

    # Tags. Superset, not equality: a pack may legitimately contribute tags the
    # hand-written gold label does not enumerate, but every tag the label DOES
    # record must be present. Without this the loop is blind to F3's forced
    # review, F4's mixed_sign, F14's foreign_currency and twelve others.
    gold_tags = cls.get("tags", [])
    if gold_tags:
        items.append(Assertion(
            "tags", sorted(gold_tags), lambda r: r.get("tags", []), kind="superset",
        ))

    # The four structured keys. Before these existed the loop could not see
    # F7, F8, F14 or F19 at all: four whole gold sections had no corresponding
    # contract key, so "10/10 green" was reachable while extracting no line
    # items, no surcharges and no scan line.

    # Line items (F8, F19). Count and the amount multiset, only where the gold
    # transcription is complete - U-PAK's label records line_items_complete:
    # false precisely because its five-page table was not fully transcribed, and
    # asserting a partial label would fail a record that read the table right.
    gold_line_items = gold.get("line_items")
    if gold_line_items and gold.get("line_items_complete", True):
        items_expected: list[Any] = list(gold_line_items)
        items.append(Assertion(
            "line_items.count", len(items_expected),
            lambda r: len(r.get("line_items") or []),
        ))
        items.append(Assertion(
            "line_items.amounts", _line_item_amounts(items_expected),
            lambda r: _line_item_amounts(r.get("line_items")),
        ))

    # Surcharges (F14). Label/amount pairs: U-PAK's fuel and environmental
    # surcharges are what make its printed total exceed the sum of its services.
    gold_charges = gold.get("charges")
    if gold_charges:
        items.append(Assertion(
            "charges", _pairs(gold_charges, "label", "amount"),
            lambda r: _pairs(r.get("charges"), "label", "amount"),
        ))

    # Scan line (F7). The raw digit run only. The gold label's encodes_* keys are
    # analysis of what the digits mean, not something the pipeline transcribes,
    # and asserting them here would score the label rather than the extraction.
    gold_scanline = gold.get("scanline") or {}
    if gold_scanline.get("raw"):
        items.append(Assertion(
            "scanline.raw", gold_scanline["raw"], lambda r: r.get("scanline"),
        ))

    # Sub-accounts (F13). id/name pairs - U-PAK's 70+ billing identities are the
    # reason a single invoice cannot be allocated to one cost centre.
    gold_sub = gold.get("sub_account")
    if gold_sub:
        items.append(Assertion(
            "sub_account", _id_name_pairs(gold_sub),
            lambda r: _id_name_pairs(r.get("sub_account")),
        ))

    # --- C3b: the confidence-modifier mechanism, previously unmeasured -----
    # Superset, not equality: a pack may legitimately apply modifiers the gold
    # label does not enumerate, but every modifier the label IMPLIES must be
    # present. Added only where gold implies at least one - an empty superset
    # check passes trivially, and seven free passes would make the score read
    # better while measuring nothing.
    expected_modifiers = _expected_modifiers(gold)
    if expected_modifiers:
        items.append(Assertion(
            "confidence_modifiers", expected_modifiers,
            lambda r: r.get("confidence_modifiers", []), kind="superset",
        ))

    # Composite "the arithmetic ran and closed" checks - see _closure_assertions.
    items.extend(_closure_assertions(gold))

    # Two derived values that exist only inside the gold `assertions` array, so
    # the derived loop above cannot see them.
    filename_crosscheck = _assertion_equals(gold, "filename_crosscheck")
    if filename_crosscheck is not None:
        items.append(Assertion(
            "derived.filename_crosscheck", filename_crosscheck,
            lambda r: r.get("derived", {}).get("filename_crosscheck"),
        ))

    # F5: two corpus senders print one brand and bill under another. The gold
    # label records the collapsed canonical name under `alias_collapse`.
    vendor_canonical = _assertion_equals(
        gold, "alias_collapse", "alias_collapse_three_names", "vendor_alias"
    )
    if vendor_canonical is not None:
        items.append(Assertion(
            "derived.vendor_canonical", vendor_canonical,
            lambda r: r.get("derived", {}).get("vendor_canonical"),
        ))

    # Reference list (F11). Exact set only where the gold label is complete;
    # subset where only some pages were transcribed, so a partial label can never
    # fail a record that found MORE keys than were written down.
    refs = [e["value"] for e in gold.get("reference_list", [])]
    if refs:
        complete = gold.get("reference_list_complete", True)
        items.append(Assertion(
            "reference_list.values", sorted(refs),
            lambda r: [e["value"] for e in r.get("reference_list", [])],
            kind="set" if complete else "superset",
        ))

    return items


def replay_gold(runner_factory: Callable[[], Any]) -> dict[str, Any]:
    documents = []
    a_passed = a_total = 0

    for gold in load_gold():
        runner = runner_factory()
        source = os.path.join(DOCS_DIR, gold["source_file"])
        record = runner.process(document_id=gold["gold_id"], source_path=source)

        results = []
        for assertion in assertions_for(gold):
            try:
                actual = assertion.getter(record)
            except Exception as exc:  # noqa: BLE001
                actual = f"<error: {exc}>"
            results.append({
                "name": assertion.name,
                "kind": assertion.kind,
                "expected": assertion.expected,
                "actual": actual,
                "passed": matches(assertion.expected, actual, assertion.kind),
            })

        passed_count = sum(1 for r in results if r["passed"])
        a_passed += passed_count
        a_total += len(results)
        documents.append({
            "gold_id": gold["gold_id"],
            "source_file": gold["source_file"],
            "priority": gold.get("priority"),
            "teaches": gold.get("teaches", []),
            "passed": passed_count == len(results),
            "passed_count": passed_count,
            "total_count": len(results),
            "assertions": results,
        })

    passed_docs = sum(1 for d in documents if d["passed"])
    return {
        "documents": documents,
        "summary": {
            "total": len(documents),
            "passed": passed_docs,
            "failed": len(documents) - passed_docs,
            "assertions_passed": a_passed,
            "assertions_total": a_total,
        },
    }
