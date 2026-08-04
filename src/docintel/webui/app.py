"""Flask app: upload one PDF, run it through the real pipeline, show the result.

Deliberately thin. Every request calls the same `Runner`/`build_pipeline` the CLI
uses (see docintel.cli._build_runner) - no extraction or routing rule is
duplicated here. The only work this module does is: validate the upload, run it,
and classify the resulting record into one of four screens.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from typing import Any

from flask import Flask, render_template, request

from docintel.adapters.vision.fake import FakeVision
from docintel.core.coverage import ScalarSelector
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_pipeline

MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25MB

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


def default_runner_factory() -> Callable[[], Runner]:
    """Same wiring `docintel process` uses: real packs, vision fallback off."""
    return lambda: build_pipeline(vision=FakeVision())


def create_app(runner_factory: Callable[[], Runner] | None = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

    # Built once, at app start, and reused across requests - deliberately, so
    # duplicate detection (IdentityIndex, scoped to "one run") works across
    # uploads made in the same server session, the same way it would across
    # documents in one `docintel process` invocation.
    runner = (runner_factory or default_runner_factory())()

    @app.get("/")
    def upload_form() -> str:
        return render_template("upload.html")

    @app.post("/process")
    def process() -> tuple[str, int] | str:
        upload = request.files.get("pdf")
        if upload is None or not upload.filename:
            return render_template("error.html", message="Choose a PDF file to upload."), 400
        if not upload.filename.lower().endswith(".pdf"):
            return render_template(
                "error.html", message="Only PDF files are accepted."
            ), 400

        fd, temp_path = tempfile.mkstemp(suffix=".pdf")
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
        finally:
            os.remove(temp_path)

        return render_template("result.html", **_view(record, upload.filename, runner))

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
