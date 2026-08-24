"""Stage 5c: escalate. Enqueue ONE rule-writing job per persona key, async.

Rule authoring itself (a human deciding a whole new persona's selectors) is
still out of scope for this build. What changed: the queue is real now
(`docintel.jobs.store.SQLiteJobQueue`), so a hard miss actually lands
somewhere a reviewer can see it, instead of only setting a flag and logging
a line no one reads.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from docintel.core.models import JobContext

WEAK = 0.60


def _json_safe(value: Any) -> Any:
    """Decimal isn't JSON-serializable; everything else here already is."""
    return format(value, "f") if isinstance(value, Decimal) else value


def _record_snapshot(ctx: JobContext) -> dict[str, Any]:
    """What was extracted so far, carried on the job so a reviewer correcting
    it later (`docintel.evals.corrections`) has something to correct against.
    A snapshot, not a live reference - the job may sit open for a while and
    `ctx` itself is never persisted (same reasoning as s7_gate's own
    `_BASIS_CONTEXT_FIELDS` snapshot, one stage over).

    `classification` is its own sub-dict, shaped like a gold fixture's own
    `classification` block (`docs/corpus/README.md`), not flattened alongside
    `fields`/`derived` - `docintel promote-correction` needs exactly this
    shape to write a real `docs/corpus/gold/*.json` file later.
    """
    return {
        "document_id": ctx.document_id,
        "source_path": ctx.source_path,
        "sender_fingerprint": ctx.sender_fingerprint,
        "classification": {
            "doc_type": ctx.doc_type,
            "tags": list(ctx.tags),
            "text_source": ctx.text_source,
            "page_count": len(ctx.pages),
            "page_roles": [m.role for m in ctx.page_meta],
        },
        "fields": {name: _json_safe(v) for name, v in ctx.extracted.values.items()},
        "derived": {name: _json_safe(v) for name, v in ctx.derived.values.items()},
    }


class AgentEscalation:
    name = "agent_escalation"

    def __init__(self, jobs: object | None = None) -> None:
        self.jobs = jobs

    def run(self, ctx: JobContext) -> JobContext:
        if ctx.persona_status != "hard_miss":
            return ctx
        confidences = list(ctx.extracted.match_quality.values())
        confident = bool(confidences) and min(confidences) >= WEAK
        # WEAK gates the QUEUE ENTRY only, never the review flag below: it
        # answers "does a human need to author a new persona", not "does a
        # human need to see this document". A confident one-shot result still
        # needs no new rules, but self-reported vision confidence is a
        # transcription-certainty signal, not a correctness one - it must
        # never be read as "this document has been reviewed".
        if not confident:
            ctx.log("s5c: agent_escalation (job queued, authoring deferred)")
            if self.jobs is not None:
                self.jobs.enqueue_once(  # type: ignore[attr-defined]
                    ctx.sender_fingerprint,
                    ctx.doc_type,
                    kind="persona_authoring",
                    context={"record_snapshot": _record_snapshot(ctx)},
                )
        else:
            ctx.log("s5c: agent_escalation (confident one-shot result, no rule-authoring job queued)")
        # A review flag, NOT a regen flag, and unconditional on confidence.
        # Spec Part 3 "First-time": a hard miss "emits anyway with the
        # one-shot result and a review flag". regen_flag means "the rules are
        # wrong" (Stage 7, Very Low lane) — but a first-time sender has no
        # rules yet, so a regen flag here would send a downstream consumer
        # looking for a regeneration that cannot exist. Stage 7 is the sole
        # writer of regen_flag, so the two never disagree.
        ctx.review_flag = True
        return ctx
