"""`generate_field_hints`: request shape, response handling, error
classification. Every test injects a fake client - the same double shape
`tests/adapters/test_gemini_adapter.py` already uses for its own SDK boundary,
so this file never needs a real API key or network access.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from docintel.core.errors import PermanentError, TransientError
from docintel.generation.persona_agent import (
    _FIELD_NAMES,
    _PATTERN_TYPES,
    SYSTEM_PROMPT,
    generate_field_hints,
    write_draft,
)


def _pdf(tmp_path, name: str = "sample.pdf") -> str:
    path = tmp_path / name
    path.write_bytes(b"%PDF-1.4 stub bytes for a base64 round trip")
    return str(path)


class _FakeParsedMessage:
    def __init__(self, parsed_output, stop_reason: str = "end_turn"):
        self.parsed_output = parsed_output
        self.stop_reason = stop_reason
        self.stop_details = None


class _FakeMessages:
    def __init__(self, response=None, raises: Exception | None = None):
        self.response = response
        self.raises = raises
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises
        return self.response


class _FakeClient:
    def __init__(self, response=None, raises: Exception | None = None) -> None:
        self.messages = _FakeMessages(response=response, raises=raises)


def _valid_spec(model):
    return model(
        fields=[{"name": "total_printed", "type": "currency", "hint": "bottom right, next to Total"}],
        row_groups=[],
        notes="a real note",
    )


def _output_model():
    from docintel.generation.persona_agent import _build_output_model

    return _build_output_model(_FIELD_NAMES, _PATTERN_TYPES)


# -- happy path --------------------------------------------------------------


def test_a_valid_response_is_returned_as_parsed_output(tmp_path):
    model = _output_model()
    spec = _valid_spec(model)
    client = _FakeClient(response=_FakeParsedMessage(spec))

    result = generate_field_hints(_pdf(tmp_path), company_name="Acme Corp", client=client)

    assert result is spec


def test_the_pdf_is_sent_base64_encoded_as_a_document_block(tmp_path):
    model = _output_model()
    client = _FakeClient(response=_FakeParsedMessage(_valid_spec(model)))
    pdf_path = _pdf(tmp_path)
    with open(pdf_path, "rb") as fh:
        raw = fh.read()

    generate_field_hints(pdf_path, company_name="Acme Corp", client=client)

    call = client.messages.calls[0]
    content = call["messages"][0]["content"]
    doc_block = next(b for b in content if b["type"] == "document")
    assert doc_block["source"]["media_type"] == "application/pdf"
    assert base64.standard_b64decode(doc_block["source"]["data"]) == raw


def test_the_company_name_appears_in_the_prompt(tmp_path):
    model = _output_model()
    client = _FakeClient(response=_FakeParsedMessage(_valid_spec(model)))

    generate_field_hints(_pdf(tmp_path), company_name="Milwaukee Bearing & Machining", client=client)

    call = client.messages.calls[0]
    text_block = next(b for b in call["messages"][0]["content"] if b["type"] == "text")
    assert "Milwaukee Bearing & Machining" in text_block["text"]
    assert call["system"] == SYSTEM_PROMPT


def test_the_output_format_is_the_dynamic_pydantic_model(tmp_path):
    client = _FakeClient(response=_FakeParsedMessage(_valid_spec(_output_model())))

    generate_field_hints(_pdf(tmp_path), company_name="Acme Corp", client=client)

    call = client.messages.calls[0]
    assert call["output_format"].__name__ == "GeneratedFieldHints"


def test_the_model_defaults_to_opus_5(tmp_path):
    client = _FakeClient(response=_FakeParsedMessage(_valid_spec(_output_model())))

    generate_field_hints(_pdf(tmp_path), company_name="Acme Corp", client=client)

    assert client.messages.calls[0]["model"] == "claude-opus-5"


# -- refusal & missing output -------------------------------------------------


def test_a_refusal_is_a_permanent_error_not_a_bare_none(tmp_path):
    client = _FakeClient(response=_FakeParsedMessage(None, stop_reason="refusal"))

    with pytest.raises(PermanentError, match="declined"):
        generate_field_hints(_pdf(tmp_path), company_name="Acme Corp", client=client)


def test_no_parsed_output_without_a_refusal_is_still_a_permanent_error(tmp_path):
    client = _FakeClient(response=_FakeParsedMessage(None, stop_reason="max_tokens"))

    with pytest.raises(PermanentError, match="did not return a parseable result"):
        generate_field_hints(_pdf(tmp_path), company_name="Acme Corp", client=client)


# -- error classification -----------------------------------------------------


def _response(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))


@pytest.mark.parametrize("status", [408, 409, 429, 500, 503])
def test_retryable_statuses_become_transient_errors(tmp_path, status):
    import anthropic

    client = _FakeClient(
        raises=anthropic.APIStatusError("boom", response=_response(status), body=None)
    )
    with pytest.raises(TransientError):
        generate_field_hints(_pdf(tmp_path), company_name="Acme Corp", client=client)


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_client_errors_are_permanent(tmp_path, status):
    import anthropic

    client = _FakeClient(
        raises=anthropic.APIStatusError("bad request", response=_response(status), body=None)
    )
    with pytest.raises(PermanentError):
        generate_field_hints(_pdf(tmp_path), company_name="Acme Corp", client=client)


def test_rate_limit_error_is_transient(tmp_path):
    import anthropic

    client = _FakeClient(
        raises=anthropic.RateLimitError("rate limited", response=_response(429), body=None)
    )
    with pytest.raises(TransientError, match="rate limited"):
        generate_field_hints(_pdf(tmp_path), company_name="Acme Corp", client=client)


def test_connection_error_is_transient(tmp_path):
    import anthropic

    client = _FakeClient(
        raises=anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    )
    with pytest.raises(TransientError, match="could not reach"):
        generate_field_hints(_pdf(tmp_path), company_name="Acme Corp", client=client)


def test_a_missing_source_file_is_a_permanent_error(tmp_path):
    client = _FakeClient(response=_FakeParsedMessage(_valid_spec(_output_model())))
    with pytest.raises(PermanentError, match="not a readable file"):
        generate_field_hints(str(tmp_path / "nope.pdf"), company_name="Acme Corp", client=client)
    assert client.messages.calls == []


# -- write_draft ---------------------------------------------------------


def test_write_draft_labels_itself_unreviewed(tmp_path):
    spec = _valid_spec(_output_model())
    out = tmp_path / "acme.hints.json"

    write_draft(spec, str(out), company_name="Acme Corp", source_pdf="/x/acme_invoice.pdf")

    payload = json.loads(out.read_text())
    assert "draft" in payload["status"].lower()
    assert "not reviewed" in payload["status"].lower()
    assert payload["company_name"] == "Acme Corp"
    assert payload["source_pdf"] == "acme_invoice.pdf"
    assert payload["spec"]["fields"][0]["name"] == "total_printed"
    assert "total_printed" in payload["field_vocabulary_version"]


def test_write_draft_creates_missing_parent_directories(tmp_path):
    spec = _valid_spec(_output_model())
    out = tmp_path / "nested" / "dir" / "acme.hints.json"

    write_draft(spec, str(out), company_name="Acme Corp", source_pdf="acme.pdf")

    assert out.exists()
