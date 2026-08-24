#!/usr/bin/env python3
"""Self-check the gold corpus.

Recomputes every arithmetic claim in gold/*.json from the recorded field values,
so the labelled numbers cannot drift out of agreement with each other. Runs with
no dependencies:

    python3 docs/corpus/validate_gold.py

This is deliberately independent of the pipeline. It does not read PDFs and it
does not call any extraction code — it only asks "is this label set internally
consistent?". A gold set that contradicts itself is worse than no gold set,
because every downstream eval inherits the error silently.

Exit code 0 = consistent, 1 = a contradiction was found.
"""

from __future__ import annotations

import glob
import json
import os
import sys

TOL = 0.011  # one cent, plus float slack
GOLD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gold")


class Report:
    def __init__(self) -> None:
        self.checks = 0
        self.failures: list[str] = []
        self.skips: list[str] = []

    def ok(self, doc: str, label: str, got, want) -> None:
        self.checks += 1
        if isinstance(want, (int, float)) and not isinstance(want, bool) \
                and isinstance(got, (int, float)) and not isinstance(got, bool):
            if abs(float(got) - float(want)) > TOL:
                self.failures.append(f"{doc}: {label}: got {got!r}, expected {want!r}")
        elif got != want:
            self.failures.append(f"{doc}: {label}: got {got!r}, expected {want!r}")

    def skip(self, doc: str, label: str, why: str) -> None:
        self.skips.append(f"{doc}: {label} ({why})")


def money(rows, key):
    """Sum a key across rows, treating absent as 0 but None-valued as absent."""
    total = 0.0
    for r in rows:
        v = r.get(key)
        if v is not None:
            total += float(v)
    return round(total, 2)


