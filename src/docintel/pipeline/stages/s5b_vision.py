"""Stage 5b: no rules, or the rules collapsed? Send the pages to a vision model."""

from __future__ import annotations

from docintel.adapters.vision.hints import field_names_for_persona, hints_for_persona
from docintel.core import coverage
from docintel.core.confidence import MODIFIERS
from docintel.core.coverage import DEFAULT_COLLAPSE_SHARE
from docintel.core.models import JobContext

COLLAPSE_THRESHOLD = 0.50
DEFAULT_FIELDS = ["vendor_name", "invoice_number", "invoice_date", "total_printed"]


def _collapsed(ctx: JobContext) -> bool:
    """Have the cached rules failed, rather than the document being bad?

    True when two or more fields fall below threshold, when NOTHING was
    extracted at all — a persona whose selectors matched zero fields has failed
    just as completely as one whose values came back weak — or when most of
    what the persona declared came back empty, even if the few fields that DID
    match are individually confident.

    That third case is the one confidence alone cannot see: `match_quality` is
    only ever recorded for a field that produced a value (`ExtractedFields.set`),
    so a persona with 14 declared fields where 12 return nothing and 2 return
    confidently never appears in `weak` at all - the other 12 are simply absent
    from the dict, not "weak". `core.coverage.assess` is the one place that
    already answers "how much of what was declared came back empty", and
    `s7_gate.ConfidenceGate` already routes on it for exactly this reason - this
    reuses the same computation rather than inventing a second one.

    Calling `coverage.assess(ctx)` here is safe this early: by the time Stage 5b
    runs, `ctx.persona`, `ctx.pack` and `ctx.doc_type` are already set (Stage 3
    classifies, Stage 4 looks up the persona), which is everything `assess`
    reads. It is NOT the same call `CaptureFields` (stage 6) makes into
    `ctx.coverage` - this one is ephemeral and must never be assigned back onto
    `ctx`, because Stage 6 still has adjust ops to run first, and its own
    `coverage.assess(ctx)` afterward is the one that actually lands on the
    emitted record. Computing it twice costs nothing (pure, in-memory) and
    keeps this stage's escalation decision independent of the gate's routing.
    """
    if not ctx.extracted.match_quality:
        return True
    weak = [q for q in ctx.extracted.match_quality.values() if q < COLLAPSE_THRESHOLD]
    if len(weak) >= 2:
        return True
    cov = coverage.assess(ctx)
    return cov.assessed and cov.miss_share >= DEFAULT_COLLAPSE_SHARE


class VisionOneShot:
    name = "vision_one_shot"

    def __init__(self, vision: object, field_names: list[str] | None = None) -> None:
        self.vision = vision
        # `None` means "derive from the persona when one is known" (see
        # `_field_names_and_hints`) - an explicit list here is a caller's
        # override and always wins, the same contract this parameter has
        # always had (e.g. the isolated vision eval, which deliberately wants
        # a fixed, vendor-independent field set to score against).
        self._field_names_override = field_names

    def run(self, ctx: JobContext) -> JobContext:
        if ctx.extraction_route == "5a_cached" and not _collapsed(ctx):
            return ctx
        ctx.log("s5b: vision_one_shot")
        field_names, hints = self._field_names_and_hints(ctx)
        # The path is what makes this vision rather than a text call - see
        # `adapters.vision.port`. Passed by keyword so a stand-in may ignore it.
        # `readable_path` wins when Stage 2 converted a non-PDF input to PDF
        # (`core.models.JobContext.readable_path`) - the vision adapter needs
        # a real PDF's bytes on disk, and `source_path` may point at the
        # original image/Office file that produced them.
        result = self.vision.extract(  # type: ignore[attr-defined]
            ctx.pages, field_names,
            source_path=ctx.readable_path or ctx.source_path, field_hints=hints,
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

    def _field_names_and_hints(self, ctx: JobContext) -> tuple[list[str], dict[str, str]]:
        """What to ask vision for, and how to describe where to find it.

        An explicit constructor override always wins - a caller that built
        this stage with its own list already knows what it wants, and asked
        for no hints along with it. Otherwise: a KNOWN persona's own declared
        fields plus its own anchor/region prose (`adapters.vision.hints`) -
        the vendor's own field list is a strictly better request than the
        4-field generic default, whether this document reached vision because
        there was no persona at all or because a known persona's read
        collapsed. A persona that (unusually) declares no scalar fields at
        all falls through to the same generic default a true first-time
        vendor gets, since there is nothing more specific to ask for either
        way. A genuinely brand-new vendor (no persona) has no vendor
        knowledge to draw on, so it gets the generic default with no hints -
        exactly what vision was always asked for in that case.
        """
        if self._field_names_override is not None:
            return self._field_names_override, {}
        if ctx.persona is not None:
            names = field_names_for_persona(ctx.persona)
            if names:
                return names, hints_for_persona(ctx.persona)
        return DEFAULT_FIELDS, {}
