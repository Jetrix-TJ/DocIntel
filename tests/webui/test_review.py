"""The reviewer queue (`/review`, `/review/<id>`, `/review/<id>/resolve`) -
against the real job store, real templates, and (for the no-restart test) the
real pipeline and real pack conventions. No mocked extraction here either,
matching tests/webui/test_app.py's own convention.
"""

from __future__ import annotations

import io
import json
import os

from docintel.adapters.vision.fake import FakeVision
from docintel.jobs.store import SQLiteJobQueue
from docintel.pipeline.stages import build_pipeline
from docintel.webui import app as app_module
from docintel.webui.app import create_app

EDCO_GOLD = os.path.join("docs", "corpus", "gold", "northstar-edco-077087.json")


def _queue(tmp_path):
    return SQLiteJobQueue(tmp_path / "jobs.sqlite3")


def _upload(client, path: str, filename: str | None = None):
    with open(path, "rb") as fh:
        data = fh.read()
    return client.post(
        "/process",
        data={"pdf": (io.BytesIO(data), filename or os.path.basename(path))},
        content_type="multipart/form-data",
    )


def test_review_list_says_nothing_waiting_when_the_queue_is_empty(tmp_path):
    app = create_app(jobs=_queue(tmp_path))
    resp = app.test_client().get("/review")
    assert resp.status_code == 200
    assert "Nothing waiting on a human right now." in resp.data.decode()


