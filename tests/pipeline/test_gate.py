"""Stage 7: the confidence gate. Three exits, but every document leaves.

The plan's block comes first, verbatim. After it, the cases the corpus actually
requires — which turned out to need a fourth lane and a second dimension the
plan's tests do not reach.
"""

from __future__ import annotations

import random

import pytest

from docintel.core.coverage import Coverage
from docintel.core.models import new_context
from docintel.pipeline.stages.s7_gate import (
    DEFAULT_FORCED_REVIEW_TAGS,
    FORCING_MODIFIERS,
    VERY_LOW_FLOOR,
    ConfidenceGate,
)


def _gate(**kw):
    kw.setdefault("rng", random.Random(0))
    return ConfidenceGate(**kw)


# ==========================================================================
# The plan's block, verbatim
# ==========================================================================


def test_all_fields_clear_thresholds_goes_high():
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"total_printed": 0.98, "invoice_number": 0.95}
    out = _gate(thresholds={"total_printed": 0.95, "invoice_number": 0.92}).run(ctx)
    assert out.lane == "high"
    assert out.review_flag is False


def test_one_weak_field_goes_medium_with_review():
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"vendor_name": 0.97, "total_printed": 0.55}
    out = _gate(thresholds={"total_printed": 0.95, "vendor_name": 0.90}).run(ctx)
    assert out.lane == "medium"
    assert out.review_flag is True
    assert out.regen_flag is False


def test_most_fields_weak_goes_low_with_regen_not_just_review():
    """Systemic failure means 'fix the rules', not 'a human reads this one'."""
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"a": 0.2, "b": 0.3, "c": 0.25, "d": 0.9}
    out = _gate(thresholds={}).run(ctx)
    assert out.lane == "low"
    assert out.regen_flag is True


def test_flattened_annotations_force_review_regardless_of_confidence():
    """F3: Federal Recycling. Never fast-lane an annotated document."""
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"total_printed": 0.99}
    ctx.add_tag("has_flattened_annotations")
    out = _gate(thresholds={}, forced_review_tags={"has_flattened_annotations"}).run(ctx)
    assert out.review_flag is True
    assert out.lane != "high"


def test_audit_sampling_is_deterministic_under_a_seeded_rng():
    lanes = []
    for seed in range(20):
        ctx = new_context("d", "/x.pdf")
        ctx.confidence = {"total_printed": 0.99}
        out = ConfidenceGate(thresholds={}, audit_rate=0.5,
                             rng=random.Random(seed)).run(ctx)
        lanes.append(out.audit_sample)
    assert any(lanes) and not all(lanes)


def test_audit_sample_stays_in_the_high_lane_but_is_flagged():
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"total_printed": 0.99}
    out = ConfidenceGate(thresholds={}, audit_rate=1.0, rng=random.Random(1)).run(ctx)
    assert out.lane == "high"
    assert out.audit_sample is True
    assert out.review_flag is True


def test_no_confidence_at_all_is_low_not_high():
    """An empty confidence dict must never be read as 'nothing fell short'."""
    out = _gate(thresholds={}).run(new_context("d", "/x.pdf"))
    assert out.lane == "low"
    assert out.review_flag is True


# ==========================================================================
# The fourth lane: `review`
# ==========================================================================


def test_the_review_lane_exists_because_gold_requires_it():
    """The spec's Stage 7 table lists three lanes (High, Medium/Low, Very Low).
    Two gold files expect a fourth, `review`, and gold is the objective function.

    It is a real distinction, not a synonym for `medium`: Federal Recycling's
    fields may extract perfectly, and the reason a human must look is that the
    page carries values invisible to the text layer (F3) — not low confidence.
    """
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"total_printed": 0.99}
    ctx.add_tag("has_flattened_annotations")
    out = _gate(thresholds={}).run(ctx)
    assert out.lane == "review"


def test_flattened_annotations_are_forced_by_default_not_by_configuration():
    """Section 5 says this modifier forces review *unconditionally*, so it is a
    spec-mandated default rather than something a pack opts into."""
    assert "has_flattened_annotations" in DEFAULT_FORCED_REVIEW_TAGS


