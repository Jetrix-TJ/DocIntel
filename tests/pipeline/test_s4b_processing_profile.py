"""Stage 4b: `ResolveProcessingProfile`.

Absence - no persona, no `processing_profile` key, or no store at all - must
all mean the same thing: no follow-up is owed, the all-`"none"` default. A
declared profile is validated against a closed vocabulary (reconciliation
values, registered export layout names) and fails loudly on anything else,
matching every other closed-vocabulary check in this codebase.
"""

from __future__ import annotations

import pytest

from docintel.core.models import new_context
from docintel.pipeline.stages.s4b_processing_profile import (
    ProcessingProfileError,
    ResolveProcessingProfile,
)

_SENTINEL_PERSONA = object()  # the stage only checks "is a persona present", not its shape


class _FakeStore:
    def __init__(self, raw: dict | None) -> None:
        self._raw = raw

    def raw(self, sender_fingerprint, doc_type):
        return self._raw


def _ctx(persona=_SENTINEL_PERSONA, sender_fingerprint="northstar|veritiv", doc_type="standard_invoice"):
    ctx = new_context("d1", "/x.pdf", sender_fingerprint=sender_fingerprint, doc_type=doc_type)
    ctx.persona = persona
    return ctx


def test_a_hard_miss_gets_the_all_none_default():
    ctx = _ctx(persona=None)
    out = ResolveProcessingProfile(store=_FakeStore({"processing_profile": {"reconciliation": "auto"}})).run(ctx)
    assert out.processing_profile == {"reconciliation": "none", "export": []}


def test_no_store_at_all_gets_the_all_none_default():
    out = ResolveProcessingProfile(store=None).run(_ctx())
    assert out.processing_profile == {"reconciliation": "none", "export": []}


def test_a_persona_with_no_processing_profile_key_gets_the_default():
    out = ResolveProcessingProfile(store=_FakeStore({"doc_type": "standard_invoice"})).run(_ctx())
    assert out.processing_profile == {"reconciliation": "none", "export": []}


def test_reconciliation_auto_is_read_through():
    raw = {"processing_profile": {"reconciliation": "auto"}}
    out = ResolveProcessingProfile(store=_FakeStore(raw)).run(_ctx())
    assert out.processing_profile == {"reconciliation": "auto", "export": []}


def test_an_invalid_reconciliation_value_fails_loudly():
    raw = {"processing_profile": {"reconciliation": "sometimes"}}
    with pytest.raises(ProcessingProfileError, match="reconciliation"):
        ResolveProcessingProfile(store=_FakeStore(raw)).run(_ctx())


def test_a_registered_export_layout_is_read_through():
    raw = {"processing_profile": {"export": ["telecom_detail"]}}
    out = ResolveProcessingProfile(
        store=_FakeStore(raw), export_layouts=frozenset({"standard", "telecom_detail"})
    ).run(_ctx())
    assert out.processing_profile == {"reconciliation": "none", "export": ["telecom_detail"]}


def test_an_unregistered_export_layout_fails_loudly_not_silently_ignored():
    raw = {"processing_profile": {"export": ["a_layout_nobody_registered"]}}
    with pytest.raises(ProcessingProfileError, match="a_layout_nobody_registered"):
        ResolveProcessingProfile(store=_FakeStore(raw), export_layouts=frozenset({"standard"})).run(_ctx())


def test_both_reconciliation_and_export_can_be_declared_together():
    raw = {"processing_profile": {"reconciliation": "auto", "export": ["standard"]}}
    out = ResolveProcessingProfile(
        store=_FakeStore(raw), export_layouts=frozenset({"standard"})
    ).run(_ctx())
    assert out.processing_profile == {"reconciliation": "auto", "export": ["standard"]}
