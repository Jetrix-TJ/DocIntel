"""Stage 6: the op chain and confidence pricing.

The ordering assertions here are the ones that matter. A persona author can list
`adjust` ops in any order, and Stage 6 must not let that order break the F1
derivation — so the chain is run in `ops.ORDER`, not as written.
"""

from __future__ import annotations

from decimal import Decimal

from docintel.core.models import PageMeta, PageText, Word, new_context
from docintel.grammar.schema import parse_persona
from docintel.pipeline.stages.s6_capture import CaptureFields


def _page(number: int, *texts: str) -> PageText:
    words = tuple(
        Word(text=t, x0=10.0 + 70.0 * i, y0=100.0, x1=60.0 + 70.0 * i, y1=110.0)
        for i, t in enumerate(texts)
    )
    return PageText(page_number=number, words=words, width=612.0, height=792.0, source="native")


def _persona(*selectors, status="active"):
    return parse_persona({
        "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
        "rule_version": "v1", "status": status,
        "field_selectors": list(selectors), "layout_fingerprint": {},
    })


def _ctx(persona=None, **fields):
    ctx = new_context("d", "/docs/inv-6060-699.00.pdf")
    ctx.doc_type = "standard_invoice"
    ctx.pages = (_page(1, "Invoice"),)
    ctx.page_meta = (PageMeta(1, 100, 0, 0, "primary"),)
    ctx.persona = persona
    for name, value in fields.items():
        ctx.extracted.set(name, value, 1.0)
    return ctx


# --------------------------------------------------------------------------
# Value ops
# --------------------------------------------------------------------------


def test_a_value_op_transforms_only_its_own_selectors_field() -> None:
    persona = _persona(
        {"field": "account_number", "region": "header-block", "pattern": "text",
         "adjust": ["strip_internal_whitespace"]},
        {"field": "vendor_name", "region": "header-block", "pattern": "text"},
    )
    ctx = _ctx(persona, account_number="8495 44 462 0365242", vendor_name="EDCO  Waste")
    ctx = CaptureFields().run(ctx)
    assert ctx.extracted.get("account_number") == "8495444620365242"
    assert ctx.extracted.get("vendor_name") == "EDCO  Waste", "untouched selector"


def test_value_ops_run_in_declaration_order() -> None:
    """Section 4: "Ops run at Stage 6 in declaration order." For value ops that
    order is the persona's, because the composition is the author's intent."""
    persona = _persona(
        {"field": "vendor_name", "region": "header-block", "pattern": "text",
         "adjust": ["collapse_internal_spaces", "uppercase"]},
    )
    ctx = _ctx(persona, vendor_name="  edco   waste  ")
    ctx = CaptureFields().run(ctx)
    assert ctx.extracted.get("vendor_name") == "EDCO WASTE"


def test_a_value_op_preserves_match_quality() -> None:
    persona = _persona(
        {"field": "vendor_name", "region": "header-block", "pattern": "text",
         "adjust": ["uppercase"]},
    )
    ctx = _ctx(persona)
    ctx.extracted.set("vendor_name", "edco", 0.90)
    ctx = CaptureFields().run(ctx)
    assert ctx.extracted.match_quality["vendor_name"] == 0.90


def test_a_missing_field_is_not_invented_by_its_ops() -> None:
    persona = _persona(
        {"field": "vendor_name", "region": "header-block", "pattern": "text",
         "adjust": ["uppercase"]},
    )
    ctx = _ctx(persona)
    ctx = CaptureFields().run(ctx)
    assert "vendor_name" not in ctx.extracted.values


# --------------------------------------------------------------------------
# Document ops and their order
# --------------------------------------------------------------------------


def test_the_f1_chain_runs_in_dependency_order_not_declaration_order() -> None:
    """THE ordering test. The persona below lists the ops backwards on purpose:
    if Stage 6 honoured that order, derive_amount_payable would read a
    carried_balance that did not exist yet and fall back to the printed total —
    the F1 bug, reachable purely by how a persona was written."""
    persona = _persona(
        {"field": "current_charges", "anchor": "Current Charges", "region": "line_items",
         "pattern": "currency",
         "adjust": ["derive_amount_payable", "resolve_carried_balance",
                    "normalize_credit_sign"]},
    )
    ctx = _ctx(
        persona,
        prior_balance=Decimal("20123.80"),
        prior_balance_basis="net_of_payments",
        payments_credits=Decimal("-24120.20"),
        current_charges=Decimal("13752.60"),
        total_printed=Decimal("33876.40"),
    )
    ctx = CaptureFields().run(ctx)
    assert ctx.derived.get("carried_balance") == Decimal("20123.80")
    assert ctx.derived.get("amount_payable") == Decimal("13752.60")
    assert ctx.derived.get("payable_basis") == "current_charges"


