"""Generate a first-draft field-hint spec for a brand-new company, from one
real document - the automated half of vendor onboarding Anamul asked for at
the Aug 18 standup: "we are invoking cloud... rather than we will do it in a
server... so in a server we will send the request that okay this is the PDF
and for this PDF we need to create the classification rules or the personas."

**What this produces, and what it deliberately does not.** The output is a
field-hint spec - `{name, type, hint}` per field, `hint` a one-sentence prose
description of where a human would look, never the anchor/region regex a real
Stage 5a persona selector needs. This is not a scope cut; it is the one thing
this session's own evidence says NOT to attempt: an earlier blind-agent
exercise asked an agent to author real anchor/region selectors from one PDF
and scored 194/283 against the shipped personas' 238/283, with the losses
almost entirely geometry ("address block wholly wrong"). A follow-up ablation
found deleting every anchor/region from a Gemini prompt moved 1 value in 102 -
the geometry a blind pass gets wrong was never load-bearing on that path. So
this generates exactly the part that generalizes (field list, type, a
sentence) and leaves selector geometry to a human, later, informed by this
draft.

**Where the output actually plugs in.** The `{name: hint}` shape this returns
is the exact shape `adapters.vision.hints.hints_for_persona` already builds
from a real persona for Stage 5b's `field_hints` - so a reviewed draft can
become a brand-new company's *vision-fallback* guidance immediately (Stage 5b
already runs unconditionally for a company with no persona at all), while a
human separately authors the real Stage 5a selectors at their own pace. The
company is live on the (slower, per-document-cost) vision path from day one,
cheap Stage 5a is a deliberate follow-up.

**The review gate is not optional and is not implemented by this module.**
This module returns a Python object and, via `write_draft`, a JSON file on
disk - both loud about being unreviewed. Nothing here writes into a pack's
`personas/` directory, calls `registry.PACK_MODULES`, or is on any path the
real pipeline (`pipeline.stages.build_pipeline`) executes. Promoting a draft
into something the pipeline actually uses is a separate, human decision, by
design - both JA and Anamul were explicit in the standup that this must never
skip a human review step.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Literal

from pydantic import BaseModel, Field

from docintel.core.errors import PermanentError, TransientError
from docintel.grammar.patterns import NAMED as PATTERN_NAMED
from docintel.scorecard import CHECKED_FIELDS

MODEL = "claude-opus-5"

# The field vocabulary a draft may choose from - the same real, live registry
# `scorecard.py` uses to decide what the eval layer measures, not a second
# copy of it. A generated field name outside this set would describe
# something no existing tooling knows how to score or compare, so the schema
# itself makes that choice unavailable rather than relying on the model to
# remember a rule.
_FIELD_NAMES: tuple[str, ...] = tuple(sorted(CHECKED_FIELDS))

# The closed pattern/type vocabulary the grammar's own coercer understands
# (`grammar.patterns.NAMED`) - reused directly so a generated `type` is
# guaranteed coercible the same way a hand-authored selector's `pattern`
# already is, with no separate list to keep in sync.
_PATTERN_TYPES: tuple[str, ...] = tuple(sorted(PATTERN_NAMED))

_MAX_TOKENS = 8192

SYSTEM_PROMPT = """\
You are writing extraction hints for ONE company's documents, from a single \
representative sample. Another system will later process OTHER documents \
from this same company using only what you write now - you will never see \
those documents, and there is no answer key to check against.

Describe what this document contains so a later reader - who sees a \
DIFFERENT document with the same layout - can find each value.

RULES THAT DECIDE QUALITY

1. NEVER put the VALUE in a hint. "the invoice number, printed top right \
beside the words Invoice No." is a hint. "the invoice number, 37525600" is \
an answer, and it will be wrong on every other document this company sends.
2. Where two fields look alike, say how to tell them apart - vendor address \
vs. remit-to address, bill-to vs. ship-to, invoice date vs. due date, unit \
price vs. extended amount. These are what get confused.
3. Each hint is ONE sentence telling a reader who can see the whole page how \
to recognise that value: the label it sits beside, the block it belongs to, \
what distinguishes it from a similar value elsewhere on the page.
4. Omit a field rather than guess. A field you leave out costs one value. A \
field you describe wrongly costs every document this company sends.
5. `name` must come from the fixed field list you are given. Do not invent a \
name close to one on the list - if the document prints something with no \
name on the list, leave it out entirely.
6. `type` must be one of the fixed pattern kinds you are given. \
`currency_signed` requires an explicit + or - on every value; use plain \
`currency` for anything that ever prints unsigned.
7. For any repeating table: give it a short snake_case name, describe where \
it starts and what its columns are called IN PRINT, name each column \
(short, descriptive, snake_case - there is no fixed list for these), and \
say whether a subtotal/total row should be excluded.
8. In `notes`, record anything a later reader should know: negative \
amounts or credits, multiple tables, scans vs. clean digital copies, \
anything unusual about how this company formats things.

You are never shown, and must never guess at, whether your output is \
correct. A field described wrongly and a field left out are not the same \
mistake - prefer leaving it out.
"""

_PROMPT_TEMPLATE = """\
Company: {company_name}

