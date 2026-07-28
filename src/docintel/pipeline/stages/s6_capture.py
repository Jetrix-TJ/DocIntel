"""Stage 6: run the op chain, then price every field's confidence.

Order inside `run` is the whole design of this stage:

1. **Document modifiers** - facts about the document or the persona that lower
   confidence on everything (`ocr_source`, `draft_rules`, `soft_miss`).
2. **Value ops** (§4.1), per selector, on that selector's own field.
3. **Document ops** (§4.2-4.4), deduplicated and run in `ops.ORDER` rather than
   in the order a persona happened to list them - a persona must not be able to
   break the F1 derivation by writing `derive_amount_payable` before
   `resolve_carried_balance`.
4. **`derive_document_identity`**, unconditionally. It is not an `adjust` op a
   persona may reference: `validate_record` requires the identity on every
   processed record, and a persona must not be able to opt out by omitting a name.
5. **Confidence**, last, so it prices the values the ops actually left behind.

Confidence is `match_quality` from the executor, multiplied by every applicable
modifier, then raised by any corroboration boosts - in that order, because a
boost is capped relative to the already-penalized value. A cross-check cannot
lift an OCR'd field back to the confidence of a native-text one.
"""

from __future__ import annotations

from docintel.core.confidence import apply_boosts, apply_modifiers
from docintel.core.models import JobContext
from docintel.grammar import ops
from docintel.grammar.ops import base, derive
from docintel.grammar.schema import FieldSelector

# Which extracted field a derived payable inherits its confidence from.
_BASIS_SOURCE = {
    "current_charges": "current_charges",
    "total_printed": "total_printed",
}


class CaptureFields:
    name = "capture_fields"

    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("s6: capture_fields")
        self._document_modifiers(ctx)
        selectors = self._selectors(ctx)
        self._apply_value_ops(ctx, selectors)
        self._apply_document_ops(ctx, selectors)
        derive.derive_document_identity(ctx)
        self._score(ctx)
        return ctx

    # -- inputs ------------------------------------------------------------

    def _selectors(self, ctx: JobContext) -> tuple[object, ...]:
        """The persona's selectors, or nothing if no persona was matched.

        Read off `ctx.persona` rather than injected: the `adjust` ops belong to
        the persona that declared them, so keeping any copy here would be a
        second source of truth that could drift.
        """
        declared = getattr(ctx.persona, "field_selectors", ())
        return tuple(declared) if isinstance(declared, (list, tuple)) else ()

    # -- 1. document-wide modifiers ---------------------------------------

    def _document_modifiers(self, ctx: JobContext) -> None:
        if ctx.text_source == "ocr":
            ctx.add_modifier("ocr_source")
        if ctx.persona_status == "soft_miss":
            ctx.add_modifier("soft_miss")
        if getattr(ctx.persona, "status", None) == "draft":
            ctx.add_modifier("draft_rules")
        if "handwritten_supporting" in ctx.tags:
            # SPEC ERRATUM. Section 5 defines `handwriting_detected` as "Primary
            # page has handwriting", and this tag says the opposite - the
            # handwriting is on a supporting page. C3 therefore did not apply it.
            #
            # Complete Beverage's gold routing settles it the other way: its
            # `expected_routing.reason` reads "OCR-only source plus handwritten
            # supporting pages; ocr_source and handwriting modifiers apply", and
            # it expects the `medium` lane. With `ocr_source` alone every field
            # scores exactly 0.90, clears the default threshold, and the document
            # would fast-lane.
            #
            # It is also the better reading. A supporting page exists to
            # corroborate the primary one (F10); if that corroboration is
            # handwritten, it is weaker evidence, and the invoice it supports is
            # correspondingly less certain. Section 5's wording is too narrow
            # rather than this being too broad.
            ctx.add_modifier("handwriting_detected")
        if "has_flattened_annotations" in ctx.tags:
            # F3. The 0.75 penalty belongs here because it is a confidence
            # question. Section 5 also says this modifier *forces* review
            # unconditionally; making the gate act on it is C4's task, since
            # `s7_gate` does not read `ctx.tags` yet.
            ctx.add_modifier("flattened_annotations")

    # -- 2. value ops ------------------------------------------------------

    def _apply_value_ops(self, ctx: JobContext, selectors: tuple[object, ...]) -> None:
        """Transform each field by the ops its own selector declared, in order."""
        for selector in selectors:
            if not isinstance(selector, FieldSelector):
                continue
            value = ctx.extracted.get(selector.field)
            if value is None:
                continue
            changed = False
            for name in selector.adjust:
                op = base.VALUE_OPS.get(name)
                if op is None:
                    continue  # a document op; handled below
                value = op(value)
                changed = True
            if changed:
                quality = ctx.extracted.match_quality.get(selector.field, 1.0)
                ctx.extracted.set(selector.field, value, quality)

    # -- 3. document ops ---------------------------------------------------

    def _apply_document_ops(self, ctx: JobContext, selectors: tuple[object, ...]) -> None:
        requested: list[str] = []
        for selector in selectors:
            for name in getattr(selector, "adjust", ()):
                if name in ops.OPS:
                    requested.append(name)
        for name in ops.ordered(requested):
            ctx = ops.OPS[name](ctx)

    # -- 5. confidence -----------------------------------------------------

    def _score(self, ctx: JobContext) -> None:
        for name, quality in ctx.extracted.match_quality.items():
            penalized = apply_modifiers(quality, ctx.modifiers)
            ctx.confidence[name] = apply_boosts(penalized, ctx.boosts.get(name, 0))

        # The payable is the number that matters most, and it is derived, so it
        # has no match_quality of its own. It inherits from whichever field it
        # was based on - `payable_basis` records exactly which.
        if ctx.derived.get("amount_payable") is None:
            return
        source = _BASIS_SOURCE.get(str(ctx.derived.get("payable_basis")))
        if source is not None and source in ctx.confidence:
            ctx.confidence["amount_payable"] = ctx.confidence[source]
