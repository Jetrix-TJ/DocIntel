"""The vision adapter: a Gemini model reads the page and returns data.

Implements `VisionExtractor` (`adapters/vision/port.py`), routing every result
through the same security boundary (`adapters.vision.policy.sanitize` - the
allowlist, irregularity enum, and confidence clamp) as every other adapter in
this package. Same "the model transcribes, it does not decide" discipline as
the system prompt below states outright.

**An anchor/region persona is not required to locate a value** - a field's
name, its type, and one prose sentence describing where a human would look is
enough. Deleting anchor/region geometry from a Gemini prompt, across 10
documents and 256 assertions, moved 1 value in 102 that had it (see
`docs/agent-hints/README.md`). So this adapter accepts an OPTIONAL
`field_hints` map - `{field_name: "one sentence describing where it sits"}`
- built from a persona's own `anchor`/`region` (or from nothing at all) - and
falls back to a bare field-name request when no hint is supplied.

**Untested against a live key until this file's own first real run.** What's
pinned here is the request shape and the response handling, not that Google's
SDK accepts it forever. Model IDs, per-page token costs and request-size
limits all move; check Google's current docs rather than trusting the
constants here.
"""

from __future__ import annotations

import json
import os
from typing import Any

from docintel.adapters.vision.policy import VISION_OBSERVABLE, sanitize
from docintel.adapters.vision.port import VisionResult
from docintel.core.errors import PermanentError, TransientError
from docintel.core.models import PageText
from docintel.extract.convert import VISION_NATIVE_IMAGE_SUFFIXES

MODEL = "gemini-2.5-pro"

# Gemini bills a PDF page as an image plus its text, so cost scales with page
# count. A refusal, not a warning: the mistake is one flag away, silent, and
# only visible afterwards on a bill.
#
# 30, not 10: a real-world sample of 24 telecom/utility invoices (see
# docs/BUGS-FEATURES-PRODUCTION.md) found 4 legitimate documents at 14-18
# pages - a 10-page guard rejected ~1 in 6 real invoices outright. The actual
# API constraint is cost and the inline-part byte ceiling below, not a hard
# platform page limit, so this number is a deliberate cost/coverage choice,
# adjustable as real volume dictates - not a wall to raise reactively later.
MAX_PAGES = 30
MAX_PDF_BYTES = 15 * 1024 * 1024  # Gemini's inline-part ceiling; bigger needs the Files API.

# The literal MIME string per vision-native image suffix - which suffixes
# qualify at all is `extract.convert.VISION_NATIVE_IMAGE_SUFFIXES` (the
# single source of truth this and `s5b_vision.py` both read), so the two
# cannot silently drift apart; this dict only adds the MIME-string detail
# that's specific to this one adapter's API.
_IMAGE_MIME_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}
assert set(_IMAGE_MIME_TYPES) == VISION_NATIVE_IMAGE_SUFFIXES, (
    "_IMAGE_MIME_TYPES must cover exactly VISION_NATIVE_IMAGE_SUFFIXES"
)

# Reuses `MAX_PDF_BYTES` rather than inventing a second, unverified number:
# that constant is documented as Gemini's INLINE-PART ceiling generally (any
# single inline `Part` sent to `generate_content`, "bigger needs the Files
# API"), not a PDF-specific limit - so the same ceiling is the right guard
# for an inline image part too. Flagged rather than silently assumed: no
# official page found on this review states an image-specific byte ceiling
# distinct from the general inline-part limit; verify against current docs
# or a live key before trusting this for a production image size guard.
MAX_IMAGE_BYTES = MAX_PDF_BYTES

# The SDK's own default is no timeout at all (`HttpOptions.timeout=None`, which
# `_api_client.py` documents as "httpx/aiohttp uses its own default, typically
# None") - a single call can hang the calling `Runner._run_one` attempt
# indefinitely rather than failing fast into a retry or a dead letter. 120s is
# generous for a 30-page inline PDF (the `MAX_PAGES` guard above) while still
# bounding the worst case to something a caller can plan around.
_REQUEST_TIMEOUT_SECONDS = 120

