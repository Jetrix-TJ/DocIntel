"""Finding 5 re-measurement: Edco account `15570`'s `total_printed` does not
equal `prior_balance + current_charges` on its two real invoices
(`15570AUG25`, `15570SEPT25`), unlike two other real Edco accounts
(`13307OCT25`, `159507OCT25`) where the naive sum reconciles exactly.

Reading the actual PDF text (via `docintel.extract.pdf.read_pages`) for all
four files found the real cause, and it is NOT a mis-anchored/stray-value
selector:

    13307OCT25:  prior_balance 1146.58 + current_charges 1618.27 = 2764.85 = total_printed  (reconciles)
    159507OCT25: prior_balance  411.13 + current_charges  580.42 =  991.55 = total_printed  (reconciles)
    15570AUG25:  prior_balance  607.21 + current_charges  894.98 = 1502.19 != total_printed (510.28)
    15570SEPT25: prior_balance  510.28 + current_charges 1405.43 = 1915.71 != total_printed (1020.73)

The `15570` account's two statements each print a `PAYMENT -- THANK YOU` line
between the balance-forward and current-charges lines (`991.91` on the AUG25
statement, `894.98` on the SEPT25 one - each equal to the *previous* month's
`current_charges`, i.e. the customer paid the prior invoice in full before
the next one was cut). Netting that payment out reconciles perfectly:

    15570AUG25:  607.21 - 991.91 +  894.98 =  510.28 == total_printed
    15570SEPT25: 510.28 - 894.98 + 1405.43 = 1020.73 == total_printed

`total_printed`'s selector (`header-block` region, `currency` pattern) is
reading the correct, literally-printed "amount due" figure in both cases -
the same figure that also appears again on the remittance stub and next to
`CURRENT CHARGES:` further down the page. There is no stray value from
elsewhere on the page; the two accounts that "compute correctly" simply had
no intervening payment, so the naive `prior_balance + current_charges`
formula happened to equal the printed total for them by coincidence of
having a zero payment, not because Edco's layout guarantees that identity.

This is the same shape as the persona's own documented "F1 TRAP" (see the
`notes` field in `edco.json`: printed total 367.96, true payable 69.62) and
is exactly the gap Task 11 ("The payable amount (A3) - GATE") in
`docs/superpowers/plans/2026-07-29-weakness-remediation.md` calls out and
gates behind a business decision: computing a true netted `amount_payable`
is decision-gated arithmetic-derivation machinery, not an Edco-specific
selector fix. This test locks in the current, correct, printed-fields-only
behavior so a future "fix" doesn't silently start computing `total_printed`
from `prior_balance + current_charges` (which would be wrong exactly when a
payment intervenes, i.e. exactly the case this test exists for).
"""

from __future__ import annotations

from decimal import Decimal

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs

WIDTH = 612.0
HEIGHT = 792.0


def _edco_selectors(*fields: str) -> list[dict]:
    """The actual selectors out of the shipped `northstar|edco` persona for
    the given fields, in shipped order - read from the loaded pack rather than
    re-typed, so this test exercises the real rule, not a copy of it."""
    for pack in load_packs():
        if pack.name != "northstar":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint") == "northstar|edco":
                by_field = {s.get("field"): s for s in persona["field_selectors"]}
                return [by_field[f] for f in fields if f in by_field]
    raise AssertionError("northstar|edco persona not found")


def _row(y: float, *cells: tuple[str, float]) -> list[Word]:
    """One text row at height `y`: each cell is (text, x0)."""
    return [
        Word(text=text, x0=x0, y0=y, x1=x0 + 7.0 * len(text), y1=y + 10.0)
        for text, x0 in cells
    ]


