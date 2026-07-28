"""The real vision adapter: an Anthropic model reads the page and returns data.

**Named `anthropic_adapter` rather than `anthropic`** (the plan's file list says
the latter, its interface list says the former). A module called `anthropic.py`
inside this package is safe under absolute imports, but it self-shadows the moment
anyone runs the file directly - `python src/.../anthropic.py` puts its own
directory first on `sys.path` and `import anthropic` finds itself. Not worth the
trap for a nicer name.

**We send the PDF, not rendered PNGs.** The plan says "renders pages to PNG"; the
Messages API takes a base64 `document` block natively, so rasterizing would add a
dependency (pdfium or poppler) to produce a strictly worse input. Worse in three
ways: a re-render can drop the flattened annotation overlays that F3 is entirely
about, page indices would have to be re-derived and kept in step with
`page_meta`, and any resampling choice we made would silently become part of the
extraction's accuracy. Passing the original bytes has none of those problems.

**The model transcribes; it does not decide.** The system prompt forbids
arithmetic, normalization and payable selection. That is not politeness - it is
the same rule the persona path enforces structurally. F1 exists because the
headline total on an invoice is frequently *not* the amount payable, and the
pipeline's answer is a derivation with a recorded `payable_basis`. A vision model
that helpfully returned the "amount due" it judged correct would bypass that
derivation and take the F1 trap with it. So it reports what is printed, and
`derive_amount_payable` still does the deciding.

**Untested against the live API.** `anthropic` is not installed in this
environment and no key exists, so every test here injects a fake client. What is
pinned is the request shape and the response handling; what is not pinned is that
the SDK accepts that shape. First live call should be an operator running
`--vision record` on one document.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from docintel.adapters.vision.policy import VISION_OBSERVABLE, sanitize
from docintel.adapters.vision.port import VisionResult
from docintel.core.errors import PermanentError, TransientError
from docintel.core.models import PageText

MODEL = "claude-opus-5"

# Thinking counts against max_tokens on this model, and thinking is on by default,
# so a budget sized for the JSON alone would truncate mid-answer. 16000 also keeps
# a non-streaming request inside the SDK's HTTP timeout, which is why this adapter
# does not stream: there is exactly one short response to read, and streaming would
# buy nothing while adding a second code path to the fallback branch below.
MAX_TOKENS = 16000

# Raw PDF ceiling. The API's limit is 32 MB *per request* and base64 inflates by
# 4/3, so 20 MB of PDF leaves room for the prompt and the schema.
MAX_PDF_BYTES = 20 * 1024 * 1024

# Opting into server-side refusal fallbacks by default. A scanned AP invoice will
# not trip the cyber/bio classifiers in practice, but a refusal returns HTTP 200
# with an empty `content`, so the cost of not handling it is a confusing parse
# error rather than a clear failure - and the fallback makes the request succeed
# instead of merely failing legibly. Constructor flag, because it needs the beta
# endpoint and an operator may not want that.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

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

For each value you do return, give a confidence in [0, 1]: how sure you are that \
you transcribed what is printed. Low confidence on a smudged or ambiguous \
character is expected and wanted.

Report an irregularity only when you can see it on the page:
- `handwriting_detected` - handwritten marks, signatures or annotations.
- `high_skew` - the page is visibly rotated or skewed enough to impair reading.
"""


class AnthropicVision:
    """`VisionExtractor` backed by an Anthropic model."""

    def __init__(
        self,
        model: str = MODEL,
        api_key: str | None = None,
        client: Any | None = None,
        effort: str = "high",
        fallbacks: bool = True,
    ) -> None:
        self.model = model
        self.effort = effort
        self.fallbacks = fallbacks
        self._api_key = api_key
        self._client = client

    # -- the port ----------------------------------------------------------

    def extract(
        self,
        pages: tuple[PageText, ...],
        field_names: list[str],
        *,
        source_path: str | None = None,
    ) -> VisionResult:
        if not field_names:
            return VisionResult()
        document = _pdf_block(source_path)
        request = self._request(document, field_names, len(pages))
        payload = self._parse(self._send(request))
        return sanitize(_result_from(payload, field_names), field_names)

    # -- request -----------------------------------------------------------

    def _request(
        self, document: dict[str, Any], field_names: list[str], page_count: int
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            # The system prompt is byte-identical across documents, so it is the
            # only cacheable prefix here. Opus 5's minimum cacheable prefix is 512
            # tokens; below that this silently does nothing, which is why it is
            # marked and then forgotten rather than measured.
            "system": [
                {
                    "type": "text",
                    "text": _SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "thinking": {"type": "adaptive"},
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": _schema(field_names)},
            },
            "messages": [
                {
                    "role": "user",
                    # Document block first: the API wants it ahead of the text
                    # that refers to it.
                    "content": [
                        document,
                        {"type": "text", "text": _prompt(field_names, page_count)},
                    ],
                }
            ],
        }

    def _send(self, request: dict[str, Any]) -> Any:
        client = self._resolve_client()
        try:
            if self.fallbacks:
                return client.beta.messages.create(
                    betas=[FALLBACK_BETA], fallbacks="default", **request
                )
            return client.messages.create(**request)
        except Exception as exc:  # noqa: BLE001 - re-raised, classified
            raise _wrap(exc) from exc

    def _resolve_client(self) -> Any:
        """Build the SDK client on first use.

        Lazy so `anthropic` stays an optional extra: importing this module must not
        require the SDK, or `--vision fake` and `--vision cassette` would need a
        dependency they never call.
        """
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise PermanentError(
                "the anthropic SDK is not installed; `pip install 'docintel[vision]'` "
                "or use --vision cassette"
            ) from exc
        # No api_key argument when none was passed: the SDK then resolves
        # ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, or an `ant auth login` profile,
        # and passing None would not.
        kwargs = {"api_key": self._api_key} if self._api_key else {}
        self._client = anthropic.Anthropic(**kwargs)
        return self._client

    # -- response ----------------------------------------------------------

    def _parse(self, response: Any) -> dict[str, Any]:
        """The response's JSON body, or a clear failure.

        `stop_reason` is checked before `content` is touched, because a refusal
        returns 200 with an empty content list and indexing it would report a
        safety decline as a malformed response.
        """
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None)
            raise PermanentError(
                f"vision request declined by safety classifiers (category={category})"
            )
        if stop_reason == "max_tokens":
            # Truncated JSON is unparseable, and the useful message is *why*.
            raise TransientError(
                f"vision response hit max_tokens ({MAX_TOKENS}) before completing"
            )

        text = _first_text(response)
        if text is None:
            raise PermanentError(
                f"vision response carried no text block (stop_reason={stop_reason!r})"
            )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PermanentError(f"vision response was not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise PermanentError(
                f"vision response was {type(payload).__name__}, expected an object"
            )
        return payload


