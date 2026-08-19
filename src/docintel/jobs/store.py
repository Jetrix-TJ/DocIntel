"""A real queue for the two escalation paths that used to be silent.

`AgentEscalation` (s5c) and `ConfidenceGate` (s7) each find a document they
cannot resolve on their own: a sender with no persona at all, or a prior
balance whose basis ("gross" vs "net_of_payments") no pack convention has
recorded yet. Before this module, both paths only set `review_flag` and
logged a line - nothing was ever enqueued, because nothing existed to enqueue
into.

SQLite, not a message broker: this queue serves one reviewer-facing web UI,
not a distributed system, and the stdlib driver means zero new dependency.
The `UNIQUE(kind, sender_fingerprint, doc_type, match_key)` index does the
single-flight work `enqueue_once` promises.

`match_key` defaults to `''`, never `NULL` - SQLite treats `NULL`s as
mutually distinct in a unique index, so a `NULL` default would silently
*break* single-flight instead of preserving it. For `persona_authoring` and
`prior_balance_basis`, every row shares the same `''`, so those two kinds are
still single-flight per `(kind, sender_fingerprint, doc_type)` exactly as
before - a second document from the same unresolved sender is a duplicate of
the same open question, not a second job. A `contract_reconciliation` finding
(reconciliation.findings) is the reason the column exists at all: two
different invoices under the same carrier can each raise their own
`rate_mismatch`, and single-flighting those on vendor/doc_type alone would
collapse the second one into the first, silently dropping it. Passing
`match_key=invoice_document_id` there keeps each invoice's finding distinct.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = "var/jobs.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    sender_fingerprint TEXT NOT NULL,
    doc_type TEXT,
    match_key TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    context_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolved_by TEXT,
    resolution_json TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_single_flight
    ON jobs (kind, sender_fingerprint, doc_type, match_key);
"""


@dataclass(frozen=True)
class Job:
    id: int
    kind: str
    sender_fingerprint: str
    doc_type: str | None
    status: str
    context: dict[str, Any]
    created_at: str
    match_key: str = ""
    resolved_at: str | None = None
    resolved_by: str | None = None
    resolution: dict[str, Any] | None = None

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> "Job":
        return cls(
            id=row["id"],
            kind=row["kind"],
            sender_fingerprint=row["sender_fingerprint"],
            doc_type=row["doc_type"],
            status=row["status"],
            context=json.loads(row["context_json"]),
            created_at=row["created_at"],
            match_key=row["match_key"],
            resolved_at=row["resolved_at"],
            resolved_by=row["resolved_by"],
            resolution=(
                json.loads(row["resolution_json"])
                if row["resolution_json"] is not None
                else None
            ),
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteJobQueue:
    """One SQLite file, one table, opened fresh per call.

    Opening a new connection per method call (rather than holding one open)
    keeps this safe to share across the Flask app's request threads without
    a connection-pooling layer this project doesn't otherwise need.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        resolved = path or os.environ.get("DOCINTEL_JOBS_DB") or DEFAULT_DB_PATH
        self.path = Path(resolved)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        # `sqlite3.Connection` used as a context manager only commits/rolls
        # back on exit - it does NOT close the connection. Every method here
        # closes explicitly in `finally`, or the file stays locked (fatal on
        # Windows, where a still-open handle blocks even deleting the file).
        conn = self._connect()
        try:
            with conn:
                conn.executescript(_SCHEMA)
                # Migration: `_SCHEMA`'s CREATE TABLE is a no-op against an
                # on-disk file that predates `match_key` - ALTER it in
                # explicitly, so an existing var/jobs.sqlite3 keeps working
                # rather than needing a manual reset. SQLite can't ALTER an
                # index in place, so the single-flight index is dropped and
                # recreated against the widened column set.
                cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
                if "match_key" not in cols:
                    conn.execute(
                        "ALTER TABLE jobs ADD COLUMN match_key TEXT NOT NULL DEFAULT ''"
                    )
                    conn.execute("DROP INDEX IF EXISTS jobs_single_flight")
                    conn.execute(
                        "CREATE UNIQUE INDEX jobs_single_flight "
                        "ON jobs (kind, sender_fingerprint, doc_type, match_key)"
                    )
        finally:
            conn.close()

    def enqueue_once(
        self,
        sender_fingerprint: str,
        doc_type: str | None,
        kind: str,
        context: dict[str, Any] | None = None,
        match_key: str = "",
    ) -> bool:
        """Insert a new open job unless one already exists for this key.

        Returns True when this call created the job, False when it was
        already queued - the caller (a pipeline stage) never needs to know
        which, but tests do.

        `match_key` defaults to `''` - existing callers (`AgentEscalation`,
        `ConfidenceGate`) never pass it, so their single-flight behavior is
        unchanged. A caller that needs finer single-flight than
        `(kind, sender_fingerprint, doc_type)` alone - reconciliation findings,
        one per invoice - passes a real one; see this module's own docstring.
        """
        conn = self._connect()
        try:
            with conn:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO jobs "
                    "(kind, sender_fingerprint, doc_type, match_key, status, "
                    "context_json, created_at) VALUES (?, ?, ?, ?, 'open', ?, ?)",
                    (
                        kind, sender_fingerprint, doc_type, match_key,
                        json.dumps(context or {}), _now(),
                    ),
                )
                return cursor.rowcount > 0
        finally:
            conn.close()

    def list_open(self, kind: str | None = None) -> list[Job]:
        query = "SELECT * FROM jobs WHERE status = 'open'"
        params: tuple[Any, ...] = ()
        if kind is not None:
            query += " AND kind = ?"
            params = (kind,)
        query += " ORDER BY created_at ASC"
        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()
        return [Job._from_row(row) for row in rows]

    def get(self, job_id: int) -> Job | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        finally:
            conn.close()
        return Job._from_row(row) if row is not None else None

    def resolve(
        self, job_id: int, resolution: dict[str, Any], resolved_by: str
    ) -> None:
        """Mark a job resolved. Does not itself change any pack convention -

        writing the actual decision (e.g. a prior_balance_basis overlay entry)
        is the caller's job, deliberately kept separate so this queue never
        needs to know what a "resolution" means for any given job kind.
        """
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "UPDATE jobs SET status = 'resolved', resolved_at = ?, "
                    "resolved_by = ?, resolution_json = ? WHERE id = ?",
                    (_now(), resolved_by, json.dumps(resolution), job_id),
                )
        finally:
            conn.close()
