"""GeminiVision: request shape, response handling, error classification.

Every test injects a fake `client` double, mirroring `test_anthropic_adapter.py`'s
approach. One real difference from that file: Gemini's schema/document objects
(`types.Schema`, `types.Part`) are native SDK objects, not plain dicts, so
`_send`/`_schema` import `google.genai.types` unconditionally rather than only
inside a client-construction path. That means every test here except
`test_importing_the_module_does_not_require_the_sdk` needs the `google-genai`
package installed (the `vision` extra) - the same requirement `--vision live`/
`--vision record` already have. `--vision fake`/`--vision cassette` never call
`.extract()` at all, so they stay SDK-free; that is what the import-only test
below pins.

What's verified here is the request we build and what we do with a response -
NOT that Google's SDK accepts that request forever. That remains unverified
until an operator runs `--vision record` against a live key.
"""

from __future__ import annotations

import json

import pytest

from docintel.adapters.vision.gemini_adapter import (
    MAX_PAGES,
    MAX_PDF_BYTES,
    MODEL,
    GeminiVision,
)
from docintel.core.errors import PermanentError, TransientError
from docintel.core.models import PageText

FIELDS = ["vendor_name", "total_printed"]


# -- doubles ---------------------------------------------------------------


class _Response:
    def __init__(self, text: str | None) -> None:
        self.text = text


class _Models:
    def __init__(self, owner: FakeClient) -> None:
        self._owner = owner

    def generate_content(self, **kwargs):
        self._owner.calls.append(kwargs)
        if self._owner.raises is not None:
            raise self._owner.raises
        return self._owner.response


class FakeClient:
    """Records the request and returns a canned response."""

    def __init__(self, response=None, raises: Exception | None = None) -> None:
        self.response = response
        self.raises = raises
        self.calls: list[dict] = []
        self.models = _Models(self)


def _pdf(tmp_path, name: str = "invoice.pdf", pages: int = 1) -> str:
    """A real, parseable PDF - `_read_pdf` opens it with `pypdf` to count
    pages, unlike the Anthropic adapter, which never parses the bytes it
    sends. A hand-rolled dummy byte string fails that parse."""
    import pypdf

    writer = pypdf.PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    path = tmp_path / name
    with open(path, "wb") as fh:
        writer.write(fh)
    return str(path)


def _pages(n: int = 2) -> tuple[PageText, ...]:
    return tuple(
        PageText(page_number=i + 1, words=(), width=612.0, height=792.0, source="native")
        for i in range(n)
    )


_DEFAULT_FIELDS = {"vendor_name": "ACME", "total_printed": "1,177.70"}
_DEFAULT_CONFIDENCE = {"vendor_name": 0.9, "total_printed": 0.8}


def _ok(fields: dict[str, str] | None = None, confidence=None, irregularities=None) -> _Response:
    payload = {
        "fields": _DEFAULT_FIELDS if fields is None else fields,
        "confidence": _DEFAULT_CONFIDENCE if confidence is None else confidence,
        "irregularities": irregularities or [],
    }
    return _Response(json.dumps(payload))


# -- happy path --------------------------------------------------------------


def test_a_structured_response_becomes_a_vision_result(tmp_path):
    client = FakeClient(_ok())
    v = GeminiVision(client=client)

    result = v.extract(_pages(), FIELDS, source_path=_pdf(tmp_path))

    assert result.fields == {"vendor_name": "ACME", "total_printed": "1,177.70"}
    assert result.confidence["total_printed"] == pytest.approx(0.8)


def test_an_empty_transcription_is_absence_not_a_value(tmp_path):
    """The prompt tells the model to return "" for a field it cannot read. That has
    to become a missing key, not a field whose value is the empty string - the
    latter would satisfy a required-field check with nothing in it."""
    client = FakeClient(_ok(fields={"vendor_name": "ACME", "total_printed": "   "}))
    v = GeminiVision(client=client)

    result = v.extract(_pages(), FIELDS, source_path=_pdf(tmp_path))

    assert set(result.fields) == {"vendor_name"}
    assert "total_printed" not in result.confidence