_SYSTEM = """\
You read scanned and native-PDF business documents - vendor invoices, telecom \
bills, credit memos - and transcribe specific named values from them.

Transcribe. Do not interpret.

- Report each value EXACTLY as printed: same digits, same separators, same \
currency symbol, same date format. Do not reformat, normalize, or convert.
- Do NOT do arithmetic. Do not sum line items, do not net credits against \
charges, do not compute a balance.
- Do NOT decide which number should be paid. If a document shows several totals, \
report the one the requested field names, as printed. `total_printed` means the \
headline total printed on the document, even when you believe a different number \
is the amount actually due.
- Read only from the document. Never infer a value from the filename, from what \
is typical for this vendor, or from what would make the numbers agree.
- If a value is not legibly present, return an empty string for it. An empty \
string is a correct and useful answer; a guess is not.
- Copy each value exactly as printed, character for character - including odd \
spacing. Do not close up or insert gaps to make it look tidy.

For each value you do return, give a confidence in [0, 1]: how sure you are that \
you transcribed what is printed. Low confidence on a smudged or ambiguous \
character is expected and wanted.

Report an irregularity only when you can see it on the page:
- `handwriting_detected` - handwritten marks, signatures or annotations.
- `high_skew` - the page is visibly rotated or skewed enough to impair reading.
"""


