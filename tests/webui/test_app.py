"""End-to-end tests for the web UI, against the real pipeline - no mocked
extraction. Each test builds its own runner_factory so the four result states
(extracted, no persona, collapsed persona, skipped/dead-letter) are each
reproduced by real pipeline conditions rather than asserted on stubbed output.
"""

from __future__ import annotations

import copy
import io
import json
import os

from docintel.adapters.vision.fake import FakeVision
from docintel.core.coverage import ScalarSelector
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs, register_all
from docintel.packs.store import PackPersonaStore
from docintel.pipeline.hooks import HookRegistry
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_default_stages, build_pipeline
from docintel.webui.app import _label, create_app

DTSS_PDF = "docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf"

COMCAST_GOLD = os.path.join(
    "docs", "corpus", "gold", "digitaldirection-comcast-8495444620365242.json"
)
NO_MATCH = "(ZZ_NOT_ON_THIS_PAGE_ZZ)"


def _real_runner_factory():
    return lambda: build_pipeline(vision=FakeVision())


def _no_persona_runner_factory():
    """A runner with no persona store at all: every document is a hard miss."""
    return lambda: Runner(
        stages=build_default_stages(vision=FakeVision()), hooks=HookRegistry()
    )


def _collapsed_runner_factory():
    """Comcast's real persona, mutated so all but two selectors match nothing -
    same technique tests/test_incomplete_extraction_guard.py uses to simulate a
    template redesign that leaves most declared fields unsatisfied.
    """
    with open(COMCAST_GOLD) as fh:
        gold = json.load(fh)

    def factory():
        packs = load_packs()
        hooks = HookRegistry()
        register_all(hooks, packs)
        store = PackPersonaStore(packs)
        key = next(k for k in store.keys if k[0] == "digitaldirection|comcast")
        raw = copy.deepcopy(store.raw(*key))
        for selector in raw["field_selectors"]:
            if selector.get("field") not in {"account_number", "total_printed"}:
                selector["pattern"] = NO_MATCH
        store._by_key[key] = parse_persona(raw)
        return Runner(
            stages=build_default_stages(
                vision=FakeVision(), hooks=hooks, packs=packs, store=store
            ),
            hooks=hooks,
        )

    return factory, gold


def _upload(client, path: str, filename: str | None = None):
    with open(path, "rb") as fh:
        data = fh.read()
    return client.post(
        "/process",
        data={"pdf": (io.BytesIO(data), filename or os.path.basename(path))},
        content_type="multipart/form-data",
    )


def test_upload_form_renders():
    app = create_app(runner_factory=_real_runner_factory())
    resp = app.test_client().get("/")
    assert resp.status_code == 200
    assert b"form" in resp.data.lower()


def test_a_clean_document_shows_extracted_fields_and_auto_approved():
    app = create_app(runner_factory=_real_runner_factory())
    resp = _upload(app.test_client(), DTSS_PDF)
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "699" in body
    assert "D.T.S.S" in body
    assert "Auto-approved" in body


def test_a_clean_document_shows_company_doc_type_and_persona_used():
    app = create_app(runner_factory=_real_runner_factory())
    resp = _upload(app.test_client(), DTSS_PDF)
    body = resp.data.decode()
    assert "D.T.S.S" in body  # company, from the printed vendor_name
    assert "standard_invoice" in body  # doc type
    assert "northstar|dtss" in body  # the persona (sender_fingerprint) that matched
    assert "v1" in body  # the persona's rule_version


def test_a_non_pdf_is_rejected_before_the_pipeline_runs():
    app = create_app(runner_factory=_real_runner_factory())
    client = app.test_client()
    resp = client.post(
        "/process",
        data={"pdf": (io.BytesIO(b"not a pdf"), "notes.txt")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert b"pdf" in resp.data.lower()


def test_no_file_is_rejected_before_the_pipeline_runs():
    app = create_app(runner_factory=_real_runner_factory())
    resp = app.test_client().post("/process", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_a_document_with_no_matching_persona_shows_the_stop_message_only():
    app = create_app(runner_factory=_no_persona_runner_factory())
    resp = _upload(app.test_client(), DTSS_PDF)
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "No extraction rules exist yet" in body
    # Nothing that looks like a field table should be rendered alongside the stop message.
    assert "<table" not in body


def test_no_persona_screen_still_shows_doc_type_and_says_no_persona_was_used():
    """Even with no persona, doc_type still has a value (Classify's own default),
    and the persona line should say plainly that none matched - not be silently
    blank - so a person knows what still needs authoring.
    """
    app = create_app(runner_factory=_no_persona_runner_factory())
    resp = _upload(app.test_client(), DTSS_PDF)
    body = resp.data.decode()
    assert "standard_invoice" in body
    assert "None" in body


def test_a_collapsed_persona_shows_a_distinct_message_from_no_persona():
    factory, gold = _collapsed_runner_factory()
    app = create_app(runner_factory=factory)
    resp = _upload(app.test_client(), os.path.join("docs", gold["source_file"]))
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "aren't matching this document" in body
    assert "No extraction rules exist yet" not in body


def test_extracted_document_shows_every_declared_field_as_extracted():
    """DTSS is the cleanest document in the corpus - every field the persona
    declares should come back marked extracted, not just the ones shown in the
    general value table."""
    store = PackPersonaStore(load_packs())
    persona = store.lookup("northstar|dtss", "standard_invoice")
    declared = [s.field for s in persona.field_selectors if isinstance(s, ScalarSelector)]
    assert declared, "the test did not achieve the condition it is asserting about"

    app = create_app(runner_factory=_real_runner_factory())
    resp = _upload(app.test_client(), DTSS_PDF)
    body = resp.data.decode()

    for field in declared:
        assert _label(field) in body, f"{field} missing from the coverage table"
    assert f"{len(declared)}/{len(declared)}" in body


def test_a_collapsed_persona_shows_which_declared_fields_are_missing():
    """The whole point of this table: on a collapsed persona, most declared
    fields should read Missing, and the two survivors should read Extracted."""
    factory, gold = _collapsed_runner_factory()
    kept = {"account_number", "total_printed"}

    # Ground truth: run the same factory directly (not through the app) so the
    # expected populated/declared counts come from the real record, not an
    # assumption about which fields survive breaking `kept`'s siblings - e.g.
    # `vendor_name` turns out to survive too, resolved via a page-text alias
    # independent of its own (broken) selector pattern.
    reference_record = factory().process(gold["gold_id"], os.path.join("docs", gold["source_file"]))
    coverage = reference_record["extraction_coverage"]
    assert coverage["populated"] < coverage["declared"], (
        "the test did not achieve the condition it is asserting about"
    )

    app = create_app(runner_factory=factory)
    resp = _upload(app.test_client(), os.path.join("docs", gold["source_file"]))
    body = resp.data.decode()

    for field in kept:
        assert _label(field) in body
    assert f"{coverage['populated']}/{coverage['declared']}" in body