def test_no_requested_fields_means_no_api_call(tmp_path):
    client = FakeClient(_ok())
    result = GeminiVision(client=client).extract(_pages(), [])

    assert result.fields == {} and result.confidence == {} and result.irregularities == []
    assert client.calls == []


# -- request shape -----------------------------------------------------------


def test_the_pdf_bytes_are_sent_as_a_document_part(tmp_path):
    path = _pdf(tmp_path)
    with open(path, "rb") as fh:
        body = fh.read()
    client = FakeClient(_ok())
    GeminiVision(client=client).extract(_pages(), FIELDS, source_path=path)

    document = client.calls[0]["contents"][0]
    assert document.inline_data.data == body
    assert document.inline_data.mime_type == "application/pdf"


def test_the_prompt_lists_every_requested_field(tmp_path):
    """Page count in the prompt comes from the PDF itself (via pypdf), not
    from the `pages` tuple argument - that tuple is PageText data the
    Anthropic adapter's callers pass along, unused here for counting."""
    client = FakeClient(_ok())
    GeminiVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path, pages=3))

    prompt = client.calls[0]["contents"][1]
    assert "vendor_name" in prompt
    assert "total_printed" in prompt
    assert "3 pages" in prompt


def test_a_field_hint_is_appended_inline_next_to_its_field_name(tmp_path):
    client = FakeClient(_ok())
    hints = {"vendor_name": "top-left, near the logo"}
    GeminiVision(client=client, field_hints=hints).extract(
        _pages(), FIELDS, source_path=_pdf(tmp_path)
    )

    prompt = client.calls[0]["contents"][1]
    assert "vendor_name: top-left, near the logo" in prompt
    # No hint was given for total_printed - it still appears, just bare.
    assert "  - total_printed\n" in prompt or prompt.endswith("- total_printed")


def test_the_request_names_the_model(tmp_path):
    client = FakeClient(_ok())
    GeminiVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))

    assert client.calls[0]["model"] == MODEL


def test_the_schema_requires_exactly_the_requested_fields(tmp_path):
    client = FakeClient(_ok())
    GeminiVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))

    schema = client.calls[0]["config"].response_schema
    assert schema.properties["fields"].required == FIELDS
    assert set(schema.properties["fields"].properties) == set(FIELDS)


def test_the_schema_constrains_irregularities_to_the_observable_enum(tmp_path):
    client = FakeClient(_ok())
    GeminiVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))

    schema = client.calls[0]["config"].response_schema
    assert schema.properties["irregularities"].items.enum == ["handwriting_detected", "high_skew"]


def test_temperature_is_zero_for_deterministic_transcription(tmp_path):
    client = FakeClient(_ok())
    GeminiVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))

    assert client.calls[0]["config"].temperature == 0.0


# -- source guards -------------------------------------------------------


def test_a_missing_source_refuses_rather_than_falling_back_to_page_text(tmp_path):
    client = FakeClient(_ok())
    with pytest.raises(PermanentError, match="needs the source document"):
        GeminiVision(client=client).extract(_pages(), FIELDS)
    assert client.calls == []


def test_a_non_pdf_source_is_refused(tmp_path):
    path = tmp_path / "scan.png"
    path.write_bytes(b"\x89PNG")
    with pytest.raises(PermanentError, match="handles PDFs"):
        GeminiVision(client=FakeClient(_ok())).extract(_pages(), FIELDS, source_path=str(path))


def test_an_oversized_pdf_is_refused_before_it_is_read(tmp_path, monkeypatch):
    """The size check runs before pypdf ever opens the file, so a raw byte
    string (not a structurally valid PDF) is enough to prove it."""
    monkeypatch.setattr("docintel.adapters.vision.gemini_adapter.MAX_PDF_BYTES", 8)
    path = tmp_path / "invoice.pdf"
    path.write_bytes(b"%PDF-1.4 too long")
    with pytest.raises(PermanentError, match="over the"):
        GeminiVision(client=FakeClient(_ok())).extract(_pages(), FIELDS, source_path=str(path))


def _multi_page_pdf(tmp_path, pages: int) -> str:
    import pypdf

    writer = pypdf.PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    path = tmp_path / "multi.pdf"
    with open(path, "wb") as fh:
        writer.write(fh)
    return str(path)


