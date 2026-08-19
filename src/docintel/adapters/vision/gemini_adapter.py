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
    ) -> VisionResult:
        if not field_names:
            return VisionResult()
        pdf_bytes, page_count = _read_pdf(source_path)
        hints = self.field_hints if field_hints is None else field_hints
        prompt = self._prompt(field_names, page_count, hints)
        payload = self._send(pdf_bytes, prompt, _schema(field_names))
        return sanitize(_result_from(payload), field_names)

    # -- request -------------------------------------------------------------

    def _prompt(self, field_names: list[str], page_count: int, hints: dict[str, str]) -> str:
        lines = []
        for name in field_names:
            hint = hints.get(name)
            lines.append(f"  - {name}: {hint}" if hint else f"  - {name}")
        pages_note = f"This document has {page_count} page{'s' if page_count != 1 else ''}."
        return (
            f"{pages_note}\n\nTranscribe the following values from this document:\n"
            + "\n".join(lines)
            + "\n\nReturn every name listed above, using an empty string for any "
            "you cannot read off the document."
        )

    def _send(self, pdf_bytes: bytes, prompt: str, schema: Any) -> dict[str, Any]:
        from google.genai import types

        client = self._resolve_client()
        document = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=[document, prompt],
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM,
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.0,
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


def _schema(field_names: list[str]) -> Any:
    """The response schema.

    Gemini's schema subset has no `additionalProperties: false`, which makes
    `policy.sanitize` load-bearing rather than a belt-and-braces second check
    here. Every value is a plain string; coercion into a real type happens
    downstream in the pipeline (Stage 6's `pattern`).
    """
    from google.genai import types

    def obj(props: dict[str, Any], required: list[str]) -> Any:
        return types.Schema(type=types.Type.OBJECT, properties=props, required=required)

    return obj(
        {
            "fields": obj({n: types.Schema(type=types.Type.STRING) for n in field_names}, field_names),
            "confidence": obj({n: types.Schema(type=types.Type.NUMBER) for n in field_names}, field_names),
            "irregularities": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING, enum=sorted(VISION_OBSERVABLE)),
            ),
        },
        ["fields", "confidence", "irregularities"],
    )


def _read_pdf(source_path: str | None) -> tuple[bytes, int]:
    """The document's bytes and page count, or a clear refusal.

    No text-layer fallback: falling back to `PageText` would turn a vision
    call into a text call at the exact moment vision was asked for.
    """
    if not source_path or not os.path.isfile(source_path):
        raise PermanentError(
            f"vision needs the source document; {source_path!r} is not a readable file"
        )
    if not source_path.lower().endswith(".pdf"):
        raise PermanentError(
            f"gemini adapter handles PDFs; {os.path.basename(source_path)} is not one"
        )
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
    return data, page_count


def _result_from(payload: dict[str, Any]) -> VisionResult:
    fields = payload.get("fields")
    confidence = payload.get("confidence")
    irregularities = payload.get("irregularities")
    return VisionResult(
        fields=dict(fields) if isinstance(fields, dict) else {},
        confidence=dict(confidence) if isinstance(confidence, dict) else {},
        irregularities=list(irregularities) if isinstance(irregularities, list) else [],
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
    return PermanentError(f"vision request failed: {type(exc).__name__}: {exc}")
