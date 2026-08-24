"""EDCO has no `payments_credits` selector, so `derive_amount_payable` can
never net a same-cycle payment against the carried balance and refuses with
a false `arith_balance_mismatch` on every EDCO account where one intervened
(measured: 11/28 real second-sample documents, including gold doc
`northstar-edco-819387`, whose gold label already records the expected
`payments_credits: -3380.67`).

Real account 174921AUG25: `BALANCE FORWARD 160.41`, `PAYMENT -- THANK YOU
357.24`, `CURRENT CHARGES: 357.24`, printed total `160.41`. Netting:
160.41 - 357.24 + 357.24 == 160.41.
"""

from __future__ import annotations

from decimal import Decimal

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs
from northstar import PACK as _NORTHSTAR_PACK
from docintel.pipeline.stages.s6_capture import CaptureFields

WIDTH = 612.0
HEIGHT = 792.0


def _edco_selectors(*fields: str) -> list[dict]:
    for pack in load_packs() + [_NORTHSTAR_PACK]:
        if pack.name != "northstar":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint") == "northstar|edco":
                by_field = {s.get("field"): s for s in persona["field_selectors"]}
                return [by_field[f] for f in fields if f in by_field]
    raise AssertionError("northstar|edco persona not found")


def _row(y: float, *cells: tuple[str, float]) -> list[Word]:
    return [
        Word(text=text, x0=x0, y0=y, x1=x0 + 7.0 * len(text), y1=y + 10.0)
        for text, x0 in cells
    ]


def _page(total_printed: str, prior_balance: str, payment: str, current_charges: str) -> PageText:
    words: list[Word] = []
    words += _row(100.0, (total_printed, 380.0))
    words += _row(519.0, ("BALANCE", 77.0), ("FORWARD", 126.0), (prior_balance, 540.0))
    words += _row(
        560.0,
        ("PAYMENT", 77.0), ("--", 140.0), ("THANK", 160.0), ("YOU", 210.0), (payment, 540.0),
    )
    words += _row(603.0, ("CURRENT", 77.0), ("CHARGES:", 129.0), (current_charges, 377.0))
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def _ctx(page: PageText) -> JobContext:
    meta = (
        PageMeta(page_number=1, char_count=sum(len(w.text) for w in page.words),
                 image_count=0, annot_count=0, role="primary"),
    )
    return JobContext(document_id="d1", source_path="x.pdf", pages=(page,), page_meta=meta,
                       doc_type="standard_invoice")


def test_edco_persona_has_a_payments_credits_selector() -> None:
    """The gap: before this fix, `_edco_selectors('payments_credits')` returns []."""
    selectors = _edco_selectors("payments_credits")
    assert len(selectors) == 1
    assert selectors[0]["pattern"] == "currency"
    assert "normalize_credit_sign" in selectors[0].get("adjust", [])


def test_edco_payment_is_extracted_and_sign_normalized() -> None:
    """Real account 174921AUG25 shape: a same-cycle payment that must come out
    negative (`normalize_credit_sign`) so `resolve_carried_balance`'s `gross`
    formula (`prior_balance + payments_credits`) nets it rather than doubling it."""
    persona = parse_persona({
        "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
        "rule_version": "v1", "status": "draft",
        "field_selectors": _edco_selectors(
            "total_printed", "prior_balance", "payments_credits", "current_charges"
        ),
        "layout_fingerprint": {},
    })
    page = _page(total_printed="160.41", prior_balance="160.41",
                 payment="357.24", current_charges="357.24")
    ctx = Executor(persona).apply(_ctx(page))
    ctx.persona = persona
    ctx = CaptureFields().run(ctx)
    assert ctx.extracted.get("payments_credits") == Decimal("-357.24")