def test_a_document_over_max_pages_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr("docintel.adapters.vision.gemini_adapter.MAX_PAGES", 2)
    with pytest.raises(PermanentError, match="3 pages, over the 2-page guard"):
        GeminiVision(client=FakeClient(_ok())).extract(
            _pages(), FIELDS, source_path=_multi_page_pdf(tmp_path, 3)
        )


def test_the_page_guard_reflects_the_documented_real_world_ceiling():
    """MAX_PAGES was raised from 10 to 30 after a real 24-document sample
    found legitimate telecom invoices running 14-18 pages - this pins that
    the guard stays above that evidence rather than silently drifting back
    down."""
    assert MAX_PAGES >= 20


def test_the_byte_ceiling_is_the_inline_part_limit_not_a_guess():
    assert MAX_PDF_BYTES == 15 * 1024 * 1024


# -- response handling ----------------------------------------------------


def test_a_response_with_no_text_fails_clearly(tmp_path):
    client = FakeClient(_Response(None))
    with pytest.raises(PermanentError, match="no text"):
        GeminiVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))


def test_non_json_text_fails_clearly(tmp_path):
    client = FakeClient(_Response("not json at all"))
    with pytest.raises(PermanentError, match="not valid JSON"):
        GeminiVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))


def test_a_json_array_instead_of_an_object_fails_clearly(tmp_path):
    client = FakeClient(_Response(json.dumps([1, 2, 3])))
    with pytest.raises(TypeError, match="expected an object"):
        GeminiVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))


def test_a_response_missing_the_confidence_object_still_yields_fields(tmp_path):
    client = FakeClient(_Response(json.dumps({"fields": {"vendor_name": "ACME"}})))
    result = GeminiVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))

    assert result.fields == {"vendor_name": "ACME"}
    assert result.confidence["vendor_name"] == pytest.approx(0.50)


def test_a_model_invented_field_is_dropped_even_though_the_schema_forbade_it(tmp_path):
    """Defence in depth: Gemini's schema subset has no `additionalProperties:
    false`, unlike Anthropic's, which makes this policy-level check load-
    bearing rather than a belt-and-braces second check."""
    client = FakeClient(_Response(json.dumps({
        "fields": {"vendor_name": "ACME", "amount_payable": "0.01", "notes": "hi"},
        "confidence": {"vendor_name": 0.9},
        "irregularities": ["flattened_annotations"],
    })))
    result = GeminiVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))

    assert set(result.fields) == {"vendor_name"}
    assert result.irregularities == []


# -- error classification -------------------------------------------------


class _Status(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


@pytest.mark.parametrize("status", [408, 409, 429, 500, 503])
def test_retryable_statuses_become_transient_errors(tmp_path, status):
    client = FakeClient(raises=_Status(status))
    with pytest.raises(TransientError):
        GeminiVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413])
def test_client_errors_are_permanent_so_they_are_not_retried(tmp_path, status):
    client = FakeClient(raises=_Status(status))
    with pytest.raises(PermanentError):
        GeminiVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))


def test_a_connection_failure_is_transient(tmp_path):
    client = FakeClient(raises=ConnectionError("no route"))
    with pytest.raises(TransientError, match="could not reach"):
        GeminiVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))


def test_an_unclassifiable_failure_is_permanent(tmp_path):
    client = FakeClient(raises=ValueError("something else"))
    with pytest.raises(PermanentError, match="ValueError"):
        GeminiVision(client=client).extract(_pages(), FIELDS, source_path=_pdf(tmp_path))


def test_importing_the_module_does_not_require_the_sdk():
    """`--vision fake` and `--vision cassette` must work without the extra
    installed - they never call `.extract()`, so importing the module alone
    must not import `google.genai`.

    Run in a fresh subprocess rather than in-process: other tests in this
    file legitimately exercise `.extract()`, which does import `google.genai`
    - checking `sys.modules` here would just see that contamination rather
    than proving anything about a bare import.
    """
    import subprocess
    import sys

    code = (
        "import sys; "
        "import docintel.adapters.vision.gemini_adapter; "
        "assert 'google.genai' not in sys.modules, sorted(sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd="src",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
