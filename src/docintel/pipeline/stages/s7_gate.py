"""Stage 7: three exits, but every document leaves.

Four lanes, not three. The spec's Stage 7 table lists High, Medium/Low and Very
Low; two gold files require a fourth, `review`, and gold is the objective
function. It earns its place as a real distinction rather than a synonym for
`medium`: Federal Recycling's fields may extract perfectly, and the reason a
human must look is that the page carries values invisible to the text layer
(F3) — not low confidence. Routing that to `medium` would file it alongside
documents whose *numbers* are shaky, which is a different queue and a different
fix.

| Lane | Meaning | Flags |
|---|---|---|
| `high` | Every field cleared its threshold | audit sample only |
| `medium` | Fields fell short, but the shortfall is explained | review |
| `review` | Something mandates a human regardless of confidence | review |
| `low` | Systemic collapse — the rules are wrong, not this document | review + regen |

**Two dimensions decide `medium` versus `low`, not one.** Counting short fields
alone cannot tell them apart, because a document-wide modifier (`ocr_source`,
`draft_rules`, `handwriting_detected`) penalizes *every* field equally — so the
share of short fields is always 0.0 or 1.0 and `medium` becomes unreachable.
Complete Beverage is exactly that case: OCR plus handwritten supporting pages
gives 0.90 x 0.60 = 0.54 on every field, and its gold expects `medium`. So `low`
additionally requires most fields to be below `VERY_LOW_FLOOR` — genuinely
collapsed, not merely penalized.

**The gate may raise `review_flag` but never clears it.** That is a property of
this stage and still holds — but the ops that used to raise it upstream do not
run today.

**DEFERRED (printed-fields-only): nothing sets `review_flag` before this stage.**
`derive_amount_payable` (on each of its three refusals) and
`crosscheck_balance_composition` are in no persona's `adjust` list any more.
`crosscheck_duplicate_anchor` never was, even at baseline — an earlier version of
this docstring named all three as live and was wrong about that one twice over.
Their implementations stay in the tree; see
`docs/superpowers/specs/2026-07-28-printed-fields-only-design.md` section 5.

The same deferral makes `arith_balance_mismatch` in `FORCING_MODIFIERS` below
declared-but-unreachable. Left in place deliberately: the entry is the
specification of what forces review, and it is correct — nothing emits the
modifier today.
"""

from __future__ import annotations

import random

from docintel.core.models import JobContext

DEFAULT_THRESHOLD = 0.90

# Share of fields that must be *very* low before this is a rules problem.
VERY_LOW_SHARE = 0.60

# What counts as very low. Deliberately below 0.60, the harshest single modifier
# in the section 5 enum (`handwriting_detected`): one harsh signal must never on
# its own read as "the rules are broken", because the fix for a handwritten page
# is not a new persona. Regen requires a genuine collapse across several signals.
VERY_LOW_FLOOR = 0.50

# Tags that mandate human review whatever the confidence. Section 5 says
# `flattened_annotations` forces review *unconditionally*, which makes it a
# spec-mandated default rather than something a pack opts into. Packs may add.
#
# `bill_to_mismatch` joins it for the same reason: the printed bill-to disagrees
# with the pack's roster, which means the pack's claim may be wrong - and a
# confidence score computed under a wrong claim is not evidence of anything.
DEFAULT_FORCED_REVIEW_TAGS: frozenset[str] = frozenset(
    {"has_flattened_annotations", "bill_to_mismatch"}
)

# Modifiers that section 5 says raise review on their own:
#   flattened_annotations   0.75  F3 -> "also forces review, unconditionally"
#   arith_balance_mismatch  0.80  F8 -> "also raises review"
#
# Forcing is read from these and from `forced_review_tags`, and deliberately NOT
# from `ctx.review_flag`. That boolean is too coarse to route on: `s5c_agent`
# sets it for every first-time sender, correctly (spec Part 3 - a hard miss
# "emits anyway with the one-shot result and a review flag"), and "we have no
# rules for this sender yet" is not the same statement as "this document has a
# problem". Routing the first case to the `review` lane would put every new
# vendor in the same queue as Federal Recycling's invisible overlays.
#
# The flag is still never *cleared* - see `run`.
FORCING_MODIFIERS: frozenset[str] = frozenset({
    "flattened_annotations", "arith_balance_mismatch",
})