def test_a_document_op_declared_on_two_selectors_runs_once() -> None:
    persona = _persona(
        {"field": "total_printed", "anchor": "Total", "region": "totals-block",
         "pattern": "currency", "adjust": ["crosscheck_filename"]},
        {"field": "invoice_number", "anchor": "Invoice", "region": "header-block",
         "pattern": "integer", "adjust": ["crosscheck_filename"]},
    )
    ctx = _ctx(persona, total_printed=Decimal("699.00"), invoice_number=6060)
    ctx = CaptureFields().run(ctx)
    # One boost, not two: the op is document-scoped and ran a single time.
    assert ctx.boosts.get("invoice_number") == 1


def test_no_persona_means_no_ops_and_no_crash() -> None:
    """Every document is in this state until C5 authors personas."""
    ctx = _ctx(None, total_printed=Decimal("699.00"))
    ctx = CaptureFields().run(ctx)
    assert ctx.derived.get("amount_payable") is None


# --------------------------------------------------------------------------
# document_identity always runs
# --------------------------------------------------------------------------


def test_the_identity_is_derived_even_with_no_persona() -> None:
    """It is not an adjust op, so a persona cannot opt out — and validate_record
    requires it on every processed record."""
    ctx = _ctx(None, invoice_number="6060")
    ctx = CaptureFields().run(ctx)
    assert ctx.derived.get("document_identity") == "6060"
    assert ctx.derived.get("identity_basis") == "invoice_number"


def test_the_identity_records_that_it_looked_when_it_cannot_build_one() -> None:
    ctx = _ctx(None)
    ctx = CaptureFields().run(ctx)
    assert "document_identity" in ctx.derived.values
    assert ctx.derived.get("document_identity") is None


# --------------------------------------------------------------------------
# Confidence
# --------------------------------------------------------------------------


def test_ocr_lowers_every_fields_confidence() -> None:
    ctx = _ctx(None, total_printed=Decimal("481.20"))
    ctx.text_source = "ocr"
    ctx = CaptureFields().run(ctx)
    assert "ocr_source" in ctx.modifiers
    assert ctx.confidence["total_printed"] == 0.9


def test_a_draft_persona_lowers_confidence() -> None:
    ctx = _ctx(_persona(status="draft"), total_printed=Decimal("699.00"))
    ctx = CaptureFields().run(ctx)
    assert "draft_rules" in ctx.modifiers
    assert ctx.confidence["total_printed"] == 0.85


def test_a_soft_miss_lowers_confidence() -> None:
    ctx = _ctx(_persona(), total_printed=Decimal("699.00"))
    ctx.persona_status = "soft_miss"
    ctx = CaptureFields().run(ctx)
    assert "soft_miss" in ctx.modifiers
    assert ctx.confidence["total_printed"] == 0.8


def test_flattened_annotations_applies_its_penalty() -> None:
    """F3. Section 5 also says this modifier forces review unconditionally;
    making the gate act on it is C4's task, since s7 does not read tags yet."""
    ctx = _ctx(None, total_printed=Decimal("481.20"))
    ctx.add_tag("has_flattened_annotations")
    ctx = CaptureFields().run(ctx)
    assert "flattened_annotations" in ctx.modifiers
    assert ctx.confidence["total_printed"] == 0.75


def test_modifiers_are_multiplicative() -> None:
    ctx = _ctx(_persona(status="draft"), total_printed=Decimal("481.20"))
    ctx.text_source = "ocr"
    ctx = CaptureFields().run(ctx)
    # 1.0 * 0.90 (ocr) * 0.85 (draft)
    assert ctx.confidence["total_printed"] == 0.765


def test_confidence_never_reaches_certainty() -> None:
    """A global invariant, not a boost-only rule: this pipeline never reports
    certainty about a value read off a document."""
    persona = _persona(
        {"field": "invoice_number", "anchor": "Invoice", "region": "header-block",
         "pattern": "integer", "adjust": ["crosscheck_filename"]},
    )
    ctx = _ctx(persona, invoice_number=6060)
    ctx = CaptureFields().run(ctx)
    assert ctx.confidence["invoice_number"] <= 0.99


def test_a_boost_cannot_undo_an_ocr_penalty() -> None:
    """Boosts apply AFTER modifiers and are capped, so corroboration cannot lift
    an OCR'd field back to the confidence of a native-text one. Three agreeing
    renderings of an OCR'd number can still all be wrong the same way."""
    persona = _persona(
        {"field": "invoice_number", "anchor": "Invoice", "region": "header-block",
         "pattern": "integer", "adjust": ["crosscheck_filename"]},
    )
    ctx = _ctx(persona, invoice_number=6060)
    ctx.text_source = "ocr"
    ctx = CaptureFields().run(ctx)
    assert ctx.confidence["invoice_number"] < 0.99
    assert ctx.confidence["invoice_number"] > 0.9, "the boost did apply"


