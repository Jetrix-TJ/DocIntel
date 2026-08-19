"""Where a human's correction to an escalated document actually goes.

The correction-return contract this project's own architecture doc names
(`docs/architecture/pipeline-v2.md:465-481`) has two halves: capture (the
webui's `/review/<job_id>/correct` route, plus the `record_snapshot` context
`AgentEscalation` now attaches) and promotion (`docintel promote-correction`,
which turns an accepted correction into a real `docs/corpus/gold/*.json`
fixture). This module is the storage between the two - same SQLite-via-
stdlib pattern as `docintel.jobs.store`.

Promotion into the *scored* gold set is deliberately NOT automatic here -
`scorecard.py`'s own docstring says it never writes to the gold set, and that
invariant is worth keeping: a silent auto-promotion pipeline would let one
reviewer's mistake corrupt the ground truth the whole eval is scored against.
A correction's arrival (`add`) is automatic; its acceptance into gold
(`docintel promote-correction`, a human-run command) is a reviewed gate.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = "var/corrections.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    document_id TEXT NOT NULL,
    source_path TEXT NOT NULL,
    original_record_json TEXT NOT NULL,
    corrected_fields_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_promotion',
    corrected_by TEXT NOT NULL,
    corrected_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Correction:
    id: int
    job_id: int | None
    document_id: str
    source_path: str
    original_record: dict[str, Any]
    corrected_fields: dict[str, Any]
    status: str
    corrected_by: str
    corrected_at: str

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> Correction:
        return cls(
            id=row["id"],
            job_id=row["job_id"],
            document_id=row["document_id"],
            source_path=row["source_path"],
            original_record=json.loads(row["original_record_json"]),
            corrected_fields=json.loads(row["corrected_fields_json"]),
            status=row["status"],
            corrected_by=row["corrected_by"],
            corrected_at=row["corrected_at"],
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()


class CorrectionStore:
    """One SQLite file, one table, opened fresh per call - see this module's
    own docstring and `docintel.jobs.store` for why."""

    def __init__(self, path: str | Path | None = None) -> None:
        resolved = path or os.environ.get("DOCINTEL_CORRECTIONS_DB") or DEFAULT_DB_PATH
        self.path = Path(resolved)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            with conn:
                conn.executescript(_SCHEMA)
        finally:
            conn.close()

    def add(
        self,
        document_id: str,
        source_path: str,
        original_record: dict[str, Any],
        corrected_fields: dict[str, Any],
        corrected_by: str,
        job_id: int | None = None,
    ) -> int:
        """Record one reviewer decision - `corrected_fields` is `{}` for a
        pure "confirmed clean, no changes" confirmation, or `{field: value}`
        for an edit. Both are useful signal; only the second changes anything
        once promoted."""
        conn = self._connect()
        try:
            with conn:
                cursor = conn.execute(
                    "INSERT INTO corrections "
                    "(job_id, document_id, source_path, original_record_json, "
                    "corrected_fields_json, corrected_by, corrected_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        job_id, document_id, source_path,
                        json.dumps(original_record), json.dumps(corrected_fields),
                        corrected_by, _now(),
                    ),
                )
                assert cursor.lastrowid is not None
                return cursor.lastrowid
        finally:
            conn.close()

    def get(self, correction_id: int) -> Correction | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM corrections WHERE id = ?", (correction_id,)
            ).fetchone()
        finally:
            conn.close()
        return Correction._from_row(row) if row is not None else None

    def list_pending(self) -> list[Correction]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM corrections WHERE status = 'pending_promotion' "
                "ORDER BY corrected_at ASC"
            ).fetchall()
        finally:
            conn.close()
        return [Correction._from_row(row) for row in rows]

    def mark_promoted(self, correction_id: int) -> None:
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "UPDATE corrections SET status = 'promoted' WHERE id = ?",
                    (correction_id,),
                )
        finally:
            conn.close()