def test_review_list_shows_an_open_job_grouped_by_kind(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    app = create_app(jobs=queue)
    resp = app.test_client().get("/review")
    body = resp.data.decode()
    assert resp.status_code == 200
    assert "northstar|edco" in body
    assert "Unknown prior-balance basis" in body


def test_review_detail_shows_the_context_snapshot(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue_once(
        "northstar|edco",
        "standard_invoice",
        kind="prior_balance_basis",
        context={"prior_balance": 298.34, "current_charges": 69.62},
    )
    job = queue.list_open()[0]
    app = create_app(jobs=queue)
    resp = app.test_client().get(f"/review/{job.id}")
    body = resp.data.decode()
    assert resp.status_code == 200
    assert "298.34" in body
    assert "edco" in body


def test_review_detail_404s_for_an_unknown_job(tmp_path):
    app = create_app(jobs=_queue(tmp_path))
    resp = app.test_client().get("/review/999")
    assert resp.status_code == 404


def test_resolve_404s_for_an_unknown_job(tmp_path):
    app = create_app(jobs=_queue(tmp_path))
    resp = app.test_client().post(
        "/review/999/resolve", data={"reviewer": "jeeva", "basis": "gross", "confirm": "on"}
    )
    assert resp.status_code == 404


def test_review_list_groups_multiple_kinds_independently(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    queue.enqueue_once("newvendor|newvendor", None, kind="persona_authoring")
    app = create_app(jobs=queue)
    body = app.test_client().get("/review").data.decode()
    assert "northstar|edco" in body
    assert "newvendor|newvendor" in body
    assert "Unknown prior-balance basis" in body
    assert "New sender, no persona yet" in body


def test_resolve_fails_cleanly_for_a_pack_that_does_not_exist(tmp_path):
    """A malformed or synthetic sender_fingerprint whose pack half does not
    resolve to a real module - must fail with a clear error, not a stack
    trace, since this data ultimately comes from whatever `Classify` computed."""
    queue = _queue(tmp_path)
    queue.enqueue_once("not_a_real_pack|somevendor", "standard_invoice", kind="prior_balance_basis")
    job = queue.list_open()[0]
    app = create_app(jobs=queue)
    resp = app.test_client().post(
        f"/review/{job.id}/resolve",
        data={"basis": "gross", "confirm": "on", "reviewer": "jeeva"},
    )
    assert resp.status_code == 400
    assert queue.get(job.id).status == "open"


def test_resolving_an_already_resolved_job_is_idempotent_not_a_crash(tmp_path, monkeypatch):
    """`/review` itself only ever lists open jobs, but a bookmarked or
    revisited detail link for an already-resolved job must not error out -
    it's safe to resolve a second time (last write wins), just unusual UX."""
    overlay_dir = tmp_path / "northstar_pack"
    overlay_dir.mkdir()
    monkeypatch.setattr(app_module, "_pack_dir", lambda pack_name: str(overlay_dir))

    queue = _queue(tmp_path)
    queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    job = queue.list_open()[0]
    app = create_app(jobs=queue)
    client = app.test_client()

    first = client.post(
        f"/review/{job.id}/resolve",
        data={"basis": "gross", "confirm": "on", "reviewer": "jeeva"},
    )
    assert first.status_code == 302

    second = client.post(
        f"/review/{job.id}/resolve",
        data={"basis": "net_of_payments", "confirm": "on", "reviewer": "someone-else"},
    )
    assert second.status_code == 302

    resolved = queue.get(job.id)
    assert resolved.resolved_by == "someone-else"
    assert resolved.resolution == {"basis": "net_of_payments"}


def test_resolve_requires_a_reviewer_name(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    job = queue.list_open()[0]
    app = create_app(jobs=queue)
    resp = app.test_client().post(
        f"/review/{job.id}/resolve", data={"basis": "gross", "confirm": "on"}
    )
    assert resp.status_code == 400
    assert queue.get(job.id).status == "open"


def test_resolve_rejects_a_basis_outside_the_closed_set(tmp_path):
    """Never free text - the same closed-set discipline derive.py relies on."""
    queue = _queue(tmp_path)
    queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    job = queue.list_open()[0]
    app = create_app(jobs=queue)
    resp = app.test_client().post(
        f"/review/{job.id}/resolve",
        data={"basis": "somewhere_in_between", "confirm": "on", "reviewer": "jeeva"},
    )
    assert resp.status_code == 400
    assert queue.get(job.id).status == "open"


def test_resolve_requires_the_confirm_checkbox(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    job = queue.list_open()[0]
    app = create_app(jobs=queue)
    resp = app.test_client().post(
        f"/review/{job.id}/resolve", data={"basis": "gross", "reviewer": "jeeva"}
    )
    assert resp.status_code == 400
    assert queue.get(job.id).status == "open"


def test_resolve_writes_the_overlay_and_marks_the_job_resolved(tmp_path, monkeypatch):
    overlay_dir = tmp_path / "northstar_pack"
    overlay_dir.mkdir()
    monkeypatch.setattr(app_module, "_pack_dir", lambda pack_name: str(overlay_dir))

    queue = _queue(tmp_path)
    queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    job = queue.list_open()[0]
    app = create_app(jobs=queue)
    resp = app.test_client().post(
        f"/review/{job.id}/resolve",
        data={"basis": "gross", "confirm": "on", "reviewer": "jeeva"},
    )
    assert resp.status_code == 302

    resolved = queue.get(job.id)
    assert resolved.status == "resolved"
    assert resolved.resolved_by == "jeeva"
    assert resolved.resolution == {"basis": "gross"}

    overlay_path = overlay_dir / "prior_balance_basis.local.json"
    assert json.loads(overlay_path.read_text()) == {"edco": "gross"}


def test_resolve_of_a_persona_authoring_job_needs_only_a_reviewer_name(tmp_path):
    """Rule authoring stays out of scope (s5c_agent.py) - resolving here just
    clears the queue entry once a human has written the persona by hand."""
    queue = _queue(tmp_path)
    queue.enqueue_once("newvendor|newvendor", None, kind="persona_authoring")
    job = queue.list_open()[0]
    app = create_app(jobs=queue)
    resp = app.test_client().post(
        f"/review/{job.id}/resolve", data={"reviewer": "jeeva", "note": "authored by hand"}
    )
    assert resp.status_code == 302
    resolved = queue.get(job.id)
    assert resolved.status == "resolved"
    assert resolved.resolution == {"note": "authored by hand"}


def test_a_reviewers_decision_takes_effect_on_the_next_document_with_no_restart(
    tmp_path, monkeypatch
):
    """The point of the whole overlay design (Phase 4): a reviewer's answer
    must take effect on the very next document from the same vendor, using the
    exact same already-built runner - no process restart, no new
    `build_pipeline` call, and `PRIOR_BALANCE_BASIS` itself stays untouched.

    EDCO is already a known vendor (`PRIOR_BALANCE_BASIS["edco"] = "gross"`),
    so its own entry is patched away here to simulate "not yet known" without
    touching the real, audited table.
    """
    from northstar import PACK as NORTHSTAR_PACK
    from northstar import conventions as ns_conventions

    # `northstar` is a test fixture (tests/fixtures/packs/), not a shipped
    # module - `webui.app._pack_dir` only locates a pack's overlay directory
    # via `PACK_MODULES`, so this test's own use of a real northstar document
    # needs it added there too, for this test's duration only. The bare
    # "northstar" import path resolves via the pythonpath entry that makes
    # `from northstar import ...` work at all in this test suite.
    monkeypatch.setattr(app_module, "PACK_MODULES", (*app_module.PACK_MODULES, "northstar"))

    monkeypatch.delitem(ns_conventions.PRIOR_BALANCE_BASIS, "edco")

    overlay_path = os.path.join(ns_conventions._PACK_DIR, "prior_balance_basis.local.json")
    assert not os.path.exists(overlay_path), (
        "a stray overlay file from a previous run would invalidate this test"
    )

    with open(EDCO_GOLD) as fh:
        gold = json.load(fh)
    source = os.path.join("docs", gold["source_file"])

    queue = _queue(tmp_path)
    runner = build_pipeline(vision=FakeVision(), jobs=queue, extra_packs=[NORTHSTAR_PACK])
    app = create_app(runner_factory=lambda: runner, jobs=queue)
    client = app.test_client()

    try:
        # First document: no known convention for edco (patched away above),
        # and no overlay file yet either - a prior_balance_basis job must
        # appear, and the document must be routed to review.
        resp = _upload(client, source)
        assert resp.status_code == 200
        assert "Needs review" in resp.data.decode()

        open_jobs = queue.list_open("prior_balance_basis")
        assert len(open_jobs) == 1
        job = open_jobs[0]
        assert job.sender_fingerprint == "northstar|edco"

        # A reviewer confirms the truth (matches this gold label's own note:
        # BALANCE FORWARD is carried in full, i.e. gross).
        resp = client.post(
            f"/review/{job.id}/resolve",
            data={"basis": "gross", "confirm": "on", "reviewer": "jeeva"},
        )
        assert resp.status_code == 302
        assert queue.get(job.id).status == "resolved"

        # Second document, same vendor, the SAME runner object built above -
        # PRIOR_BALANCE_BASIS is still missing "edco", so this can only
        # reconcile if apply_prior_balance_basis is reading the overlay file
        # the resolve route just wrote, fresh, with no restart.
        record = runner.process("edco-second-run", source)
        assert record["fields"]["prior_balance_basis"] == "gross"
        assert record["derived"]["amount_payable"] == "69.62"
        assert record["lane"] == "high"
        assert record["review_flag"] is False
        assert queue.list_open("prior_balance_basis") == []
    finally:
        if os.path.exists(overlay_path):
            os.remove(overlay_path)


# ==========================================================================
# `contract_reconciliation` jobs (Phase 7)
# ==========================================================================


def test_contract_reconciliation_job_is_listed_under_its_own_kind_label(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue_once(
        "digitaldirection|windstream", "telecom_bill", kind="contract_reconciliation",
        context={"account_number": "041069076"}, match_key="inv-1",
    )
    app = create_app(jobs=queue)
    body = app.test_client().get("/review").data.decode()
    assert "digitaldirection|windstream" in body
    assert "Invoice/contract reconciliation" in body


def test_contract_reconciliation_detail_renders_the_finding_context(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue_once(
        "digitaldirection|windstream", "telecom_bill", kind="contract_reconciliation",
        context={"contracted_rate": 100.0, "billed_rate": 106.0, "variance_pct": 6.0},
        match_key="inv-1",
    )
    job = queue.list_open("contract_reconciliation")[0]
    app = create_app(jobs=queue)
    body = app.test_client().get(f"/review/{job.id}").data.decode()
    assert "106.0" in body
    assert "6.0" in body


def test_contract_reconciliation_resolves_with_just_a_reviewer_name(tmp_path):
    """No downstream payment/approval action of any kind - resolving only
    records that a reviewer looked at it, the same shape as persona_authoring."""
    queue = _queue(tmp_path)
    queue.enqueue_once(
        "digitaldirection|windstream", "telecom_bill", kind="contract_reconciliation",
        context={"account_number": "041069076"}, match_key="inv-1",
    )
    job = queue.list_open("contract_reconciliation")[0]
    app = create_app(jobs=queue)
    resp = app.test_client().post(
        f"/review/{job.id}/resolve",
        data={"reviewer": "jeeva", "note": "confirmed with AP, one-time overage"},
    )
    assert resp.status_code == 302
    resolved = queue.get(job.id)
    assert resolved.status == "resolved"
    assert resolved.resolved_by == "jeeva"
    assert resolved.resolution == {"note": "confirmed with AP, one-time overage"}


def test_contract_reconciliation_resolve_writes_no_pack_overlay_file(tmp_path, monkeypatch):
    """Unlike prior_balance_basis, resolving a reconciliation finding must
    never touch any pack directory - there is no overlay concept here."""
    queue = _queue(tmp_path)
    queue.enqueue_once(
        "digitaldirection|windstream", "telecom_bill", kind="contract_reconciliation",
        context={}, match_key="inv-1",
    )
    job = queue.list_open("contract_reconciliation")[0]

    calls = []
    monkeypatch.setattr(app_module, "_pack_dir", lambda pack_name: calls.append(pack_name) or None)

    app = create_app(jobs=queue)
    resp = app.test_client().post(
        f"/review/{job.id}/resolve", data={"reviewer": "jeeva"},
    )
    assert resp.status_code == 302
    assert calls == []


# ==========================================================================
# `/review/<id>/correct` - the correction-return contract's capture half
# (Phase 2 of the evals plan). Only jobs whose context carries a
# `record_snapshot` (currently: `persona_authoring`) get this route; the
# other two kinds keep their existing resolve-only flow untouched.
# ==========================================================================


def _corrections(tmp_path):
    from docintel.evals.corrections import CorrectionStore

    return CorrectionStore(tmp_path / "corrections.sqlite3")


def _snapshot_job(queue, **fields):
    queue.enqueue_once(
        "newvendor|newvendor", "invoice", kind="persona_authoring",
        context={"record_snapshot": {
            "document_id": "doc-1", "source_path": "/tmp/doc-1.pdf",
            "sender_fingerprint": "newvendor|newvendor", "doc_type": "invoice",
            "tags": [], "fields": fields, "derived": {},
        }},
    )
    return queue.list_open("persona_authoring")[0]


def test_review_detail_renders_an_editable_form_for_a_job_with_a_record_snapshot(tmp_path):
    queue = _queue(tmp_path)
    job = _snapshot_job(queue, vendor_name=None, total_printed="640.50")
    app = create_app(jobs=queue, corrections=_corrections(tmp_path))

    body = app.test_client().get(f"/review/{job.id}").data.decode()

    assert 'name="field:vendor_name"' in body
    assert 'name="field:total_printed"' in body
    assert 'value="640.50"' in body
    assert f'/review/{job.id}/correct' in body


def test_correcting_a_field_records_the_diff_and_resolves_the_job(tmp_path):
    queue = _queue(tmp_path)
    job = _snapshot_job(queue, vendor_name=None, total_printed="640.50")
    corrections = _corrections(tmp_path)
    app = create_app(jobs=queue, corrections=corrections)

    resp = app.test_client().post(
        f"/review/{job.id}/correct",
        data={
            "reviewer": "alice",
            "field:vendor_name": "Acme Corp",
            "field:total_printed": "640.50",
        },
    )

    assert resp.status_code == 302
    pending = corrections.list_pending()
    assert len(pending) == 1
    assert pending[0].corrected_fields == {"vendor_name": "Acme Corp"}
    assert pending[0].corrected_by == "alice"
    assert pending[0].document_id == "doc-1"
    assert queue.get(job.id).status == "resolved"


def test_leaving_every_field_unchanged_confirms_clean_with_no_corrections(tmp_path):
    queue = _queue(tmp_path)
    job = _snapshot_job(queue, vendor_name="Acme Corp")
    corrections = _corrections(tmp_path)
    app = create_app(jobs=queue, corrections=corrections)

    app.test_client().post(
        f"/review/{job.id}/correct",
        data={"reviewer": "alice", "field:vendor_name": "Acme Corp"},
    )

    assert corrections.list_pending()[0].corrected_fields == {}


def test_correct_requires_a_reviewer_name(tmp_path):
    queue = _queue(tmp_path)
    job = _snapshot_job(queue, vendor_name=None)
    app = create_app(jobs=queue, corrections=_corrections(tmp_path))

    resp = app.test_client().post(f"/review/{job.id}/correct", data={})

    assert resp.status_code == 400


def test_correct_404s_for_an_unknown_job(tmp_path):
    app = create_app(jobs=_queue(tmp_path), corrections=_corrections(tmp_path))
    resp = app.test_client().post("/review/999/correct", data={"reviewer": "alice"})
    assert resp.status_code == 404


def test_correct_refuses_a_job_with_no_record_snapshot(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue_once("northstar|edco", "standard_invoice", kind="prior_balance_basis")
    job = queue.list_open()[0]
    app = create_app(jobs=queue, corrections=_corrections(tmp_path))

    resp = app.test_client().post(
        f"/review/{job.id}/correct", data={"reviewer": "alice"}
    )

    assert resp.status_code == 400