# --------------------------------------------------------------------------
# request/response helpers
# --------------------------------------------------------------------------


def _prompt(field_names: list[str], page_count: int) -> str:
    listed = "\n".join(f"- {name}" for name in field_names)
    pages = f"{page_count} page{'s' if page_count != 1 else ''}"
    return (
        f"This document has {pages}. Transcribe the following values from it:\n"
        f"{listed}\n\n"
        "Return every name listed above, using an empty string for any you cannot "
        "read off the document."
    )


def _schema(field_names: list[str]) -> dict[str, Any]:
    """The response schema.

    All values are strings and absence is the empty string, rather than a nullable
    type. Two reasons: `anyOf`-with-null is one more schema feature to be right
    about for no gain, and "" and null would mean the same thing to `policy`
    anyway - it drops both.

    `additionalProperties: false` everywhere is required by the API's schema
    subset, and it happens to be the constraint that keeps a model from inventing a
    field name. `policy.sanitize` re-checks rather than relying on it: schema
    enforcement is the API's promise, and the field allowlist is ours.
    """
    return {
        "type": "object",
        "properties": {
            "fields": {
                "type": "object",
                "properties": {name: {"type": "string"} for name in field_names},
                "required": list(field_names),
                "additionalProperties": False,
            },
            "confidence": {
                "type": "object",
                "properties": {name: {"type": "number"} for name in field_names},
                "required": list(field_names),
                "additionalProperties": False,
            },
            "irregularities": {
                "type": "array",
                # The closed enum, so the API rejects an invented flag before it
                # reaches us. `policy` filters again on arrival.
                "items": {"type": "string", "enum": sorted(VISION_OBSERVABLE)},
            },
        },
        "required": ["fields", "confidence", "irregularities"],
        "additionalProperties": False,
    }


def _pdf_block(source_path: str | None) -> dict[str, Any]:
    """The document content block, or a clear refusal to proceed without one.

    Deliberately no text-layer fallback. Falling back to `PageText` would turn a
    vision call into a text call at the exact moment vision was asked for - and
    the caller would get a plausible-looking `VisionResult` with no way to know
    the model never saw the page.
    """
    if not source_path or not os.path.isfile(source_path):
        raise PermanentError(
            f"vision needs the source document; {source_path!r} is not a readable file"
        )
    if not source_path.lower().endswith(".pdf"):
        raise PermanentError(
            f"vision adapter handles PDFs; {os.path.basename(source_path)} is not one"
        )
    size = os.path.getsize(source_path)
    if size > MAX_PDF_BYTES:
        raise PermanentError(
            f"{os.path.basename(source_path)} is {size} bytes, over the "
            f"{MAX_PDF_BYTES}-byte vision limit"
        )
    with open(source_path, "rb") as fh:
        data = base64.standard_b64encode(fh.read()).decode("ascii")
    return {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": data},
    }


def _first_text(response: Any) -> str | None:
    for block in getattr(response, "content", ()) or ():
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", None)
            if isinstance(text, str):
                return text
    return None


def _result_from(payload: dict[str, Any], field_names: list[str]) -> VisionResult:
    fields = payload.get("fields")
    confidence = payload.get("confidence")
    irregularities = payload.get("irregularities")
    return VisionResult(
        fields=dict(fields) if isinstance(fields, dict) else {},
        confidence=dict(confidence) if isinstance(confidence, dict) else {},
        irregularities=list(irregularities) if isinstance(irregularities, list) else [],
    )


# Statuses worth another attempt. The SDK already retries these twice on its own;
# mapping them to TransientError lets the Runner's retry policy see them too, and
# - more importantly - keeps an auth or bad-request failure from being retried,
# which is the mistake a blanket TransientError would make.
_RETRY_STATUSES = frozenset({408, 409, 429})

_RETRY_CLASS_NAMES = frozenset({"APIConnectionError", "APITimeoutError"})


def _wrap(exc: Exception) -> Exception:
    """Classify an SDK exception as retryable or not.

    Duck-typed on `status_code` rather than isinstance-checked against the SDK's
    classes, because this has to work when the SDK is absent (every test) and
    because the status is the actual signal - the class hierarchy is just how the
    SDK spells it.
    """
    if isinstance(exc, (TransientError, PermanentError)):
        return exc
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and (status in _RETRY_STATUSES or status >= 500):
        return TransientError(f"vision request failed with status {status}: {exc}")
    if type(exc).__name__ in _RETRY_CLASS_NAMES or isinstance(
        exc, (TimeoutError, ConnectionError)
    ):
        return TransientError(f"vision request could not reach the API: {exc}")
    return PermanentError(f"vision request failed: {type(exc).__name__}: {exc}")