class GeminiVision:
    """`VisionExtractor` backed by a Gemini model.

    `field_hints`, if given here at construction, is `{field_name: "one
    descriptive sentence"}` - no anchor, no region, no regex. Fields with no
    entry are still requested, just without a hint. This is a per-instance
    DEFAULT for a caller that only ever serves one vendor; `extract()` also
    accepts `field_hints` per call, which - when given - replaces this default
    for that call only. Stage 5b uses the per-call form, since one shared
    `GeminiVision` instance serves every vendor across a run and the hint set
    is a property of the document's persona, not of the adapter.
    """

    def __init__(
        self,
        model: str = MODEL,
        api_key: str | None = None,
        client: Any | None = None,
        field_hints: dict[str, str] | None = None,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._client = client
        self.field_hints = field_hints or {}

    # -- the port ----------------------------------------------------------

    def extract(
        self,
        pages: tuple[PageText, ...],
        field_names: list[str],
        *,
        source_path: str | None = None,
        field_hints: dict[str, str] | None = None,
        table_requests: dict[str, list[str]] | None = None,
        table_hints: dict[str, dict[str, str]] | None = None,
    ) -> VisionResult:
        tables = table_requests or {}
        if not field_names and not tables:
            return VisionResult()
        document_bytes, mime_type, page_count = _read_document(source_path)
        hints = self.field_hints if field_hints is None else field_hints
        prompt = self._prompt(field_names, page_count, hints, tables, table_hints or {})
        payload = self._send(document_bytes, mime_type, prompt, _schema(field_names, tables))
        return sanitize(_result_from(payload), field_names, tables)

    # -- request -------------------------------------------------------------

    def _prompt(
        self,
        field_names: list[str],
        page_count: int,
        hints: dict[str, str],
        tables: dict[str, list[str]],
        table_hints: dict[str, dict[str, str]],
    ) -> str:
        pages_note = f"This document has {page_count} page{'s' if page_count != 1 else ''}."
        parts = [pages_note]

        if field_names:
            lines = []
            for name in field_names:
                hint = hints.get(name)
                lines.append(f"  - {name}: {hint}" if hint else f"  - {name}")
            parts.append(
                "Transcribe the following values from this document:\n"
                + "\n".join(lines)
                + "\n\nReturn every name listed above, using an empty string for any "
                "you cannot read off the document."
            )

        for table_name, columns in tables.items():
            column_hints = table_hints.get(table_name, {})
            col_lines = []
            for col in columns:
                hint = column_hints.get(col)
                col_lines.append(f"  - {col}: {hint}" if hint else f"  - {col}")
            parts.append(
                f'Also transcribe every row of the "{table_name}" table, if this '
                "document has one, with these columns:\n"
                + "\n".join(col_lines)
                + "\n\nReturn one object per row, in the order printed on the page, "
                "using an empty string for any cell you cannot read. Return an "
                "empty list if this table is not present in the document at all. "
                "Do NOT include a subtotal, prior-balance, payment-received, or "
                "total row as a line item - only genuine charge/detail rows."
            )

        return "\n\n".join(parts)

    def _send(self, document_bytes: bytes, mime_type: str, prompt: str, schema: Any) -> dict[str, Any]:
        from google.genai import types

        client = self._resolve_client()
        document = types.Part.from_bytes(data=document_bytes, mime_type=mime_type)
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=[document, prompt],
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM,
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.0,
                    # Milliseconds - the SDK's own field, not seconds.
                    http_options=types.HttpOptions(timeout=_REQUEST_TIMEOUT_SECONDS * 1000),
                ),
            )
        except Exception as exc:
            raise _wrap(exc) from exc
        return self._parse(response)

    def _resolve_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise PermanentError(
                "the google-genai SDK is not installed; `pip install google-genai` "
                "or use a fake/cassette client for testing"
            ) from exc
        # The SDK's own auto-detection only looks at GOOGLE_API_KEY. This
        # project's key lives in GEMINI_API_KEY, so it has to be read explicitly -
        # otherwise a bare GeminiVision() silently falls through to "no
        # credentials" even with a real key sitting in the environment.
        key = self._api_key or os.environ.get("GEMINI_API_KEY")
        try:
            self._client = genai.Client(api_key=key) if key else genai.Client()
        except ValueError as exc:
            raise PermanentError(f"no Gemini credentials: {exc}") from exc
        return self._client

    def _parse(self, response: Any) -> dict[str, Any]:
        text = getattr(response, "text", None)
        if not text:
            raise PermanentError("vision response carried no text")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PermanentError(f"vision response was not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise TypeError(f"vision response was {type(payload).__name__}, expected an object")
        return payload


# ---------------------------------------------------------------------------
# request/response helpers
# ---------------------------------------------------------------------------


def _schema(field_names: list[str], tables: dict[str, list[str]] | None = None) -> Any:
    """The response schema.

    Gemini's schema subset has no `additionalProperties: false`, which makes
    `policy.sanitize` load-bearing rather than a belt-and-braces second check
    here. Every scalar value is a plain string; coercion into a real type
    happens downstream in the pipeline (Stage 6's `pattern`). Table rows are
    the same discipline one level down: every column is a plain string, one
    object per row, so a table adds a repeating shape rather than a new type.
    """
    from google.genai import types

    def obj(props: dict[str, Any], required: list[str]) -> Any:
        return types.Schema(type=types.Type.OBJECT, properties=props, required=required)

    properties: dict[str, Any] = {
        "fields": obj({n: types.Schema(type=types.Type.STRING) for n in field_names}, field_names),
        "confidence": obj({n: types.Schema(type=types.Type.NUMBER) for n in field_names}, field_names),
        "irregularities": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(type=types.Type.STRING, enum=sorted(VISION_OBSERVABLE)),
        ),
    }
    required = ["fields", "confidence", "irregularities"]

    if tables:
        row_schema = {
            table_name: types.Schema(
                type=types.Type.ARRAY,
                items=obj({col: types.Schema(type=types.Type.STRING) for col in columns}, list(columns)),
            )
            for table_name, columns in tables.items()
        }
        properties["tables"] = obj(row_schema, list(tables))
        required.append("tables")

    return obj(properties, required)


def _read_document(source_path: str | None) -> tuple[bytes, str, int]:
    """The document's bytes, the MIME type to send them as, and a page count
    for the prompt - or a clear refusal.

    Two shapes, dispatched on suffix: a `.pdf` gets the original page-count/
    byte-ceiling treatment via `pypdf`; a Gemini-native image suffix
    (`_IMAGE_MIME_TYPES` - currently `.jpg`/`.jpeg`/`.png`) is read as raw
    bytes with `page_count=1` (an image has no page concept) and its own
    byte-ceiling check. Anything else is a refusal: Stage 2/Stage 5b's own
    design (see `pipeline/stages/s2_filter.py`, `s5b_vision.py`) never hands
    this function a path in any other shape - a DOCX/XLSX/TIFF/BMP/GIF has
    already been rendered to PDF by the time vision is reached - so reaching
    this branch means that invariant broke upstream, and this function should
    say so loudly rather than guess a MIME type.

    No text-layer fallback: falling back to `PageText` would turn a vision
    call into a text call at the exact moment vision was asked for.
    """
    if not source_path or not os.path.isfile(source_path):
        raise PermanentError(
            f"vision needs the source document; {source_path!r} is not a readable file"
        )
    suffix = os.path.splitext(source_path)[1].lower()
    if suffix == ".pdf":
        return _read_pdf(source_path)
    if suffix in _IMAGE_MIME_TYPES:
        return _read_image(source_path, suffix)
    raise PermanentError(
        f"gemini adapter handles PDFs and {sorted(_IMAGE_MIME_TYPES)} images; "
        f"{os.path.basename(source_path)} is neither - it should have been "
        "rendered to PDF before reaching vision"
    )


