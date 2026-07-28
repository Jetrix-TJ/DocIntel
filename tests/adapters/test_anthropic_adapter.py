"""AnthropicVision: request shape, response handling, error classification.

Every test injects a fake client. The `anthropic` SDK is not installed here and no
key exists, so what these tests pin is the request we build and what we do with a
response - NOT that the SDK accepts the request. That remains unverified until an
operator runs `--vision record` against a live key.
"""

from __future__ import annotations

import base64
import json

import pytest

from docintel.adapters.vision.anthropic_adapter import (
    FALLBACK_BETA,
    MAX_PDF_BYTES,
    MAX_TOKENS,
    MODEL,
    AnthropicVision,
)
from docintel.core.errors import PermanentError, TransientError
from docintel.core.models import PageText

FIELDS = ["vendor_name", "total_printed"]


# -- doubles ---------------------------------------------------------------


class _Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, payload: object = None, stop_reason: str = "end_turn",
                 content: list | None = None, stop_details: object = None) -> None:
        self.stop_reason = stop_reason
        self.stop_details = stop_details
        if content is not None:
            self.content = content
        else:
            body = payload if isinstance(payload, str) else json.dumps(payload)
            self.content = [_Block(body)]


class _Details:
    def __init__(self, category: str) -> None:
        self.category = category


class FakeClient:
    """Records the request and returns a canned response."""

    def __init__(self, response=None, raises: Exception | None = None) -> None:
        self.response = response
        self.raises = raises
        self.requests: list[dict] = []
        self.beta_requests: list[dict] = []
        self.beta = _Beta(self)
        self.messages = _Messages(self, self.requests)

    def _answer(self):
        if self.raises is not None:
            raise self.raises
        return self.response


class _Messages:
    def __init__(self, owner: FakeClient, sink: list[dict]) -> None:
        self._owner = owner
        self._sink = sink

    def create(self, **kwargs):
        self._sink.append(kwargs)
        return self._owner._answer()


class _Beta:
    def __init__(self, owner: FakeClient) -> None:
        self.messages = _Messages(owner, owner.beta_requests)


def _pdf(tmp_path, name: str = "invoice.pdf", body: bytes = b"%PDF-1.4 body") -> str:
    path = tmp_path / name
    path.write_bytes(body)
    return str(path)


def _pages(n: int = 2) -> tuple[PageText, ...]:
    return tuple(
        PageText(page_number=i + 1, words=(), width=612.0, height=792.0, source="native")
        for i in range(n)
    )


_DEFAULT_FIELDS = {"vendor_name": "ACME", "total_printed": "1,177.70"}
_DEFAULT_CONFIDENCE = {"vendor_name": 0.9, "total_printed": 0.8}


def _ok(fields: dict[str, str] | None = None, confidence=None, irregularities=None):
    return _Response({
        "fields": _DEFAULT_FIELDS if fields is None else fields,
        "confidence": _DEFAULT_CONFIDENCE if confidence is None else confidence,
        "irregularities": irregularities or [],
    })


# -- happy path ------------------------------------------------------------


def test_a_structured_response_becomes_a_vision_result(tmp_path):
    client = FakeClient(_ok())
    v = AnthropicVision(client=client)

    result = v.extract(_pages(), FIELDS, source_path=_pdf(tmp_path))

    assert result.fields == {"vendor_name": "ACME", "total_printed": "1,177.70"}
    assert result.confidence["total_printed"] == pytest.approx(0.8)


def test_an_empty_transcription_is_absence_not_a_value(tmp_path):
    """The prompt tells the model to return "" for a field it cannot read. That has
    to become a missing key, not a field whose value is the empty string - the
    latter would satisfy a required-field check with nothing in it."""
    client = FakeClient(_ok(fields={"vendor_name": "ACME", "total_printed": "   "}))
    v = AnthropicVision(client=client)

    result = v.extract(_pages(), FIELDS, source_path=_pdf(tmp_path))

    assert set(result.fields) == {"vendor_name"}
    assert "total_printed" not in result.confidence


def test_no_requested_fields_means_no_api_call(tmp_path):
    client = FakeClient(_ok())
    assert AnthropicVision(client=client).extract(_pages(), []) == type(
        AnthropicVision(client=client).extract(_pages(), [])
    )()
    assert client.requests == [] and client.beta_requests == []


# -- request shape ---------------------------------------------------------


