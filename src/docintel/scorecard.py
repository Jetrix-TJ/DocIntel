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

    Money needs value equality, not string equality: gold holds 33876.4 (JSON
    drops the trailing zero) while the record serializes Decimal("33876.40") as
    "33876.40". Both denote the same amount.
    """
    if kind != "money":
        return expected == actual
    if expected is None or actual is None:
        return expected == actual
    try:
        return Decimal(str(expected)) == Decimal(str(actual))
    except (InvalidOperation, ValueError):
        return False


def load_gold() -> list[dict[str, Any]]:
    out = []
    for path in sorted(glob.glob(os.path.join(GOLD_DIR, "*.json"))):
        with open(path) as fh:
            out.append(json.load(fh))
    return out


MONEY_FIELDS = frozenset({
    "total_printed", "current_charges", "prior_balance", "payments_credits",
    "subtotal", "tax_amount", "balance_due", "please_pay", "amount_payable",
})

CHECKED_FIELDS = (
    "total_printed", "current_charges", "prior_balance", "subtotal", "tax_amount",
    "invoice_number", "invoice_date", "vendor_name", "account_number", "bill_date",
    "currency", "service_location",
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