def _read_pdf(source_path: str) -> tuple[bytes, str, int]:
    size = os.path.getsize(source_path)
    if size > MAX_PDF_BYTES:
        raise PermanentError(
            f"{os.path.basename(source_path)} is {size} bytes, over the "
            f"{MAX_PDF_BYTES}-byte inline-part limit"
        )
    import pypdf

    with open(source_path, "rb") as fh:
        data = fh.read()
    page_count = len(pypdf.PdfReader(source_path).pages)
    if page_count > MAX_PAGES:
        raise PermanentError(
            f"{os.path.basename(source_path)} is {page_count} pages, over the "
            f"{MAX_PAGES}-page guard - cost scales with page count on this vendor"
        )
    return data, "application/pdf", page_count


def _read_image(source_path: str, suffix: str) -> tuple[bytes, str, int]:
    size = os.path.getsize(source_path)
    if size > MAX_IMAGE_BYTES:
        raise PermanentError(
            f"{os.path.basename(source_path)} is {size} bytes, over the "
            f"{MAX_IMAGE_BYTES}-byte inline-part limit"
        )
    with open(source_path, "rb") as fh:
        data = fh.read()
    return data, _IMAGE_MIME_TYPES[suffix], 1


def _result_from(payload: dict[str, Any]) -> VisionResult:
    fields = payload.get("fields")
    confidence = payload.get("confidence")
    irregularities = payload.get("irregularities")
    tables = payload.get("tables")
    row_groups: dict[str, list[dict[str, str]]] = {}
    if isinstance(tables, dict):
        for name, rows in tables.items():
            if isinstance(rows, list):
                row_groups[name] = [row for row in rows if isinstance(row, dict)]
    return VisionResult(
        fields=dict(fields) if isinstance(fields, dict) else {},
        confidence=dict(confidence) if isinstance(confidence, dict) else {},
        irregularities=list(irregularities) if isinstance(irregularities, list) else [],
        row_groups=row_groups,
    )


def _wrap(exc: Exception) -> Exception:
    """Classify an SDK exception as retryable or not - duck-typed so this
    works whether or not the SDK is installed, and because the status is the
    real signal, not the exception's class hierarchy."""
    if isinstance(exc, (TransientError, PermanentError)):
        return exc
    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if isinstance(status, int) and (status in (408, 409, 429) or status >= 500):
        return TransientError(f"vision request failed with status {status}: {exc}")
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return TransientError(f"vision request could not reach the API: {exc}")
    # The SDK's own transport (`google.genai._api_client`) raises
    # `httpx.TimeoutException`/`httpx.ConnectError` directly on a request that
    # hits `_REQUEST_TIMEOUT_SECONDS` or cannot connect at all - neither
    # inherits from the built-in `TimeoutError`/`ConnectionError` checked
    # above, so without this they fell all the way through to
    # `PermanentError` and a timeout would dead-letter every document on the
    # first hit instead of ever being retried. Imported lazily, matching
    # `_resolve_client`'s own guard: whenever the SDK path actually ran far
    # enough to raise one of these, httpx (a transitive `google-genai`
    # dependency) is necessarily already installed.
    try:
        import httpx
    except ImportError:
        httpx = None  # pragma: no cover - depends on the environment
    if httpx is not None and isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return TransientError(f"vision request could not reach the API: {exc}")
    return PermanentError(f"vision request failed: {type(exc).__name__}: {exc}")