def test_the_pdf_is_sent_as_a_base64_document_block_before_the_prompt(tmp_path):
    body = b"%PDF-1.4 the actual bytes"
    client = FakeClient(_ok())
    AnthropicVision(client=client).extract(
        _pages(), FIELDS, source_path=_pdf(tmp_path, body=body)
    )

    content = client.beta_requests[0]["messages"][0]["content"]
    assert content[0]["type"] == "document"
    assert content[0]["source"]["media_type"] == "application/pdf"
    assert content[0]["source"]["data"] == base64.standard_b64encode(body).decode()
    assert content[1]["type"] == "text"


def test_base64_payload_carries_no_newlines(tmp_path):
    """The API rejects a base64 string containing newlines, and a long document is
    exactly where a wrapping encoder would bite."""
    client = FakeClient(_ok())
    AnthropicVision(client=client).extract(
        _pages(), FIELDS, source_path=_pdf(tmp_path, body=b"%PDF" + b"x" * 5000)
    )
    data = client.beta_requests[0]["messages"][0]["content"][0]["source"]["data"]
    assert "\n" not in data


def test_the_request_names_the_model_and_leaves_room_for_thinking(tmp_path):
    client = FakeClient(_ok())
    AnthropicVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))

    request = client.beta_requests[0]
    assert request["model"] == MODEL
    assert request["max_tokens"] == MAX_TOKENS
    assert request["thinking"] == {"type": "adaptive"}
    assert request["output_config"]["effort"] == "high"


def test_the_schema_lists_exactly_the_requested_fields_and_forbids_others(tmp_path):
    client = FakeClient(_ok())
    AnthropicVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))

    schema = client.beta_requests[0]["output_config"]["format"]["schema"]
    assert schema["properties"]["fields"]["required"] == FIELDS
    assert schema["properties"]["fields"]["additionalProperties"] is False
    assert schema["additionalProperties"] is False


def test_the_schema_constrains_irregularities_to_the_observable_enum(tmp_path):
    """The API rejecting an invented flag is the first line of defence; policy
    filtering it is the second. This asserts the first exists."""
    client = FakeClient(_ok())
    AnthropicVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))

    items = client.beta_requests[0]["output_config"]["format"]["schema"]["properties"][
        "irregularities"
    ]["items"]
    assert items["enum"] == ["handwriting_detected", "high_skew"]


def test_the_system_prompt_is_cacheable_and_forbids_arithmetic(tmp_path):
    client = FakeClient(_ok())
    AnthropicVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))

    system = client.beta_requests[0]["system"][0]
    assert system["cache_control"] == {"type": "ephemeral"}
    assert "Do NOT do arithmetic" in system["text"]
    assert "which number should be paid" in system["text"]


def test_refusal_fallbacks_use_the_beta_endpoint_by_default(tmp_path):
    client = FakeClient(_ok())
    AnthropicVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))

    assert client.requests == []
    assert client.beta_requests[0]["fallbacks"] == "default"
    assert client.beta_requests[0]["betas"] == [FALLBACK_BETA]


def test_fallbacks_can_be_turned_off_and_then_the_plain_endpoint_is_used(tmp_path):
    client = FakeClient(_ok())
    AnthropicVision(client=client, fallbacks=False).extract(
        _pages(), FIELDS, source_path=_pdf(tmp_path)
    )

    assert client.beta_requests == []
    assert "fallbacks" not in client.requests[0]


# -- source guards ---------------------------------------------------------


def test_a_missing_source_refuses_rather_than_falling_back_to_page_text(tmp_path):
    """The whole reason the port carries a source path. A text-layer fallback would
    return a plausible VisionResult from a model that never saw the page."""
    client = FakeClient(_ok())
    with pytest.raises(PermanentError, match="needs the source document"):
        AnthropicVision(client=client).extract(_pages(), FIELDS)
    assert client.beta_requests == []


def test_a_non_pdf_source_is_refused(tmp_path):
    path = tmp_path / "scan.png"
    path.write_bytes(b"\x89PNG")
    with pytest.raises(PermanentError, match="handles PDFs"):
        AnthropicVision(client=FakeClient(_ok())).extract(
            _pages(), FIELDS, source_path=str(path)
        )