def test_xlsx_hidden_content_is_forced_by_default_not_by_configuration():
    """`extract.xlsx_hidden.has_hidden_content` detects, never extracts - a
    hidden sheet/row/column's content is structurally invisible to any
    render, so it forces review the same unconditional way
    `has_flattened_annotations` does, not something a pack opts into."""
    assert "xlsx_hidden_content_present" in DEFAULT_FORCED_REVIEW_TAGS
    ctx = new_context("d", "/x.xlsx")
    ctx.confidence = {"total_printed": 0.99}
    ctx.add_tag("xlsx_hidden_content_present")
    out = _gate(thresholds={}).run(ctx)
    assert out.lane == "review"
    assert out.review_flag is True


def test_the_forcing_modifier_alone_also_forces_review():
    """Section 5 attaches the forcing to the MODIFIER, so a document carrying it
    without the tag must still be forced."""
    assert "flattened_annotations" in FORCING_MODIFIERS
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"total_printed": 0.99}
    ctx.add_modifier("flattened_annotations")
    out = _gate(thresholds={}).run(ctx)
    assert out.lane == "review"
    assert out.review_flag is True


def test_arith_balance_mismatch_forces_the_review_lane():
    """U-PAK. Section 5: this modifier "also raises review". It is what
    `derive_amount_payable` applies when it refuses to guess the payable (F8)."""
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"total_printed": 0.99}
    ctx.add_modifier("arith_balance_mismatch")
    out = _gate(thresholds={}).run(ctx)
    assert out.lane == "review"


def test_a_bare_upstream_review_flag_does_NOT_force_the_review_lane():
    """The bug this caught, and why forcing reads modifiers rather than a boolean.

    `s5c_agent` sets `review_flag` for every first-time sender, correctly: spec
    Part 3 says a hard miss "emits anyway with the one-shot result and a review
    flag". Treating that as forcing routed ALL TEN corpus documents to `review`,
    including DTSS with no tags and no modifiers at all.

    "We have no rules for this sender yet" is not "this document has a problem",
    and putting the two in one queue would bury Federal Recycling's invisible
    overlays under every new vendor.
    """
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"total_printed": 0.99}
    ctx.review_flag = True
    out = _gate(thresholds={}).run(ctx)
    assert out.lane == "high"
    assert out.review_flag is True, "preserved, just not lane-determining"


def test_the_gate_never_clears_an_upstream_review_flag():
    """Three C3 ops raise it. A gate that reset it would silently discard the
    reason a human was supposed to look."""
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"total_printed": 0.99}
    ctx.review_flag = True
    out = _gate(thresholds={}, audit_rate=0.0).run(ctx)
    assert out.review_flag is True


def test_a_systemic_failure_outranks_a_forced_review():
    """Both are true, but `low` carries the actionable signal: regenerate the
    rules. `review_flag` is set either way, so the ROUTING loses nothing by
    preferring it. The forced REASON is a separate claim, covered by
    `test_a_forced_reason_is_not_dropped_when_confidence_also_collapses` below.
    """
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"a": 0.1, "b": 0.1, "c": 0.1}
    ctx.add_tag("has_flattened_annotations")
    out = _gate(thresholds={}).run(ctx)
    assert out.lane == "low"
    assert out.regen_flag is True
    assert out.review_flag is True


def test_a_forced_reason_is_not_dropped_when_confidence_also_collapses():
    """N3: `lane == "low"` correctly outranks `review` for ROUTING (both are
    already forced to `review_flag=True` regardless), but the forced reason
    (e.g. `bill_to_mismatch` - a wrong-inbox document) must still be reported,
    not silently replaced by the collapse reason. A human reading the log
    should see "this may be the wrong inbox", not just "regenerate the rules".
    """
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"a": 0.1, "b": 0.1, "c": 0.1}
    ctx.add_tag("bill_to_mismatch")
    out = _gate(thresholds={}).run(ctx)
    assert out.lane == "low"
    assert out.regen_flag is True
    assert out.review_flag is True
    assert any("bill_to_mismatch" in e for e in out.events), (
        "the forced reason must still be surfaced even though `low` wins routing"
    )


