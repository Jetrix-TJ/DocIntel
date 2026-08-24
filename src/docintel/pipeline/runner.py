"""Stage sequencing plus the emit-always guarantee.

count(intaken) == count(emitted) is spec Stage 8's machine-checkable promise.
Rather than trusting every code path to remember, process() wraps each document
so that any escape route - unhandled exception, retry exhaustion, a pack hook
throwing - still produces a record.
"""

from __future__ import annotations

import datetime as _dt
import shutil
from typing import Any, Protocol

from docintel.core.contract import build_record, validate_record
from docintel.core.duplicates import IdentityIndex
from docintel.core.errors import TransientError
from docintel.core.models import JobContext, new_context
from docintel.pipeline.hooks import HookRegistry


class Stage(Protocol):
    name: str

    def run(self, ctx: JobContext) -> JobContext: ...


# Which hook socket fires at which stage boundary.
#
# The runner owns BOUNDARY sockets, because it is the only object that can see
# the seams between stages. Two sockets are deliberately absent: classifySignals
# fires *inside* stage 3 (a pack injects its signal ladder there, cluster C5), and
# onRegenTrigger belongs to the rule lifecycle, which runs beside the pipeline
# rather than in it.
HOOKS_BEFORE: dict[str, str] = {
    "intake": "beforeIntake",
    "persona_lookup": "beforePersonaLookup",
    "capture_fields": "afterExtraction",
    "confidence_gate": "beforeConfidenceGate",
}

HOOKS_AFTER: dict[str, str] = {
    "attachment_filter": "afterFilter",
}

# beforeEmit is NOT in either map. It fires inside _emit() so that it reaches
# every emitted record — including skipped and dead-lettered ones, which never
# reach the emit stage because _run_stages breaks out early.


class Runner:
    def __init__(
        self,
        stages: list[Stage],
        hooks: HookRegistry,
        max_retries: int = 0,
    ) -> None:
        self.stages = stages
        self.hooks = hooks
        self.max_retries = max_retries
        self._intaken = 0
        self._emitted = 0
        # One index per Runner: duplicate detection is scoped to a single run
        # (see core.duplicates for why cross-run is out of scope).
        self._identity_index = IdentityIndex()

    @property
    def stats(self) -> dict[str, int]:
        return {"intaken": self._intaken, "emitted": self._emitted}

    def process(self, document_id: str, source_path: str, **kw: Any) -> dict[str, Any]:
        self._intaken += 1
        ctx = new_context(
            document_id=document_id,
            source_path=source_path,
            received_at=_dt.datetime.now(_dt.UTC).isoformat(),
            **kw,
        )
        try:
            try:
                ctx = self._run_stages(ctx)
            except Exception as exc:  # noqa: BLE001 - deliberate catch-all
                ctx.disposition = "dead_letter"
                ctx.skip_reason = str(exc)
                ctx.review_flag = True
                ctx.log(f"dead_letter: {type(exc).__name__}: {exc}")

            record = self._emit(ctx)
            self._emitted += 1
            ctx.emitted = True
            return record
        finally:
            # Whatever happened above - processed, dead-lettered, or emit
            # itself degraded - a non-PDF input converted at Stage 2
            # (`extract.convert`) leaves its `mkdtemp()` directory on
            # `ctx.temp_dirs`, and nothing downstream of this method ever
            # reads it again. Removing it here, unconditionally, is the one
            # place that is guaranteed to run for every document this Runner
            # ever processes.
            for directory in ctx.temp_dirs:
                shutil.rmtree(directory, ignore_errors=True)

    def _emit(self, ctx: JobContext) -> dict[str, Any]:
        """Build and validate the record, degrading rather than raising.

        Subtle but load-bearing: if validation raised out of process(), the
        caller would get an exception instead of a record while the emitted
        counter had already been bumped — so the invariant this class exists to
        guarantee would silently become a lie. A record that cannot be validated
        is itself a dead letter, not an exception.
        """
        try:
            identity = ctx.derived.get("document_identity")
            # Looked up, not yet committed: `peek` is a plain dict `.get` over
            # already-typed keys, so - like the old single-call `see` this
            # replaced - it cannot raise. That protects the invariant, but it
            # is not by itself a correctness guarantee; the answer only
            # becomes permanent below, once it is proven to belong to a
            # record that actually ships. `document_id` is passed through so
            # a replay of this same document is never read as a duplicate of
            # itself (see `IdentityIndex.peek`).
            #
            # Set BEFORE `beforeEmit` runs, not after: that hook is the only
            # extension point that exists this close to emit (stage 7 has
            # already returned), so a pack hook that wants to react to a
            # possible duplicate - e.g. to raise `review_flag` - can only ever
            # observe the field if it is on `ctx` before the hook fires.
            ctx.possible_duplicate_of = self._identity_index.peek(ctx.document_id, identity)
            ctx = self.hooks.run("beforeEmit", ctx)
            record = build_record(ctx)
            validate_record(record)
            # Committed only now that `record` is proven buildable and valid.
            # Committing at lookup time would let a document that goes on to
            # dead-letter HERE still claim the identity slot forever, even
            # though `_minimal_dead_letter` rebuilds its record from a fresh,
            # empty context that carries no trace of that identity - a later
            # document told "duplicate of this one" would then point at a
            # record with no corroborating evidence at all (review finding on
            # this module's first version).
            #
            # Re-read fresh here rather than reusing the pre-hook `identity`
            # local: `build_record` above already reads `ctx.derived` fresh,
            # so if a `beforeEmit` hook mutates `document_identity`, the
            # committed value must match what the record just shipped with -
            # not the stale value `peek` used before the hook ran.
            self._identity_index.commit(ctx.document_id, ctx.derived.get("document_identity"))
            return record
        except Exception as exc:  # noqa: BLE001 - deliberate catch-all
            ctx.log(f"emit failed, degrading: {exc}")
            return self._minimal_dead_letter(ctx.document_id, str(exc))

    @staticmethod
    def _minimal_dead_letter(document_id: str, reason: str) -> dict[str, Any]:
        """The last-resort record. Built from a fresh context so no field
        polluted by a partially-run pipeline can make it fail validation too."""
        fallback = new_context(document_id=document_id, source_path="")
        fallback.disposition = "dead_letter"
        fallback.skip_reason = f"contract validation failed: {reason}"
        fallback.review_flag = True
        record = build_record(fallback)
        validate_record(record)
        return record

    def _run_stages(self, ctx: JobContext) -> JobContext:
        for stage in self.stages:
            before = HOOKS_BEFORE.get(stage.name)
            if before is not None:
                ctx = self.hooks.run(before, ctx)

            ctx = self._run_one(stage, ctx)

            # The after-socket runs before the disposition check so a pack can
            # observe - or react to - a skip the base pipeline just decided.
            after = HOOKS_AFTER.get(stage.name)
            if after is not None:
                ctx = self.hooks.run(after, ctx)

            if ctx.disposition != "processed":
                break
        return ctx

    def _run_one(self, stage: Stage, ctx: JobContext) -> JobContext:
        attempts = self.max_retries + 1
        last: Exception | None = None
        for _ in range(attempts):
            try:
                result = stage.run(ctx)
            except TransientError as exc:
                last = exc
                continue
            if not isinstance(result, JobContext):
                raise TypeError(f"stage {stage.name!r} must return a JobContext")
            return result
        if last is None:  # unreachable for max_retries >= 0, but not via assert:
            raise RuntimeError(  # `python -O` strips asserts, and this is control flow
                f"stage {stage.name!r} exhausted retries without a result"
            )
        raise last
