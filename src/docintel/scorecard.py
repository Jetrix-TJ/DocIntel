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