The fixed field names you may use for `fields[].name` - choose only from \
this list, do not invent one:
{field_names}

The fixed pattern kinds for `type` (on both `fields[]` and table columns):
{pattern_types}

Describe every field this document actually prints that matches one of the \
names above, plus any repeating table, following the rules in the system \
prompt.
"""


def _build_output_model(field_names: tuple[str, ...], pattern_types: tuple[str, ...]) -> type[BaseModel]:
    """Pydantic models built at call time, not import time - the field
    vocabulary is a live tuple (`scorecard.CHECKED_FIELDS`), so a class body
    frozen at import time would silently drift from it the moment a new
    field name is registered elsewhere in this codebase.
    """
    field_name_type = Literal[field_names]  # type: ignore[valid-type]
    pattern_type_type = Literal[pattern_types]  # type: ignore[valid-type]

    class GeneratedField(BaseModel):
        name: field_name_type  # type: ignore[valid-type]
        type: pattern_type_type  # type: ignore[valid-type]
        hint: str = Field(
            description="One sentence: where a human would look for this "
            "value on the page. Never the value itself."
        )

    class GeneratedColumn(BaseModel):
        name: str = Field(description="Short, descriptive, snake_case.")
        type: pattern_type_type  # type: ignore[valid-type]

    class GeneratedRowGroup(BaseModel):
        name: str = Field(description="Short, descriptive, snake_case name for this table.")
        hint: str = Field(description="Where the table starts, what its columns are called in print.")
        columns: list[GeneratedColumn]
        stop_at_subtotal: bool = Field(
            description="True if a subtotal/total row should be excluded from the rows."
        )

    class GeneratedFieldHints(BaseModel):
        """The output shape. `fields` maps directly onto
        `adapters.vision.hints.hints_for_persona`'s own `{name: hint}` return
        shape once flattened - see this module's docstring."""

        fields: list[GeneratedField]
        row_groups: list[GeneratedRowGroup]
        notes: str

    return GeneratedFieldHints


def _read_pdf_base64(pdf_path: str) -> str:
    if not os.path.isfile(pdf_path):
        raise PermanentError(f"{pdf_path!r} is not a readable file")
    with open(pdf_path, "rb") as fh:
        return base64.standard_b64encode(fh.read()).decode("ascii")


def generate_field_hints(
    pdf_path: str,
    *,
    company_name: str,
    client: Any | None = None,
    model: str = MODEL,
) -> BaseModel:
    """One document in, one draft hint spec out. Raises `PermanentError`/
    `TransientError` - never a bare SDK exception - so a caller (the
    `generate-persona` CLI command) can apply this project's usual
    retry/report discipline without importing `anthropic`'s own exception
    types.

    `client`, if given, must already be constructed (an `anthropic.Anthropic`
    or a test double with a `.messages.parse` method) - this function never
    reads credentials itself, the same "no hidden side effect at import time"
    discipline `gemini_adapter.py` already follows.
    """
    import anthropic

    if client is None:
        client = anthropic.Anthropic()

    pdf_b64 = _read_pdf_base64(pdf_path)
    output_model = _build_output_model(_FIELD_NAMES, _PATTERN_TYPES)
    prompt = _PROMPT_TEMPLATE.format(
        company_name=company_name,
        field_names="\n".join(f"  - {n}" for n in _FIELD_NAMES),
        pattern_types="\n".join(f"  - {t}" for t in _PATTERN_TYPES),
    )

    try:
        response = client.messages.parse(
            model=model,
            max_tokens=_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
            output_format=output_model,
        )
    except anthropic.RateLimitError as exc:
        raise TransientError(f"rate limited generating hints for {company_name!r}: {exc}") from exc
    except anthropic.APIConnectionError as exc:
        raise TransientError(f"could not reach the API generating hints for {company_name!r}: {exc}") from exc
    except anthropic.APIStatusError as exc:
        status = getattr(exc, "status_code", None)
        if isinstance(status, int) and (status in (408, 409, 429) or status >= 500):
            raise TransientError(f"generation request failed with status {status}: {exc}") from exc
        raise PermanentError(f"generation request failed with status {status}: {exc}") from exc

    if response.stop_reason == "refusal":
        raise PermanentError(
            f"the model declined to generate hints for {company_name!r} "
            f"(stop_details={getattr(response, 'stop_details', None)})"
        )
    if response.parsed_output is None:
        raise PermanentError(
            f"generation for {company_name!r} did not return a parseable result "
            f"(stop_reason={response.stop_reason!r})"
        )
    return response.parsed_output


def write_draft(spec: BaseModel, out_path: str, *, company_name: str, source_pdf: str) -> None:
    """Write the draft to disk, unmistakably labelled as unreviewed.

    `field_vocabulary_version` is the sorted vocabulary this draft was
    generated against - if `scorecard.CHECKED_FIELDS` grows before this draft
    is reviewed, a reviewer can tell whether a field it omitted was actually
    unavailable at generation time or has simply never been looked at.
    """
    payload = {
        "status": "draft - not reviewed, do not use in production",
        "company_name": company_name,
        "source_pdf": os.path.basename(source_pdf),
        "field_vocabulary_version": list(_FIELD_NAMES),
        "spec": json.loads(spec.model_dump_json()),
    }
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
