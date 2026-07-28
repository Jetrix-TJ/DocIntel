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

    Four comparison kinds:
      exact    - plain equality
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
    if kind == "superset":
        if actual is None:
            return not expected
        return set(expected) <= set(actual)
    if kind == "set":
        if actual is None:
            return not expected
        return set(expected) == set(actual)
    return expected == actual


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
)

CHECKED_DERIVED = ("amount_payable", "payable_basis", "document_identity", "identity_basis")

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
                lambda r, n=name: r["fields"].get(n),
                kind="money" if name in MONEY_FIELDS else "exact",
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