def test_the_payable_inherits_the_confidence_of_its_basis() -> None:
    """The number that matters most is derived, so it has no match_quality of its
    own. `payable_basis` records exactly which field it came from."""
    persona = _persona(
        {"field": "current_charges", "anchor": "Current Charges", "region": "line_items",
         "pattern": "currency",
         "adjust": ["resolve_carried_balance", "derive_amount_payable"]},
    )
    ctx = _ctx(
        persona,
        prior_balance=Decimal("298.34"),
        prior_balance_basis="gross",
        total_printed=Decimal("367.96"),
    )
    ctx.extracted.set("current_charges", Decimal("69.62"), 0.90)
    ctx = CaptureFields().run(ctx)
    assert ctx.derived.get("payable_basis") == "current_charges"
    assert ctx.confidence["amount_payable"] == ctx.confidence["current_charges"]


def test_a_refused_payable_gets_no_confidence_entry() -> None:
    """U-PAK. There is no number to be confident about."""
    persona = _persona(
        {"field": "total_printed", "anchor": "Total", "region": "totals-block",
         "pattern": "currency", "adjust": ["derive_amount_payable"]},
    )
    ctx = _ctx(
        persona,
        total_printed=Decimal("14789.77"),
        please_pay=Decimal("14740.85"),
    )
    ctx = CaptureFields().run(ctx)
    assert ctx.derived.get("amount_payable") is None
    assert "amount_payable" not in ctx.confidence
    assert ctx.review_flag is True


# --------------------------------------------------------------------------
# A modifier scoped to a field that produced nothing
# --------------------------------------------------------------------------


def test_a_modifier_on_a_field_that_produced_nothing_still_penalises_the_document() -> None:
    """A field-scoped modifier had nothing to multiply, so it multiplied nothing.

    `add_field_modifier` appends to BOTH `field_modifiers` and `modifiers`, and
    `_score` treats every name that appears in `field_modifiers` as claimed by that
    field - so it is excluded from `document_wide`. When the field also has no
    `match_quality` row, which is exactly the case for `pattern_timeout` (the
    executor discards its partial values and returns), the modifier applied to
    nothing at all: it appeared on the record and changed no number.

    A blown pattern budget is evidence about the DOCUMENT - the page is pathological
    enough to exhaust a 50ms budget - so with no field left to carry it, it belongs
    to the document.
    """
    ctx = _ctx(_persona(
        {"field": "total_printed", "anchor": "Total", "region": "near-anchor",
         "pattern": "currency"},
    ), total_printed=Decimal("100.00"))
    # The timed-out field never reached `extracted.set`, so it has no match_quality.
    ctx.add_field_modifier("invoice_number", "pattern_timeout")

    CaptureFields().run(ctx)

    assert ctx.confidence["total_printed"] == 0.50, (
        "pattern_timeout was recorded on the record but penalised no field"
    )


def test_a_modifier_scoped_to_a_field_that_DID_produce_stays_scoped() -> None:
    """The distinction the orphan rule must not break: a modifier belonging to one
    field that has a value still applies to that field alone."""
    ctx = _ctx(_persona(
        {"field": "total_printed", "anchor": "Total", "region": "near-anchor",
         "pattern": "currency"},
    ), total_printed=Decimal("100.00"), invoice_number="A-1")
    ctx.add_field_modifier("invoice_number", "pattern_timeout")

    CaptureFields().run(ctx)

    assert ctx.confidence["invoice_number"] == 0.50
    assert ctx.confidence["total_printed"] == 0.99, (
        "a field-scoped modifier leaked onto a field it does not belong to"
    )


def test_apply_prior_balance_basis_fires_for_centracom_and_edco() -> None:
    """Task 11 prerequisite: resolve_carried_balance needs this hook's output.

    Registering the hook alone must not change any scored assertion - nothing
    yet reads `prior_balance_basis` except this hook itself - so this test
    checks the hook's own effect directly rather than through the scorecard.
    """
    import json
    import os

    from digitaldirection import PACK as DIGITALDIRECTION_PACK
    from northstar import PACK as NORTHSTAR_PACK

    from docintel.adapters.vision.fake import FakeVision
    from docintel.pipeline.stages import build_pipeline

    def _run(gold_id: str) -> dict:
        with open(os.path.join("docs", "corpus", "gold", f"{gold_id}.json")) as fh:
            gold = json.load(fh)
        runner = build_pipeline(FakeVision(), extra_packs=[NORTHSTAR_PACK, DIGITALDIRECTION_PACK])
        return runner.process(
            document_id=gold["gold_id"],
            source_path=os.path.join("docs", gold["source_file"]),
        )

    centracom = _run("digitaldirection-centracom-0384043574")
    assert centracom["fields"]["prior_balance_basis"] == "net_of_payments"

    edco = _run("northstar-edco-077087")
    assert edco["fields"]["prior_balance_basis"] == "gross"
