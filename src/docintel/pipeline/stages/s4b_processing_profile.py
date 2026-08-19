"""Stage 4b: what does this document's persona need done with it, beyond
extraction itself?

Runs immediately after persona lookup, because that's the earliest point a
real-time decision is possible: `docintel process` classified the sender,
found (or didn't find) a persona, and now - before a single field is even
captured - can already answer "does this vendor's invoice need matching
against a contract on file? does it need an Excel drop for an AP team?"
without a human having to remember to run a separate command afterward.

Deliberately does NOT re-decide "raw values vs. computed formulas" here -
that's already fully expressed by which `adjust` ops a persona's selectors
wire (see `grammar/ops/derive.py`), and restating it as a second flag here
would just be a second source of truth that can drift from the first. This
profile only covers the two decisions that have no per-document trigger
today: reconciliation and export.

A persona with no `processing_profile` key, or no persona at all (hard miss),
both mean the same thing: no follow-up is owed. Absence is not an error.
"""

from __future__ import annotations

from typing import Any

from docintel.core.models import JobContext

_DEFAULT: dict[str, Any] = {"reconciliation": "none", "export": []}

_VALID_RECONCILIATION = frozenset({"none", "auto"})


class ProcessingProfileError(ValueError):
    """A persona's `processing_profile` names something this build doesn't
    recognize - fails loudly at resolution time rather than silently doing
    nothing, matching every other closed-vocabulary check in this codebase
    (the signal registry, the value-op registry, the claim-rule kinds)."""


class ResolveProcessingProfile:
    name = "resolve_processing_profile"

    def __init__(self, store: object | None = None, export_layouts: frozenset[str] = frozenset()) -> None:
        self.store = store
        # The registered export layout names, injected rather than imported
        # directly - this stage must not depend on `docintel.export` (which
        # pulls in the optional `openpyxl` extra) just to validate a string.
        self.export_layouts = export_layouts

    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("s4b: resolve_processing_profile")
        ctx.processing_profile = dict(_DEFAULT)

        if ctx.persona is None or self.store is None:
            return ctx
        if ctx.sender_fingerprint is None or ctx.doc_type is None:
            return ctx

        raw = self.store.raw(ctx.sender_fingerprint, ctx.doc_type)  # type: ignore[attr-defined]
        declared = (raw or {}).get("processing_profile")
        if not declared:
            return ctx

        reconciliation = declared.get("reconciliation", "none")
        if reconciliation not in _VALID_RECONCILIATION:
            raise ProcessingProfileError(
                f"{ctx.sender_fingerprint}/{ctx.doc_type}: processing_profile.reconciliation "
                f"is {reconciliation!r}, must be one of {sorted(_VALID_RECONCILIATION)}"
            )

        export = declared.get("export", [])
        unknown = [name for name in export if name not in self.export_layouts]
        if unknown:
            raise ProcessingProfileError(
                f"{ctx.sender_fingerprint}/{ctx.doc_type}: processing_profile.export names "
                f"unregistered layout(s) {unknown} - registered: {sorted(self.export_layouts)}"
            )

        ctx.processing_profile = {"reconciliation": reconciliation, "export": list(export)}
        return ctx