def test_a_forced_reason_is_not_dropped_when_coverage_collapses():
    """The same drop, via the OTHER `low` path: `_collapsed(ctx)` (coverage-based,
    not confidence-based) also outranks forced review for routing, and must also
    not swallow the forced reason.
    """
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"a": 0.99}
    ctx.coverage = Coverage(declared=10, populated=2, missing_required=(), assessed=True)
    ctx.add_tag("bill_to_mismatch")
    out = _gate(thresholds={}).run(ctx)
    assert out.lane == "low"
    assert out.regen_flag is True
    assert out.review_flag is True
    assert any("bill_to_mismatch" in e for e in out.events), (
        "the forced reason must still be surfaced even though `low` wins routing"
    )


def test_an_unforced_tag_does_not_force_review():
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"total_printed": 0.99}
    ctx.add_tag("past_due")
    out = _gate(thresholds={}).run(ctx)
    assert out.lane == "high"
    assert out.review_flag is False


# ==========================================================================
# The second dimension: how far short, not just how many
# ==========================================================================


def test_a_document_wide_modifier_does_not_trigger_regen():
    """THE case the plan's tests miss, and the reason a share-only rule fails.

    A document-wide modifier (`ocr_source`, `draft_rules`) penalizes *every*
    field equally, so the share of short fields is always 0.0 or 1.0 and the
    `medium` lane becomes unreachable. Complete Beverage is exactly this: OCR
    plus handwritten supporting pages gives 0.90 x 0.60 = 0.54 on every field,
    and its gold expects `medium` with regen False — not `low`.

    So `low` requires fields to be *very* low, not merely below threshold.
    """
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"a": 0.54, "b": 0.54, "c": 0.54, "d": 0.54}
    out = _gate(thresholds={}).run(ctx)
    assert out.lane == "medium"
    assert out.regen_flag is False
    assert out.review_flag is True


def test_the_very_low_floor_sits_below_the_harshest_single_modifier():
    """0.60 is the harshest modifier in the section 5 enum
    (`handwriting_detected`). Putting the floor below it means one harsh signal
    can never on its own be read as "the rules are broken" — regen requires a
    genuine collapse across several signals.
    """
    assert VERY_LOW_FLOOR < 0.60


@pytest.mark.parametrize("score,lane", [
    (0.89, "medium"),   # just below a 0.90 threshold
    (0.51, "medium"),   # weak, but one bad modifier explains it
    (0.49, "low"),      # below the floor
    (0.10, "low"),
])
def test_the_boundary_between_medium_and_low(score: float, lane: str):
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"a": score, "b": score, "c": score}
    assert _gate(thresholds={}).run(ctx).lane == lane


def test_a_single_very_low_field_among_healthy_ones_is_medium_not_low():
    """One field collapsing is a document problem; most of them collapsing is a
    rules problem. Only the second warrants regen."""
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"a": 0.95, "b": 0.95, "c": 0.95, "d": 0.05}
    out = _gate(thresholds={}).run(ctx)
    assert out.lane == "medium"
    assert out.regen_flag is False


# ==========================================================================
# Thresholds
# ==========================================================================


def test_a_per_field_threshold_overrides_the_default():
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"vendor_name": 0.80}
    assert _gate(thresholds={"vendor_name": 0.75}).run(ctx).lane == "high"
    ctx2 = new_context("d", "/x.pdf")
    ctx2.confidence = {"vendor_name": 0.80}
    assert _gate(thresholds={"vendor_name": 0.95}).run(ctx2).lane == "medium"


def test_a_field_exactly_on_its_threshold_clears_it():
    """Thresholds are a floor, not a strict inequality — an extracted field at
    exactly the stated confidence has met the bar it was given."""
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"total_printed": 0.90}
    assert _gate(thresholds={"total_printed": 0.90}).run(ctx).lane == "high"


# ==========================================================================
# Audit sampling
# ==========================================================================


def test_audit_sampling_never_fires_outside_the_high_lane():
    """A document already going to a human does not need to be sampled into
    review, and marking it `audit_sample` would corrupt the audit statistics."""
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"total_printed": 0.10, "b": 0.10}
    out = ConfidenceGate(thresholds={}, audit_rate=1.0, rng=random.Random(1)).run(ctx)
    assert out.lane == "low"
    assert out.audit_sample is False