def _page(total_printed: str, prior_balance: str, current_charges: str) -> PageText:
    """A minimal page shaped like the real Edco invoices: the header-block
    total near the top of the page (y0=100, well inside the top-25% band),
    then a `BALANCE FORWARD` row and a `CURRENT CHARGES:` row further down -
    matching the real documents' relative geometry."""
    words: list[Word] = []
    words += _row(100.0, (total_printed, 380.0))
    words += _row(
        519.0,
        ("BALANCE", 77.0), ("FORWARD", 126.0), (prior_balance, 540.0),
    )
    words += _row(
        603.0,
        ("CURRENT", 77.0), ("CHARGES:", 129.0), (current_charges, 377.0),
    )
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def _ctx(page: PageText) -> JobContext:
    meta = (
        PageMeta(
            page_number=1,
            char_count=sum(len(w.text) for w in page.words),
            image_count=0,
            annot_count=0,
            role="primary",
        ),
    )
    return JobContext(
        document_id="d1", source_path="x.pdf", pages=(page,), page_meta=meta,
        doc_type="standard_invoice",
    )


def _extract(total_printed: str, prior_balance: str, current_charges: str) -> dict[str, object]:
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": _edco_selectors("total_printed", "prior_balance", "current_charges"),
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(_page(total_printed, prior_balance, current_charges)))
    return {
        "total_printed": ctx.extracted.get("total_printed"),
        "prior_balance": ctx.extracted.get("prior_balance"),
        "current_charges": ctx.extracted.get("current_charges"),
    }


def test_reconciling_account_13307oct25_matches_naive_sum() -> None:
    """No intervening payment on this real account -> the naive
    `prior_balance + current_charges` formula happens to equal the printed
    total, and the selector reads all three correctly."""
    got = _extract(total_printed="2764.85", prior_balance="1146.58", current_charges="1618.27")
    assert got == {
        "total_printed": Decimal("2764.85"), "prior_balance": Decimal("1146.58"),
        "current_charges": Decimal("1618.27"),
    }
    assert got["prior_balance"] + got["current_charges"] == got["total_printed"]


def test_reconciling_account_159507oct25_matches_naive_sum() -> None:
    """Second real no-payment account: same reconciliation, different
    numbers - confirms the first case wasn't a coincidence of one sample."""
    got = _extract(total_printed="991.55", prior_balance="411.13", current_charges="580.42")
    assert got == {
        "total_printed": Decimal("991.55"), "prior_balance": Decimal("411.13"),
        "current_charges": Decimal("580.42"),
    }
    assert got["prior_balance"] + got["current_charges"] == got["total_printed"]


def test_account_15570aug25_total_printed_is_the_real_printed_value_not_the_naive_sum() -> None:
    """The finding: this real account's printed total (510.28) is correctly
    extracted by the shipped `header-block` selector, but does NOT equal
    `prior_balance + current_charges` (1502.19) because a 991.91 payment
    (`PAYMENT -- THANK YOU`, printed between the balance-forward and
    current-charges lines) intervened. Netting the payment out of the naive
    sum reconciles it exactly - proof the printed total is correct and there
    is no stray/mis-anchored value, only an un-derived payment."""
    got = _extract(total_printed="510.28", prior_balance="607.21", current_charges="894.98")
    assert got == {
        "total_printed": Decimal("510.28"), "prior_balance": Decimal("607.21"),
        "current_charges": Decimal("894.98"),
    }
    prior_balance = got["prior_balance"]
    current_charges = got["current_charges"]
    total_printed = got["total_printed"]
    payment = Decimal("991.91")  # read off the real PDF's "PAYMENT -- THANK YOU" line
    assert prior_balance + current_charges != total_printed
    assert prior_balance - payment + current_charges == total_printed


def test_account_15570sept25_total_printed_is_the_real_printed_value_not_the_naive_sum() -> None:
    """Same shape one billing cycle later: prior_balance (510.28) is exactly
    the previous month's total_printed carried forward, a new 894.98 payment
    intervenes, and the printed total (1020.73) again nets out correctly -
    confirming this is how account 15570 behaves every month, not a one-off
    misread."""
    got = _extract(total_printed="1020.73", prior_balance="510.28", current_charges="1405.43")
    assert got == {
        "total_printed": Decimal("1020.73"), "prior_balance": Decimal("510.28"),
        "current_charges": Decimal("1405.43"),
    }
    prior_balance = got["prior_balance"]
    current_charges = got["current_charges"]
    total_printed = got["total_printed"]
    payment = Decimal("894.98")  # read off the real PDF's "PAYMENT -- THANK YOU" line
    assert prior_balance + current_charges != total_printed
    assert prior_balance - payment + current_charges == total_printed
