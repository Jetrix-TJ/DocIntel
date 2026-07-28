"""Stage 5b: no rules, or the rules collapsed? Send the pages to a vision model."""

from __future__ import annotations

from docintel.core.confidence import MODIFIERS
from docintel.core.models import JobContext

COLLAPSE_THRESHOLD = 0.50
DEFAULT_FIELDS = ["vendor_name", "invoice_number", "invoice_date", "total_printed"]


def _collapsed(ctx: JobContext) -> bool:
    """Have the cached rules failed, rather than the document being bad?

    True when two or more fields fall below threshold, and also when NOTHING was
    extracted at all — a persona whose selectors matched zero fields has failed
    just as completely as one whose values came back weak.
    """
    if not ctx.extracted.match_quality:
        return True
    weak = [q for q in ctx.extracted.match_quality.values() if q < COLLAPSE_THRESHOLD]
    return len(weak) >= 2


class VisionOneShot:
    name = "vision_one_shot"

    def __init__(self, vision: object, field_names: list[str] | None = None) -> None:
        self.vision = vision
        self.field_names = field_names or DEFAULT_FIELDS

    def run(self, ctx: JobContext) -> JobContext:
        if ctx.extraction_route == "5a_cached" and not _collapsed(ctx):
            return ctx
        ctx.log("s5b: vision_one_shot")
        # `source_path` is what makes this vision rather than a text call - see
        # `adapters.vision.port`. Passed by keyword so a stand-in may ignore it.
        result = self.vision.extract(  # type: ignore[attr-defined]
            ctx.pages, self.field_names, source_path=ctx.source_path
        )
        for name, value in result.fields.items():
            ctx.extracted.set(name, value, result.confidence.get(name, 0.50))
        ctx.extraction_route = "5b_vision"
        for flag in result.irregularities:
            # A vision irregularity that names a section 5 modifier must *be* one,
            # or its penalty never applies. Filing `handwriting_detected` as a tag
            # would record the observation on the emitted record and then leave
            # every field's confidence untouched - the observation would look
            # honoured and do nothing. Anything outside the enum stays a tag, which
            # is the right home for a signal with no defined price.
            #
            # What a vision model may claim is constrained upstream, by
            # `adapters.vision.policy`: neither admitted name is in
            # `s7_gate.FORCING_MODIFIERS`, so this cannot route a lane by itself.
            if flag in MODIFIERS:
                ctx.add_modifier(flag)
            else:
                ctx.add_tag(flag)
        return ctx
