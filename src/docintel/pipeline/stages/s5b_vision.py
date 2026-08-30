"""Stage 5b: no rules, or the rules collapsed? Send the pages to a vision model."""

from __future__ import annotations

import os

from docintel.adapters.vision.hints import (
    field_names_for_persona,
    hints_for_persona,
    table_hints_for_persona,
    table_requests_for_persona,
    vision_type_prose,
)
from docintel.core import coverage
from docintel.core.confidence import MODIFIERS
from docintel.core.models import JobContext
from docintel.extract import convert, office_render
from docintel.extract.plaintext import SOURCE_FORMATS as TEXT_NATIVE_SOURCE_FORMATS

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
    reuses the same computation (and the same `Coverage.collapsed` verdict,
    share AND absolute-count floor both) rather than inventing a second one.

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
    return cov.collapsed


def _pack_vision_defaults(ctx: JobContext) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """`(ctx.pack.vision_defaults(ctx.doc_type))`, or `({}, {})` when there is
    no matched pack, no doc_type yet, or the pack declares this method at all
    (see `DataPack.vision_defaults`'s own docstring for why this is read
    defensively via `getattr` rather than a required `registry.Pack` Protocol
    method: the two hand-coded module packs, `northstar`/`digitaldirection`,
    declare none today)."""
    getter = getattr(ctx.pack, "vision_defaults", None)
    if getter is None or ctx.doc_type is None:
        return {}, {}
    return getter(ctx.doc_type)


