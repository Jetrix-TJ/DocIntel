"""Flask app: upload one PDF, run it through the real pipeline, show the result.

Deliberately thin. Every request calls the same `Runner`/`build_pipeline` the CLI
uses (see docintel.cli._build_runner) - no extraction or routing rule is
duplicated here. The only work this module does is: validate the upload, run it,
and classify the resulting record into one of four screens.

Also serves `/review`: the human-in-the-loop queue that `AgentEscalation` (s5c)
and `ConfidenceGate` (s7) enqueue into instead of silently guessing. One
`SQLiteJobQueue` instance is shared between the extraction pipeline and these
routes - built once, at app start, same lifecycle as the shared `runner`.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import urllib.parse
from collections.abc import Callable
from typing import Any

from flask import Flask, redirect, render_template, request, url_for

from docintel.adapters.vision.fake import FakeVision
from docintel.core.coverage import ScalarSelector
from docintel.evals.corrections import CorrectionStore
from docintel.extract.convert import ACCEPTED_SUFFIXES
from docintel.jobs.store import SQLiteJobQueue
from docintel.packs.registry import PACK_MODULES, load_basis_overlay
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_pipeline

MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25MB

# Where an escalated upload's source bytes get retained (docintel.evals.corrections,
# promote-correction) - the upload route's own temp file is removed right after
# processing (see `process()` below), so anything that might later need the real
# PDF (a promoted gold fixture needs a real, retained file) must copy it out first.
# Keyed by document_id, not by whatever the job's `record_snapshot.source_path`
# says, deliberately: that field is frozen at escalation time and stays a dead
# temp path for a webui upload, while this location is a stable convention a
# later promotion step can always check first.
CORRECTIONS_DIR = "var/eval_corrections"

# The only two values `derive.resolve_carried_balance` understands (F1b) - a
# reviewer picks one of these, never free text, so an overlay entry can never
# introduce a third meaning the reconciliation code doesn't already handle.
BASIS_CHOICES = ("gross", "net_of_payments")

# Derived values that describe HOW a field was resolved (provenance/plumbing)
# rather than a value a person uploading a document cares about. Matched by
# suffix so a new "*_basis" field added to a pack doesn't need this list touched.
_PLUMBING_SUFFIXES = ("_basis", "_fingerprint", "_canonical")

# Human-readable copy for confidence_modifiers tags (s7_gate.py / infer.py). Any
# tag not listed here falls back to a humanized version of the raw tag name, so
# a newly-added modifier doesn't require a template change to be visible.
_MODIFIER_COPY = {
    "bill_to_mismatch": (
        "The printed bill-to party does not match this vendor's known client "
        "roster — confirm this document is actually billed to us before approving payment."
    ),
}


def default_runner_factory(jobs: object) -> Callable[[], Runner]:
    """Same wiring `docintel process` uses: real packs, vision fallback off.

    Takes the app's shared `jobs` queue so escalated documents land in the
    same store `/review` reads from - one queue per app, not one per module.
    """
    return lambda: build_pipeline(vision=FakeVision(), jobs=jobs)


def _retain_source(temp_path: str, document_id: str) -> None:
    os.makedirs(CORRECTIONS_DIR, exist_ok=True)
    # The real uploaded suffix, not a hardcoded ".pdf" - `temp_path` holds
    # whatever the uploader actually sent (an image or Office document
    # converts to PDF only *inside* the pipeline, not before this copy), and
    # a retained file misnamed ".pdf" would silently corrupt a later
    # `promote-correction`/gold-authoring pass that expects to open it as one.
    suffix = os.path.splitext(temp_path)[1]
    shutil.copyfile(temp_path, os.path.join(CORRECTIONS_DIR, f"{document_id}{suffix}"))


def _pack_dir(pack_name: str) -> str | None:
    """Directory of a shipped pack module, for locating its overlay file.

    Only module-backed packs (northstar, digitaldirection) carry a
    `conventions.py`/overlay at all - `PACK_MODULES` already enumerates
    exactly those, deliberately excluding the data-only packs in
    `PACK_FILES` (see `packs/registry.py`), which have no F1b table to
    override in the first place.
    """
    import importlib

    for module_path in PACK_MODULES:
        if module_path.rsplit(".", 1)[-1] == pack_name:
            module = importlib.import_module(module_path)
            return os.path.dirname(module.__file__)  # type: ignore[arg-type]
    return None


def create_app(
    runner_factory: Callable[[], Runner] | None = None,
    jobs: object | None = None,
    corrections: object | None = None,
) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

    # One queue for the whole app: the extraction pipeline enqueues into it
    # (s5c/s7), and /review reads and resolves against the exact same store.
    job_queue = jobs if jobs is not None else SQLiteJobQueue()

    # Where a reviewer's correction to a job's record_snapshot lands - see
    # `docintel.evals.corrections` for why promotion into gold stays a
    # separate, human-run command rather than happening here.
    correction_store = corrections if corrections is not None else CorrectionStore()

    # Built once, at app start, and reused across requests - deliberately, so
    # duplicate detection (IdentityIndex, scoped to "one run") works across
    # uploads made in the same server session, the same way it would across
    # documents in one `docintel process` invocation.
    runner = (runner_factory or default_runner_factory(job_queue))()

    @app.get("/")
    def upload_form() -> str:
        return render_template("upload.html")

    @app.post("/process")
    def process() -> tuple[str, int] | str:
        upload = request.files.get("pdf")
        if upload is None or not upload.filename:
            return render_template("error.html", message="Choose a file to upload."), 400
        upload_suffix = os.path.splitext(upload.filename)[1].lower()
        if upload_suffix not in ACCEPTED_SUFFIXES:
            accepted = ", ".join(sorted(ACCEPTED_SUFFIXES))
            return render_template(
                "error.html", message=f"{upload_suffix or '(no extension)'} is not accepted. "
                f"Accepted types: {accepted}."
            ), 400

        # The real uploaded suffix, not a hardcoded ".pdf" - Stage 2 branches
        # on this file's own extension to decide whether to convert it before
        # reading it as a PDF, so the temp file must carry the real one.
        fd, temp_path = tempfile.mkstemp(suffix=upload_suffix)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(upload.read())
            try:
                record = runner.process(
                    document_id=f"webui-{os.path.basename(temp_path)}",
                    source_path=temp_path,
                )
            except Exception as exc:  # noqa: BLE001 - last-resort surface, not a crash
                return render_template(
                    "error.html", message=f"Processing failed unexpectedly: {exc}"
                ), 500
            if record.get("review_flag"):
                _retain_source(temp_path, record["document_id"])
        finally:
            os.remove(temp_path)

        return render_template("result.html", **_view(record, upload.filename, runner))

    @app.get("/review")
    def review_list() -> str:
        jobs_by_kind: dict[str, list[dict[str, Any]]] = {}
        for job in job_queue.list_open():  # type: ignore[attr-defined]
            jobs_by_kind.setdefault(job.kind, []).append(
                {"id": job.id, "sender_fingerprint": job.sender_fingerprint,
                 "doc_type": job.doc_type, "created_at": job.created_at}
            )
        return render_template("review_list.html", jobs_by_kind=jobs_by_kind)

    @app.get("/review/<int:job_id>")
    def review_detail(job_id: int) -> tuple[str, int] | str:
        job = job_queue.get(job_id)  # type: ignore[attr-defined]
        if job is None:
            return render_template("error.html", message=f"No job #{job_id}."), 404
        _pack_name, _, vendor = job.sender_fingerprint.partition("|")
        return render_template(
            "review_detail.html",
            job=job,
            vendor=vendor or job.sender_fingerprint,
            basis_choices=BASIS_CHOICES,
        )

    @app.post("/review/<int:job_id>/resolve")
    def review_resolve(job_id: int) -> tuple[str, int] | str:
        job = job_queue.get(job_id)  # type: ignore[attr-defined]
        if job is None:
            return render_template("error.html", message=f"No job #{job_id}."), 404

        reviewer = (request.form.get("reviewer") or "").strip()
        if not reviewer:
            return render_template(
                "error.html", message="Reviewer name is required to confirm a decision."
            ), 400

        if job.kind == "prior_balance_basis":
            basis = request.form.get("basis")
            if basis not in BASIS_CHOICES or not request.form.get("confirm"):
                return render_template(
                    "error.html",
                    message="Pick one of the listed basis values and check the confirm box.",
                ), 400
            pack_name, _, vendor = job.sender_fingerprint.partition("|")
            pack_dir = _pack_dir(pack_name)
            if pack_dir is None:
                return render_template(
                    "error.html", message=f"Unknown pack {pack_name!r}; cannot write an overlay."
                ), 400
            overlay_path = os.path.join(pack_dir, "prior_balance_basis.local.json")
            overlay = load_basis_overlay(pack_dir)
            overlay[vendor] = basis
            with open(overlay_path, "w") as fh:
                json.dump(overlay, fh, indent=2, sort_keys=True)
            job_queue.resolve(job_id, {"basis": basis}, resolved_by=reviewer)  # type: ignore[attr-defined]
        elif job.kind == "contract_reconciliation":
            # No action here triggers any downstream payment or approval
            # system (docintel.reconciliation's own explicit scope boundary)
            # - resolving just records that a reviewer looked at the finding
            # and what they decided, in free text.
            job_queue.resolve(  # type: ignore[attr-defined]
                job_id, {"note": request.form.get("note", "")}, resolved_by=reviewer
            )
        else:
            # persona_authoring: rule authoring itself is still out of scope
            # (see s5c_agent.py's docstring) - resolving here just clears the
            # queue entry once a human has actually written the persona by
            # hand, the same way it always required a developer before.
            job_queue.resolve(  # type: ignore[attr-defined]
                job_id, {"note": request.form.get("note", "")}, resolved_by=reviewer
            )

        return redirect(url_for("review_list"))

    @app.post("/review/<int:job_id>/correct")
    def review_correct(job_id: int) -> tuple[str, int] | str:
        """The correction-return contract's capture half (`docs/architecture/
        pipeline-v2.md:465-481`): a reviewer looking at a job that carries a
        `record_snapshot` can submit the actual correct value for any field,
        or confirm the snapshot is already clean. Either way becomes one
        `Correction` row - `docintel promote-correction` is what later turns
        an accepted one into real gold data; nothing here writes to the gold
        set directly.
        """
        job = job_queue.get(job_id)  # type: ignore[attr-defined]
        if job is None:
            return render_template("error.html", message=f"No job #{job_id}."), 404

        snapshot = (job.context or {}).get("record_snapshot")
        if snapshot is None:
            return render_template(
                "error.html",
                message=f"Job #{job_id} has nothing to correct against.",
            ), 400

        reviewer = (request.form.get("reviewer") or "").strip()
        if not reviewer:
            return render_template(
                "error.html", message="Reviewer name is required to confirm a decision."
            ), 400

        original_fields = snapshot.get("fields") or {}
        corrected_fields = {}
        for key, value in request.form.items():
            if not key.startswith("field:"):
                continue
            name = key[len("field:"):]
            value = value.strip()
            if not value:
                continue
            if str(original_fields.get(name, "")) != value:
                corrected_fields[name] = value

        correction_store.add(  # type: ignore[attr-defined]
            document_id=snapshot["document_id"],
            source_path=snapshot.get("source_path", ""),
            original_record=snapshot,
            corrected_fields=corrected_fields,
            corrected_by=reviewer,
            job_id=job_id,
        )
        job_queue.resolve(  # type: ignore[attr-defined]
            job_id, {"note": request.form.get("note", "")}, resolved_by=reviewer
        )

        return redirect(url_for("review_list"))

    return app


def _view(record: dict[str, Any], filename: str, runner: Runner) -> dict[str, Any]:
    """Classify one pipeline record into exactly one of four screens.

    See docs/superpowers/specs/2026-08-04-simple-web-ui-design.md for why each
    signal was picked: `extraction_coverage.declared == 0` is precise for "no
    persona was even matched" (core/coverage.py derives it from
    ctx.persona.field_selectors, empty when ctx.persona is None); `regen_flag`
    is s7_gate's own signal that a persona exists but mostly didn't match.

    Every branch includes `classification` (company / doc type / persona used) -
    that answer doesn't depend on whether extraction succeeded, so it's computed
    once and shown on all four screens.
    """
    coverage = record.get("extraction_coverage") or {}
    values = {**(record.get("fields") or {}), **(record.get("derived") or {})}
    classification = _classification(record, coverage, values)
    base = {
        "filename": filename,
        "classification": classification,
        "coverage_rows": None,
        "modifiers": [
            (tag, _MODIFIER_COPY.get(tag, _label(tag)))
            for tag in record.get("confidence_modifiers") or []
        ],
        "duplicate_of": record.get("possible_duplicate_of"),
        "record_json_url": (
            "data:application/json;charset=utf-8,"
            + urllib.parse.quote(json.dumps(record, indent=2))
        ),
    }

    if record["disposition"] in ("skipped", "dead_letter"):
        return {
            **base,
            "state": "failed",
            "reason": record.get("reason") or "No reason was given.",
        }

    if coverage.get("declared", 0) == 0:
        return {**base, "state": "no_persona"}

    coverage_rows = _declared_field_coverage(runner, record, values)
    coverage_summary = (
        f"{sum(1 for _, _, ok in coverage_rows if ok)}/{len(coverage_rows)} populated"
        if coverage_rows is not None
        else None
    )

    if record.get("regen_flag"):
        return {
            **base,
            "state": "collapsed",
            "coverage_rows": coverage_rows,
            "coverage_summary": coverage_summary,
        }

    status = (
        "Auto-approved"
        if record.get("lane") == "high" and not record.get("review_flag")
        else "Needs review"
    )

    confidence = record.get("confidence") or {}
    rows = sorted(
        (_label(name), value, confidence.get(name))
        for name, value in values.items()
        if value is not None and not name.endswith(_PLUMBING_SUFFIXES)
    )

    return {
        **base,
        "state": "extracted",
        "status": status,
        "lane": record.get("lane"),
        "rows": rows,
        "coverage_rows": coverage_rows,
        "coverage_summary": coverage_summary,
    }


def _classification(
    record: dict[str, Any], coverage: dict[str, Any], values: dict[str, Any]
) -> dict[str, str]:
    """Company / document type / persona actually used - independent of whether
    extraction succeeded, so a "no persona" screen can still say what WAS
    recognized (useful: it's exactly what tells you which persona to author).
    """
    fingerprint = record.get("sender_fingerprint") or "unknown|unknown"
    _, _, vendor_slug = fingerprint.partition("|")

    # `vendor_name` may come from either dict: some personas extract it directly
    # (fields), others only ever derive it via an alias (derived) - `values` is
    # already the merged view, same as the general field table uses.
    resolved_name = values.get("vendor_name")

    if resolved_name:
        company = resolved_name
    elif vendor_slug and vendor_slug != "unknown":
        company = _label(vendor_slug)
    else:
        company = "Unknown"

    if coverage.get("declared", 0) == 0:
        persona = "None — no persona matches this sender/document type yet"
    else:
        version = record.get("extraction_rule_version")
        persona = f"{fingerprint} (rule {version})" if version else fingerprint

    return {
        "company": company,
        "doc_type": record.get("doc_type") or "unknown",
        "persona": persona,
    }


def _declared_field_coverage(
    runner: Runner, record: dict[str, Any], values: dict[str, Any]
) -> list[tuple[str, bool, bool]] | None:
    """The persona's own declared field list - name, required, extracted -

    looked up from the SAME store the pipeline itself just used (found by
    walking `runner.stages` for whichever one carries `.store`, i.e.
    PersonaLookup), keyed by the same (sender_fingerprint, doc_type) pair
    already on the record. Not a second implementation of persona matching:
    it's the same store, asked the same question again, read-only.

    `ScalarSelector` is core/coverage.py's own filter for "a field selector
    that has a name and a required flag" - reused here so this list is defined
    identically to what `extraction_coverage.declared` already counts.
    """
    store = _find_persona_store(runner)
    if store is None:
        return None
    persona = store.lookup(record.get("sender_fingerprint"), record.get("doc_type"))
    if persona is None:
        return None

    return sorted(
        (_label(s.field), s.required, values.get(s.field) is not None)
        for s in persona.field_selectors
        if isinstance(s, ScalarSelector)
    )


def _find_persona_store(runner: Runner) -> object | None:
    for stage in runner.stages:
        store = getattr(stage, "store", None)
        if store is not None:
            return store
    return None


def _label(field_name: str) -> str:
    return field_name.replace("_", " ").title()