# Share of a persona's declared selectors that must produce nothing before this is
# a rules problem rather than a document problem.
#
# Deliberately the same 0.60 as VERY_LOW_SHARE, and for the same reason: `low`
# triggers a rule rewrite, so it has to mean "this persona no longer describes this
# template", not "one field moved". Below the share, a missing required field still
# forces `review` - the difference is whether someone re-keys one value or
# regenerates the rule set.
INCOMPLETE_COLLAPSE_SHARE = 0.60

LANES = ("high", "medium", "review", "low")


class ConfidenceGate:
    name = "confidence_gate"

    def __init__(
        self,
        thresholds: dict[str, float] | None = None,
        forced_review_tags: set[str] | frozenset[str] | None = None,
        audit_rate: float = 0.0,
        rng: random.Random | None = None,
    ) -> None:
        self.thresholds = thresholds or {}
        self.forced_review_tags = frozenset(
            DEFAULT_FORCED_REVIEW_TAGS
            if forced_review_tags is None
            else forced_review_tags
        )
        self.audit_rate = audit_rate
        self.rng = rng or random.Random(0)

    # -- forcing -----------------------------------------------------------

    def _forced_reasons(self, ctx: JobContext) -> list[str]:
        """Everything demanding a human look, independent of confidence."""
        reasons: list[str] = []
        for tag in sorted(set(ctx.tags) & self.forced_review_tags):
            reasons.append(f"tag:{tag}")
        for modifier in sorted(set(ctx.modifiers) & FORCING_MODIFIERS):
            reasons.append(f"modifier:{modifier}")
        return reasons

    # -- completeness ------------------------------------------------------

    def _incomplete_reasons(self, ctx: JobContext) -> list[str]:
        """Required fields that produced nothing.

        Kept OUT of `_forced_reasons` on purpose. That method answers "is there
        something about this document a human must see", and its answer is allowed
        to outrank an empty confidence map because it is true whether or not
        extraction ever ran. This one answers "did extraction finish", which is
        exactly the opposite kind of fact - so it must not win in the
        nothing-was-scored branch, where the honest verdict is already `low`.
        """
        if ctx.coverage is None:
            return []
        return [f"missing:{name}" for name in ctx.coverage.missing_required]

    def _collapsed(self, ctx: JobContext) -> bool:
        """Most of what the persona declared came back empty."""
        return (
            ctx.coverage is not None
            and ctx.coverage.assessed
            and ctx.coverage.miss_share >= INCOMPLETE_COLLAPSE_SHARE
        )

    # -- confidence --------------------------------------------------------

    def _thresholds_for(self, ctx: JobContext) -> dict[str, float]:
        """Injected thresholds win; otherwise the claiming pack's.

        A pack's thresholds are a business judgement about that domain (a wrong
        total is a wrong payment), so they belong to the pack rather than to the
        gate. An explicit argument still wins, because that is the test seam.
        """
        if self.thresholds:
            return self.thresholds
        pack_thresholds = getattr(ctx.pack, "thresholds", None)
        return pack_thresholds if isinstance(pack_thresholds, dict) else {}

    def _confidence_lane(self, ctx: JobContext) -> str:
        thresholds = self._thresholds_for(ctx)
        short = [
            name for name, score in ctx.confidence.items()
            if score < thresholds.get(name, DEFAULT_THRESHOLD)
        ]
        if not short:
            return "high"

        very_low = [
            name for name, score in ctx.confidence.items()
            if score < VERY_LOW_FLOOR
        ]
        if len(very_low) / len(ctx.confidence) >= VERY_LOW_SHARE:
            return "low"
        return "medium"

    # -- run ---------------------------------------------------------------

    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("s7: confidence_gate")
        forced = self._forced_reasons(ctx)
        incomplete = self._incomplete_reasons(ctx)
        collapsed = self._collapsed(ctx)

        if not ctx.confidence:
            # Nothing was scored, which must never read as "nothing fell short".
            # Deliberately no regen either way: an absent confidence map means no
            # rules ran at all, and "there are no rules yet" is not "the rules
            # are wrong".
            #
            # A forcing reason still wins here, because it is a fact about the
            # DOCUMENT rather than about whether extraction happened. Federal
            # Recycling carries values invisible to the text layer whether or not
            # a persona ever ran, and its gold expects `review` rather than `low`.
            ctx.review_flag = True
            if forced:
                ctx.lane = "review"
                ctx.log(f"s7: review forced by {', '.join(forced)}, nothing scored")
            else:
                ctx.lane = "low"
                # Regen only when a persona actually ran and its rules came back
                # empty - that is a rule set that no longer matches its template.
                # With no persona at all there is nothing to regenerate, which is
                # the distinction this branch drew before coverage existed and
                # could not act on.
                if collapsed:
                    ctx.regen_flag = True
                    ctx.log("s7: every declared selector came back empty; regen")
                else:
                    ctx.log("s7: no field confidence at all; routing to the low lane")
            return ctx

        lane = self._confidence_lane(ctx)

        if collapsed:
            # Ranked with the confidence collapse below, and above forced review,
            # for the same reason: `low` carries the actionable signal (rewrite the
            # rules) and review_flag is set either way, so the ROUTING loses
            # nothing. But the forced REASON is a separate fact - e.g. this may be
            # a wrong-inbox document - and it must still reach the log even though
            # `low` wins the lane, or a human reading it is told only "regenerate
            # the persona" when the more actionable truth is "this may be the
            # wrong inbox".
            ctx.lane = "low"
            ctx.regen_flag = True
            ctx.review_flag = True
            ctx.log(
                f"s7: {ctx.coverage.populated}/{ctx.coverage.declared} declared "
                f"selectors produced a value; the rules no longer fit this document"
            )
            if forced or incomplete:
                ctx.log(f"s7: also forced by {', '.join([*forced, *incomplete])}")
            return ctx

        if lane == "low":
            # A systemic collapse outranks a forced review for ROUTING - both are
            # true, but `low` carries the actionable signal (regenerate the rules)
            # and review_flag is set either way. The forced REASON is still a
            # separate fact that must not be dropped; see the `collapsed` branch
            # above for why.
            ctx.lane = "low"
            ctx.regen_flag = True
            ctx.review_flag = True
            ctx.log(
                "s7: most fields fell below the very-low floor; the rules no "
                "longer fit this document"
            )
            if forced or incomplete:
                ctx.log(f"s7: also forced by {', '.join([*forced, *incomplete])}")
            return ctx

        if forced or incomplete:
            # An incomplete extraction routes here rather than to `medium`, because
            # `medium` means "the numbers are shaky" and sits behind a confidence
            # threshold a well-scoring survivor set would clear. What is wrong here
            # is not a value but the absence of one, so it belongs in the queue for
            # documents a human must look at regardless of confidence.
            ctx.lane = "review"
            ctx.review_flag = True
            ctx.log(f"s7: review forced by {', '.join([*forced, *incomplete])}")
            return ctx

        if lane == "medium":
            ctx.lane = "medium"
            ctx.review_flag = True
            return ctx

        ctx.lane = "high"
        # The audit sample is the only defence against rules that are
        # confidently wrong, so it applies exactly where confidence is highest -
        # and it does NOT change the lane, because the document is genuinely
        # clean and the record should say so.
        if self.audit_rate and self.rng.random() < self.audit_rate:
            ctx.audit_sample = True
            ctx.review_flag = True
            ctx.log("s7: selected as an audit sample")
        return ctx
