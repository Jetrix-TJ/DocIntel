"""Stage sequencing plus the emit-always guarantee.

count(intaken) == count(emitted) is spec Stage 8's machine-checkable promise.
Rather than trusting every code path to remember, process() wraps each document
so that any escape route - unhandled exception, retry exhaustion, a pack hook
throwing - still produces a record.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Protocol

from docintel.core.contract import build_record, validate_record
from docintel.core.errors import TransientError
from docintel.core.models import JobContext, new_context
from docintel.pipeline.hooks import HookRegistry


class Stage(Protocol):
    name: str

    def run(self, ctx: JobContext) -> JobContext: ...


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

    def _emit(self, ctx: JobContext) -> dict[str, Any]:
        """Build and validate the record, degrading rather than raising.

        Subtle but load-bearing: if validation raised out of process(), the
        caller would get an exception instead of a record while the emitted
        counter had already been bumped — so the invariant this class exists to
        guarantee would silently become a lie. A record that cannot be validated
        is itself a dead letter, not an exception.
        """
        try:
            record = build_record(ctx)
            validate_record(record)
            return record
        except Exception as exc:  # noqa: BLE001 - deliberate catch-all
            ctx.log(f"contract validation failed, degrading: {exc}")
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
            ctx = self._run_one(stage, ctx)
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
        assert last is not None
        raise last