class VisionOneShot:
    name = "vision_one_shot"

    def __init__(
        self,
        vision: object,
        field_names: list[str] | None = None,
        table_requests: dict[str, list[str]] | None = None,
    ) -> None:
        self.vision = vision
        # `None` means "derive from the persona, then the pack, when either is
        # known" (see `_field_names_and_hints`/`_table_requests_and_hints`) -
        # an explicit value here is a caller's override and always wins, the
        # same contract `field_names` has always had (e.g. the isolated vision
        # eval, which deliberately wants a fixed, vendor-independent field set
        # to score against).
        self._field_names_override = field_names
        self._table_requests_override = table_requests

    def run(self, ctx: JobContext) -> JobContext:
        if ctx.extraction_route == "5a_cached" and not _collapsed(ctx):
            return ctx
        if ctx.source_format in TEXT_NATIVE_SOURCE_FORMATS:
            # TXT/CSV/HTML carry no visual content a vision model could add
            # anything by looking at - see `extract.plaintext.SOURCE_FORMATS`'s
            # own docstring - and Gemini does not accept any of them as a
            # document input at all. Rather than spend a request pretending
            # vision might help (or, with the real adapter, raise a
            # `PermanentError` because the format is neither a PDF nor a
            # Gemini-native image), this stage is a deliberate no-op here: a
            # persona-less document of one of these formats reaches Stage 6/7
            # with whatever `extraction_route` it already had (`None`, if
            # there was no persona at all), and Stage 7's "nothing was
            # scored" branch already handles that honestly.
            ctx.log("s5b: vision_one_shot skipped - no visual content in this format")
            return ctx
        ctx.log("s5b: vision_one_shot")
        field_names, hints = self._field_names_and_hints(ctx)
        table_requests, table_hints = self._table_requests_and_hints(ctx)
        # The path is what makes this vision rather than a text call - see
        # `adapters.vision.port`. Passed by keyword so a stand-in may ignore it.
        result = self.vision.extract(  # type: ignore[attr-defined]
            ctx.pages, field_names,
            source_path=self._vision_source_path(ctx), field_hints=hints,
            table_requests=table_requests, table_hints=table_hints,
        )
        for name, value in result.fields.items():
            ctx.extracted.set(name, value, result.confidence.get(name, 0.50))
        # Same dict `grammar.executor.Executor._apply_row_group` writes to for
        # the persona/5a path - `core.contract.build_record`'s promotion of
        # `line_items`/`charges`/`sub_account` already reads from here
        # unconditionally, regardless of which stage populated it.
        for table_name, rows in result.row_groups.items():
            ctx.row_groups[table_name] = rows
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

        Four tiers, each falling through only when the one before has
        nothing to offer: **(1)** an explicit constructor override always
        wins - a caller that built this stage with its own list already knows
        what it wants, and asked for no hints along with it. **(2)** a KNOWN
        persona's own declared fields plus its own anchor/region prose
        (`adapters.vision.hints`) - the vendor's own field list is a strictly
        better request than the generic default, whether this document
        reached vision because there was no persona at all or because a known
        persona's read collapsed. **(3)** the matched PACK's own
        `vision_defaults` for this doc_type, if it declares any - the
        1000-unknown-vendor case, where no persona exists and none ever will
        (`_pack_vision_defaults`). **(4)** the hardcoded generic default, for
        a document under neither a persona nor a pack declaration.
        """
        if self._field_names_override is not None:
            return self._field_names_override, {}
        if ctx.persona is not None:
            names = field_names_for_persona(ctx.persona)
            if names:
                return names, hints_for_persona(ctx.persona)
        pack_fields, _ = _pack_vision_defaults(ctx)
        if pack_fields:
            hints = {
                name: prose
                for name, type_name in pack_fields.items()
                if (prose := vision_type_prose(type_name)) is not None
            }
            return list(pack_fields), hints
        return DEFAULT_FIELDS, {}

    def _table_requests_and_hints(
        self, ctx: JobContext
    ) -> tuple[dict[str, list[str]], dict[str, dict[str, str]]]:
        """The table-extraction mirror of `_field_names_and_hints`, same four
        tiers: constructor override, then a known persona's own `row_group`
        selector(s), then the matched pack's `vision_defaults` tables, then
        nothing (no table asked for at all - not every document has one)."""
        if self._table_requests_override is not None:
            return self._table_requests_override, {}
        if ctx.persona is not None:
            requests = table_requests_for_persona(ctx.persona)
            if requests:
                return requests, table_hints_for_persona(ctx.persona)
        _, pack_tables = _pack_vision_defaults(ctx)
        if pack_tables:
            requests = {name: list(columns) for name, columns in pack_tables.items()}
            hints = {
                name: {
                    col: prose
                    for col, type_name in columns.items()
                    if (prose := vision_type_prose(type_name)) is not None
                }
                for name, columns in pack_tables.items()
            }
            return requests, hints
        return {}, {}

    def _vision_source_path(self, ctx: JobContext) -> str:
        """The path to hand the vision adapter for its bytes-on-disk read.

        `readable_path` wins whenever Stage 2 already produced a converted
        PDF (`core.models.JobContext.readable_path`) - true for every DOCX/
        XLSX document, always, and for a TIFF/BMP/GIF document that a PRIOR
        call to this method already converted (see below). Otherwise falls
        through to `source_path`, which is exactly right for a native PDF or
        a Gemini-native image (`ctx.source_format == "image"` and the suffix
        is in `extract.convert.VISION_NATIVE_IMAGE_SUFFIXES` - JPEG/PNG):
        neither is ever converted, by design (Stage 2's docstring, and this
        module's own source-format handling).

        The one case this method acts on rather than merely reads: an image
        document (`ctx.source_format == "image"`) whose suffix is NOT
        Gemini-native (TIFF/BMP/GIF). Gemini does not understand these
        formats natively (verified against live `ai.google.dev` docs - only
        PNG/JPEG/WEBP/HEIC/HEIF are documented image MIME types), so unlike
        JPEG/PNG they cannot go to vision as-is. Rather than Stage 2 eagerly
        converting every TIFF/BMP/GIF up front - paying the conversion cost
        even for documents whose persona's cached rules already succeed and
        never reach this stage at all - the conversion happens HERE, lazily,
        at most once per document, only when vision is actually reached.
        Reuses the same `readable_path`/`temp_dirs` fields Stage 2 already
        uses for DOCX/XLSX, so the `Runner`'s existing unconditional cleanup
        (`pipeline/runner.py`) needs no change to pick this up too.
        """
        if ctx.readable_path is not None:
            return ctx.readable_path
        if ctx.source_format == "xlsx":
            # Reaching here with `readable_path` unset and `source_format ==
            # "xlsx"` can only mean Stage 2 used the LibreOffice-free tier-1
            # HTML fallback (`pipeline.stages.s2_filter`) - the LibreOffice
            # path always sets `readable_path` to a real converted PDF.
            # Tier 1's cached-rule read collapsed (`_collapsed`, above), so
            # render a real image from the ORIGINAL workbook and hand it to
            # vision exactly like any other image.
            path = office_render.xlsx_to_image(ctx.source_path)
            ctx.readable_path = path
            ctx.temp_dirs.append(os.path.dirname(path))
            return path
        if ctx.source_format != "image":
            return ctx.source_path
        suffix = os.path.splitext(ctx.source_path)[1].lower()
        if suffix in convert.VISION_NATIVE_IMAGE_SUFFIXES:
            return ctx.source_path
        # Cache-checked, same discipline as Stage 2's DOCX/XLSX conversion -
        # a cache hit's path must never be registered on `ctx.temp_dirs` (see
        # `extract.convert.convert_to_pdf_cached`'s own docstring for why).
        path, temp_dir = convert.convert_to_pdf_cached(ctx.source_path, suffix)
        ctx.readable_path = path
        if temp_dir is not None:
            ctx.temp_dirs.append(temp_dir)
        return path