def test_a_zero_audit_rate_never_samples():
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"total_printed": 0.99}
    out = ConfidenceGate(thresholds={}, audit_rate=0.0, rng=random.Random(1)).run(ctx)
    assert out.audit_sample is False
    assert out.review_flag is False


def test_the_same_seed_gives_the_same_decision():
    """Deterministic under a seeded rng: an audit rate that could not be replayed
    would make the audit sample unauditable."""
    def _decide():
        ctx = new_context("d", "/x.pdf")
        ctx.confidence = {"total_printed": 0.99}
        return ConfidenceGate(
            thresholds={}, audit_rate=0.5, rng=random.Random(7)
        ).run(ctx).audit_sample

    assert _decide() == _decide()


# ==========================================================================
# Every document leaves
# ==========================================================================


@pytest.mark.parametrize("confidence", [
    {}, {"a": 0.0}, {"a": 1.0}, {"a": 0.5, "b": 0.5},
])
def test_every_document_gets_a_lane(confidence: dict[str, float]):
    """Stage 7 has three exits but no dead end: count(intaken) == count(emitted)
    depends on this stage always deciding something."""
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = dict(confidence)
    out = _gate(thresholds={}).run(ctx)
    assert out.lane in {"high", "medium", "low", "review"}


def test_regen_implies_review():
    """A regen flag says the rules are wrong, which means this document's output
    cannot be trusted either — it must not be emitted as if it were clean."""
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"a": 0.1, "b": 0.1}
    out = _gate(thresholds={}).run(ctx)
    assert out.regen_flag is True
    assert out.review_flag is True


def test_a_forced_review_outranks_an_empty_confidence_map():
    """Federal Recycling, and why the forcing check runs first.

    A forcing reason is a fact about the DOCUMENT, not about whether extraction
    happened: the page carries values invisible to the text layer whether or not
    a persona ever ran. Its gold expects `review`, not `low`.
    """
    ctx = new_context("d", "/x.pdf")
    ctx.add_tag("has_flattened_annotations")
    out = _gate(thresholds={}).run(ctx)
    assert out.lane == "review"
    assert out.review_flag is True
    assert out.regen_flag is False, "no rules ran, so the rules are not wrong"


def test_an_unforced_empty_confidence_map_is_still_low():
    out = _gate(thresholds={}).run(new_context("d", "/x.pdf"))
    assert out.lane == "low"
    assert out.regen_flag is False


# ==========================================================================
# The human-in-the-loop queue: `_enqueue_unknown_basis`
# ==========================================================================


