"""Structured, persisted, per-document production signal.

Distinct from the offline gold-corpus eval (`docintel.scorecard`,
`docintel.evals`): this is what happened on LIVE traffic, not a fixed
labelled set. `ctx.log(...)` (`core/models.py`) only ever appends to an
in-memory list that rides along on the emitted record's own JSON
(`core/contract.py`'s `"events"` key) - nothing aggregates it across a run,
let alone across runs, and `_cmd_process`'s disposition `Counter` is printed
once to stdout and forgotten (`docs/BUGS-FEATURES-PRODUCTION.md`'s Production
Plan item 4 names this gap directly).

Minimal real version for a single-operator CLI tool, not a hosted service:
stdlib `logging` (zero new dependency), one compact JSON line per processed
document, to a rotating file a human can tail or `jq` through. Not a metrics
stack, not push alerting - there is no on-call process yet to receive one,
so `docintel queue-status`'s exit code is the honest minimum: poll it from
cron/Task Scheduler if you want to be told when the review queue backs up.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

DEFAULT_LOG_PATH = "var/logs/docintel.jsonl"

_LOGGER_NAME = "docintel.telemetry"


class _RawLineFormatter(logging.Formatter):
    """The log record's message IS the JSON line - no timestamp/level prefix
    `logging` would otherwise add, since every field a `jq` query would want
    is already inside the JSON payload itself."""

    def format(self, record: logging.LogRecord) -> str:
        return record.getMessage()


def configure(path: str | None = None) -> logging.Logger:
    """Attach a fresh rotating-file handler, replacing any previous one.

    Safe to call more than once - each call fully replaces prior handlers
    rather than accumulating duplicates, which matters for tests that
    reconfigure against a different tmp path per test. `path` defaults to
    `DOCINTEL_TELEMETRY_LOG` if set, then `DEFAULT_LOG_PATH` - the same
    override convention `jobs.store`/`evals.history` already use.
    """
    resolved = path or os.environ.get("DOCINTEL_TELEMETRY_LOG") or DEFAULT_LOG_PATH
    logger = logging.getLogger(_LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    directory = os.path.dirname(resolved)
    if directory:
        os.makedirs(directory, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        resolved, maxBytes=10 * 1024 * 1024, backupCount=5,
    )
    handler.setFormatter(_RawLineFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def log_record(record: dict[str, Any], elapsed_ms: float | None = None) -> None:
    """One JSON line for one emitted record - the fields an operator would
    actually grep/jq for a trend, not the full record (that's already on
    disk if `--json` was used). Auto-configures against the default path on
    first use, exactly like a logger that was never explicitly set up still
    works via `logging`'s own root handler convention.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        configure()
        logger = logging.getLogger(_LOGGER_NAME)

    confidence = record.get("confidence") or {}
    payload = {
        "logged_at": datetime.now(UTC).isoformat(),
        "document_id": record.get("document_id"),
        "disposition": record.get("disposition"),
        "lane": record.get("lane"),
        "doc_type": record.get("doc_type"),
        "sender_fingerprint": record.get("sender_fingerprint"),
        "review_flag": record.get("review_flag"),
        "regen_flag": record.get("regen_flag"),
        "extraction_route": record.get("extraction_route"),
        "mean_confidence": (
            round(sum(confidence.values()) / len(confidence), 4) if confidence else None
        ),
    }
    if elapsed_ms is not None:
        payload["elapsed_ms"] = round(elapsed_ms, 1)
    logger.info(json.dumps(payload, separators=(",", ":")))


def _read_lines(path: str) -> list[dict[str, Any]]:
    """Every well-formed line in the log, skipping any that aren't.

    A log file is not a fixed corpus: a process killed mid-write, or a read
    racing an in-progress append, can leave a truncated trailing line. One
    bad line must not make `aggregate()` blind to every other line already
    on disk - skip it and keep going, the same posture `evals.vision_eval`/
    `evals.gate_eval` take toward a single document's failure.
    """
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def aggregate(path: str | None = None, since_days: float | None = None) -> dict[str, Any]:
    """Dead-letter rate, escalation rate (`5b_vision` route share), and mean
    confidence across whatever `log_record` has written - the trend view
    `docintel telemetry-report` prints. `path` resolves the same way
    `configure()`'s does: given path, then `DOCINTEL_TELEMETRY_LOG`, then
    `DEFAULT_LOG_PATH`.
    """
    resolved = path or os.environ.get("DOCINTEL_TELEMETRY_LOG") or DEFAULT_LOG_PATH
    entries = _read_lines(resolved)
    if since_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=since_days)
        entries = [
            e for e in entries
            if e.get("logged_at") and datetime.fromisoformat(e["logged_at"]) >= cutoff
        ]

    total = len(entries)
    dispositions: Counter[str] = Counter(e.get("disposition") or "unknown" for e in entries)
    routes: Counter[str] = Counter(
        e["extraction_route"] for e in entries if e.get("extraction_route")
    )
    confidences = [e["mean_confidence"] for e in entries if e.get("mean_confidence") is not None]

    return {
        "total": total,
        "dispositions": dict(dispositions),
        "routes": dict(routes),
        "dead_letter_rate": round(dispositions.get("dead_letter", 0) / total, 4) if total else 0.0,
        "escalation_rate": round(routes.get("5b_vision", 0) / total, 4) if total else 0.0,
        "mean_confidence": (
            round(sum(confidences) / len(confidences), 4) if confidences else None
        ),
    }