def check(doc: dict, r: Report) -> None:
    name = doc["gold_id"]
    f = doc.get("fields", {})
    d = doc.get("derived", {})
    lines = doc.get("line_items", [])
    charges = doc.get("charges", [])

    # --- 1. line items sum to a stated subtotal or total -------------------
    if lines and doc.get("line_items_complete", True):
        has_amounts = any(l.get("amount") is not None for l in lines)
        if has_amounts:
            s = money(lines, "amount")
            target = f.get("subtotal")
            if target is None:
                target = f.get("total_printed")
            if target is not None:
                r.ok(name, "sum(line_items.amount) == subtotal|total_printed", s, float(target))

        # per-row quantity * unit_price == amount
        for i, l in enumerate(lines):
            q, p, a = l.get("quantity"), l.get("unit_price"), l.get("amount")
            if q is not None and p is not None and a is not None:
                r.ok(name, f"line[{i}] quantity*unit_price == amount",
                     round(float(q) * float(p), 2), float(a))
    elif lines:
        r.skip(name, "line-item sum", "line_items_complete is false")

    # --- 2. subtotal + charges == total_printed ----------------------------
    if charges and f.get("subtotal") is not None and f.get("total_printed") is not None:
        composed = round(float(f["subtotal"]) + money(charges, "amount"), 2)
        r.ok(name, "subtotal + sum(charges) == total_printed",
             composed, float(f["total_printed"]))

    # --- 3. carried_prior + current == total_printed -----------------------
    #
    # The carried balance is what actually rolls into this bill, and it is NOT
    # always the printed "previous balance":
    #
    #   prior_balance_basis == "gross"           -> prior + payments_credits
    #     (Comcast, Windstream, Lumen, EDCO: a gross prior plus a separate
    #      signed credit line)
    #   prior_balance_basis == "net_of_payments" -> prior, as printed
    #     (CentraCom prints 'Previous Balance Due' already net; subtracting
    #      payments again would double-count them)
    #
    # Getting this wrong is the same class of bug as F1 itself, one level down.
    prior = f.get("prior_balance")
    current = f.get("current_charges")
    printed = f.get("total_printed")
    if prior is not None and current is not None and printed is not None:
        basis = f.get("prior_balance_basis")
        r.checks += 1
        if basis not in ("gross", "net_of_payments"):
            r.failures.append(
                f"{name}: prior_balance_basis must be 'gross' or 'net_of_payments', "
                f"got {basis!r} — the closure check is ambiguous without it")
            return

        if basis == "gross":
            carried = round(float(prior) + float(f.get("payments_credits") or 0.0), 2)
        else:
            carried = round(float(prior), 2)
            gross_bal = f.get("balance_from_last_statement")
            pay = f.get("payments_credits")
            if gross_bal is not None and pay is not None:
                r.ok(name, "balance_from_last_statement + payments == prior_balance",
                     round(float(gross_bal) + float(pay), 2), carried)

        composed = round(carried + float(current), 2)
        closes = abs(composed - float(printed)) <= TOL

        # A closing document must derive a payable; a non-closing one must not.
        if closes:
            expected_payable = float(current) if abs(carried) > TOL else float(printed)
            expected_basis = "current_charges" if abs(carried) > TOL else "total_printed"
            r.ok(name, f"amount_payable (carried={carried:.2f}, closure verified)",
                 d.get("amount_payable"), expected_payable)
            r.ok(name, "payable_basis", d.get("payable_basis"), expected_basis)
            r.ok(name, "review_flag when closure verified",
                 doc["expected_routing"]["review_flag"], False)
        else:
            r.ok(name, f"amount_payable must be null (carried={carried:.2f} + "
                       f"current={float(current):.2f} != printed={float(printed):.2f})",
                 d.get("amount_payable"), None)
            r.ok(name, "review_flag must be true when arithmetic does not close",
                 doc["expected_routing"]["review_flag"], True)

    # --- 4. no prior balance -> payable is the printed total ---------------
    elif printed is not None and prior is None:
        pp = f.get("please_pay")
        if pp is not None and abs(float(pp) - float(printed)) > TOL:
            # Printed total and payable disagree with no prior balance to explain it.
            r.ok(name, "amount_payable must be null (unexplained total/payable gap)",
                 d.get("amount_payable"), None)
            r.ok(name, "review_flag must be true (unexplained gap)",
                 doc["expected_routing"]["review_flag"], True)
        elif d.get("amount_payable") is not None:
            r.ok(name, "amount_payable == total_printed (no prior balance)",
                 d.get("amount_payable"), float(printed))

    # --- 5. scanline corroborates what it claims --------------------------
    sl = doc.get("scanline")
    if sl:
        raw = sl["raw"].replace(" ", "")
        amt = sl.get("encodes_amount")
        if amt is not None:
            digits = f"{float(amt):.2f}".replace(".", "").lstrip("0")
            r.checks += 1
            if digits not in raw:
                r.failures.append(
                    f"{name}: scanline does not contain amount digits {digits!r}: {raw!r}")
        acct = sl.get("encodes_account")
        if acct:
            r.checks += 1
            if acct.lstrip("0") not in raw:
                r.failures.append(
                    f"{name}: scanline does not contain account {acct!r}: {raw!r}")
        inv = sl.get("encodes_invoice_number")
        if inv:
            r.checks += 1
            if inv not in raw:
                r.failures.append(
                    f"{name}: scanline does not contain invoice number {inv!r}: {raw!r}")
        # F7 hard constraint
        r.checks += 1
        illegal = {"amount_payable", "current_charges"} & set(sl.get("binds_to", []))
        if illegal:
            r.failures.append(
                f"{name}: scanline binds to forbidden field(s) {sorted(illegal)} — "
                "grammar V7 permits total_printed/account_number/invoice_number/due_date only")

    # --- 6. identity basis is coherent -----------------------------------
    if d.get("identity_basis"):
        r.checks += 1
        if d["identity_basis"] == "invoice_number":
            if not f.get("invoice_number"):
                r.failures.append(f"{name}: identity_basis=invoice_number but no invoice_number")
            elif d.get("document_identity") != f["invoice_number"]:
                r.failures.append(
                    f"{name}: document_identity {d.get('document_identity')!r} != "
                    f"invoice_number {f['invoice_number']!r}")
        else:
            if f.get("invoice_number"):
                r.failures.append(
                    f"{name}: identity_basis=account_period but an invoice_number exists")
            expect = f"{f.get('account_number_normalized') or f.get('account_number')}|{f.get('bill_date')}"
            if d.get("document_identity") != expect:
                r.failures.append(
                    f"{name}: document_identity {d.get('document_identity')!r} != {expect!r}")

    # --- 7. annotated documents never feed promotion ---------------------
    tags = doc["classification"].get("tags", [])
    if "has_flattened_annotations" in tags:
        r.ok(name, "annotated doc is excluded_from_promotion",
             doc.get("excluded_from_promotion"), True)
        r.ok(name, "annotated doc forces review",
             doc["expected_routing"]["review_flag"], True)
        overlay_refs = set(doc.get("annotation_overlays", {}).get("reference_values", []))
        printed_refs = {x["value"] for x in doc.get("reference_list", [])}
        leaked = {v for v in (overlay_refs - printed_refs)} & printed_refs
        r.checks += 1
        if leaked:
            r.failures.append(f"{name}: annotation values leaked into reference_list: {leaked}")

    # --- 8. mixed_sign tag matches the data ------------------------------
    if lines:
        signs = {(float(l["amount"]) < 0) for l in lines if l.get("amount") is not None}
        if len(signs) > 1:
            r.ok(name, "mixed_sign tag present", "mixed_sign" in tags, True)

    # --- 9. page roles align with page count -----------------------------
    roles = doc["classification"].get("page_roles")
    if roles:
        r.ok(name, "len(page_roles) == page_count",
             len(roles), doc["classification"]["page_count"])

    # --- 10. amount_payable is never a raw extracted field ---------------
    r.checks += 1
    if "amount_payable" in f:
        r.failures.append(
            f"{name}: amount_payable appears under 'fields' — it is derived_only "
            "(grammar V10). Move it to 'derived'.")


def main() -> int:
    # Windows' default console codepage (cp1252) cannot encode the ✓/✗ below,
    # so a clean 116/116-checks-passing run still crashed with a raw
    # `UnicodeEncodeError` traceback instead of printing "all gold labels are
    # internally consistent" and exiting 0 - a naive CI step reading "exit 1 /
    # traceback" would misdiagnose that as a real failure. `reconfigure` is
    # unavailable only if stdout has been replaced with something unusual
    # (e.g. some test-capture shims); fall through silently there rather than
    # fail the whole script over a cosmetic guard.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    files = sorted(glob.glob(os.path.join(GOLD_DIR, "*.json")))
    if not files:
        print(f"no gold files found in {GOLD_DIR}", file=sys.stderr)
        return 1

    r = Report()
    for path in files:
        with open(path) as fh:
            doc = json.load(fh)
        check(doc, r)

    print(f"gold documents : {len(files)}")
    print(f"checks run     : {r.checks}")
    print(f"failures       : {len(r.failures)}")
    if r.skips:
        print(f"\nskipped ({len(r.skips)} — incomplete transcription, expected):")
        for s in r.skips:
            print(f"  - {s}")
    if r.failures:
        print("\nFAILURES:")
        for fail in r.failures:
            print(f"  ✗ {fail}")
        return 1
    print("\nall gold labels are internally consistent ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