class _SpyJobs:
    """Records every `enqueue_once` call instead of touching a real store."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def enqueue_once(self, sender_fingerprint, doc_type, kind, context=None, match_key=""):
        self.calls.append((sender_fingerprint, doc_type, kind, context, match_key))
        return True


def _basis_ctx():
    ctx = new_context("d", "/x.pdf", sender_fingerprint="northstar|edco", doc_type="standard_invoice")
    ctx.confidence = {"total_printed": 0.99}
    ctx.add_tag("unknown_prior_balance_basis")
    ctx.extracted.set("prior_balance", 298.34, 0.99)
    ctx.extracted.set("current_charges", 69.62, 0.99)
    ctx.extracted.set("total_printed", 367.96, 0.99)
    return ctx


def test_the_tag_enqueues_a_prior_balance_basis_job():
    jobs = _SpyJobs()
    _gate(thresholds={}, jobs=jobs).run(_basis_ctx())
    assert len(jobs.calls) == 1
    sender_fingerprint, doc_type, kind, _context, _match_key = jobs.calls[0]
    assert sender_fingerprint == "northstar|edco"
    assert doc_type == "standard_invoice"
    assert kind == "prior_balance_basis"


def test_the_job_context_snapshot_carries_only_the_populated_basis_fields():
    """`payments_credits` is one of the four fields the job snapshots, but this
    document never extracted it - it must be absent, not present as null."""
    jobs = _SpyJobs()
    _gate(thresholds={}, jobs=jobs).run(_basis_ctx())
    _, _, _, context, _match_key = jobs.calls[0]
    assert context == {"prior_balance": 298.34, "current_charges": 69.62, "total_printed": 367.96}
    assert "payments_credits" not in context


def test_a_decimal_context_value_is_json_safe():
    from decimal import Decimal

    jobs = _SpyJobs()
    ctx = _basis_ctx()
    ctx.extracted.set("prior_balance", Decimal("298.34"), 0.99)
    _gate(thresholds={}, jobs=jobs).run(ctx)
    _, _, _, context, _match_key = jobs.calls[0]
    assert context["prior_balance"] == "298.34"
    assert isinstance(context["prior_balance"], str)


def test_no_tag_means_no_enqueue_even_with_jobs_present():
    jobs = _SpyJobs()
    ctx = _basis_ctx()
    ctx.tags.remove("unknown_prior_balance_basis")
    _gate(thresholds={}, jobs=jobs).run(ctx)
    assert jobs.calls == []


def test_jobs_none_with_the_tag_present_is_a_safe_no_op():
    """The default - must not crash just because nothing was queued into."""
    out = _gate(thresholds={}).run(_basis_ctx())
    assert out.lane in {"high", "medium", "review", "low"}


def test_enqueueing_is_independent_of_lane_routing():
    """The tag alone does not force review (only `arith_balance_mismatch`, a
    modifier, does that) - the queue entry and the lane are two separate
    facts, exactly as `_enqueue_unknown_basis`'s docstring says."""
    jobs = _SpyJobs()
    ctx = _basis_ctx()  # confidence is high and nothing else forces review
    out = _gate(thresholds={}, jobs=jobs).run(ctx)
    assert len(jobs.calls) == 1
    assert out.lane == "high"


# ==========================================================================
# The processing profile's follow-up jobs: reconciliation and export
# ==========================================================================


def _profile_ctx(**profile):
    ctx = new_context("d1", "/x.pdf", sender_fingerprint="northstar|veritiv", doc_type="standard_invoice")
    ctx.confidence = {"total_printed": 0.99}
    ctx.processing_profile = {"reconciliation": "none", "export": [], **profile}
    return ctx


def test_reconciliation_auto_enqueues_a_document_scoped_job():
    jobs = _SpyJobs()
    _gate(thresholds={}, jobs=jobs).run(_profile_ctx(reconciliation="auto"))
    matches = [c for c in jobs.calls if c[2] == "reconciliation_pending"]
    assert len(matches) == 1
    sender_fingerprint, _doc_type, _kind, context, match_key = matches[0]
    assert sender_fingerprint == "northstar|veritiv"
    assert context == {"document_id": "d1"}
    assert match_key == "d1"  # per-document, not per-vendor - see the docstring


def test_reconciliation_none_enqueues_nothing():
    jobs = _SpyJobs()
    _gate(thresholds={}, jobs=jobs).run(_profile_ctx(reconciliation="none"))
    assert [c for c in jobs.calls if c[2] == "reconciliation_pending"] == []


def test_export_enqueues_one_job_per_named_layout():
    jobs = _SpyJobs()
    _gate(thresholds={}, jobs=jobs).run(_profile_ctx(export=["standard", "telecom_detail"]))
    matches = [c for c in jobs.calls if c[2] == "excel_export_pending"]
    assert len(matches) == 2
    layouts = {c[3]["layout"] for c in matches}
    assert layouts == {"standard", "telecom_detail"}
    match_keys = {c[4] for c in matches}
    assert match_keys == {"d1:standard", "d1:telecom_detail"}


def test_empty_export_list_enqueues_nothing():
    jobs = _SpyJobs()
    _gate(thresholds={}, jobs=jobs).run(_profile_ctx(export=[]))
    assert [c for c in jobs.calls if c[2] == "excel_export_pending"] == []


def test_no_jobs_queue_with_an_auto_profile_is_a_safe_no_op():
    out = _gate(thresholds={}).run(_profile_ctx(reconciliation="auto", export=["standard"]))
    assert out.lane in {"high", "medium", "review", "low"}