def test_an_oversized_pdf_is_refused_before_it_is_read(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "docintel.adapters.vision.anthropic_adapter.MAX_PDF_BYTES", 8
    )
    with pytest.raises(PermanentError, match="over the"):
        AnthropicVision(client=FakeClient(_ok())).extract(
            _pages(), FIELDS, source_path=_pdf(tmp_path, body=b"%PDF-1.4 too long")
        )


def test_the_size_ceiling_leaves_headroom_under_the_api_request_limit():
    """base64 inflates by 4/3, and the API's ceiling is 32 MB per request."""
    assert MAX_PDF_BYTES * 4 / 3 < 32 * 1024 * 1024


# -- response handling ----------------------------------------------------


def test_a_refusal_is_reported_as_a_refusal_not_a_parse_error(tmp_path):
    """A refusal returns HTTP 200 with an empty content list. Reading content[0]
    first would report a safety decline as malformed JSON."""
    client = FakeClient(_Response(content=[], stop_reason="refusal",
                                  stop_details=_Details("cyber")))
    with pytest.raises(PermanentError, match="declined by safety classifiers"):
        AnthropicVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))


def test_hitting_max_tokens_is_transient_so_the_runner_may_retry(tmp_path):
    client = FakeClient(_Response(content=[], stop_reason="max_tokens"))
    with pytest.raises(TransientError, match="max_tokens"):
        AnthropicVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))


def test_a_response_with_no_text_block_fails_clearly(tmp_path):
    client = FakeClient(_Response(content=[]))
    with pytest.raises(PermanentError, match="no text block"):
        AnthropicVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))


def test_non_json_text_fails_clearly(tmp_path):
    client = FakeClient(_Response("not json at all"))
    with pytest.raises(PermanentError, match="not valid JSON"):
        AnthropicVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))


def test_a_json_array_instead_of_an_object_fails_clearly(tmp_path):
    client = FakeClient(_Response([1, 2, 3]))
    with pytest.raises(PermanentError, match="expected an object"):
        AnthropicVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))


def test_a_response_missing_the_confidence_object_still_yields_fields(tmp_path):
    client = FakeClient(_Response({"fields": {"vendor_name": "ACME"}}))
    result = AnthropicVision(client=client).extract(
        _pages(), FIELDS, source_path=_pdf(tmp_path)
    )
    assert result.fields == {"vendor_name": "ACME"}
    assert result.confidence["vendor_name"] == pytest.approx(0.50)


def test_a_model_invented_field_is_dropped_even_though_the_schema_forbade_it(tmp_path):
    """Defence in depth: the schema should have prevented this, and we do not rely
    on it having done so."""
    client = FakeClient(_Response({
        "fields": {"vendor_name": "ACME", "amount_payable": "0.01", "notes": "hi"},
        "confidence": {"vendor_name": 0.9},
        "irregularities": ["flattened_annotations"],
    }))
    result = AnthropicVision(client=client).extract(
        _pages(), FIELDS, source_path=_pdf(tmp_path)
    )
    assert set(result.fields) == {"vendor_name"}
    assert result.irregularities == []


# -- error classification -------------------------------------------------


class _Status(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class APIConnectionError(Exception):
    """Named to match the SDK class, since classification is name/duck based."""


@pytest.mark.parametrize("status", [408, 409, 429, 500, 503, 529])
def test_retryable_statuses_become_transient_errors(tmp_path, status):
    client = FakeClient(raises=_Status(status))
    with pytest.raises(TransientError):
        AnthropicVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413])
def test_client_errors_are_permanent_so_they_are_not_retried(tmp_path, status):
    """Retrying a bad key or a malformed request just burns the retry budget and
    delays the dead letter."""
    client = FakeClient(raises=_Status(status))
    with pytest.raises(PermanentError):
        AnthropicVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))


def test_a_connection_failure_is_transient(tmp_path):
    client = FakeClient(raises=APIConnectionError("no route"))
    with pytest.raises(TransientError, match="could not reach"):
        AnthropicVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))


def test_an_unclassifiable_failure_is_permanent(tmp_path):
    client = FakeClient(raises=ValueError("something else"))
    with pytest.raises(PermanentError, match="ValueError"):
        AnthropicVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))


def test_importing_the_module_does_not_require_the_sdk():
    """`--vision fake` and `--vision cassette` must work without the extra installed."""
    import importlib
    import sys

    assert "anthropic" not in sys.modules
    importlib.reload(
        importlib.import_module("docintel.adapters.vision.anthropic_adapter")
    )
    assert "anthropic" not in sys.modules
