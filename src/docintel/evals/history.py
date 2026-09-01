"""Persist an eval scorecard over time.

`scorecard.replay_gold()` (and, later, the isolated gate/vision suites) each
compute a rich dict and hand it back to a caller that used to just print it
and let it evaporate. Nothing else this project wants from an eval layer -
"did we get better or worse than last time," a champion/challenger diff, a CI
gate - can be built honestly without a prior run to compare against. This
module is that prior run.

Same shape as `docintel.jobs.store`: one dataclass, one schema string, a
fresh connection per call (safe to share across threads with no pooling
layer), a migration check in `_init_schema()` for an on-disk file that
predates a later column. `suite` is a first-class column from day one even
though only `"full_pipeline"` exists until the isolated suites land, so that
addition is not itself a schema migration.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from docintel.paths import state_root


def _default_db_path() -> str:
    """Final fallback when neither an explicit `path` nor
    `DOCINTEL_EVAL_HISTORY_DB` is given: `state_root() / "eval_history.sqlite3"`
    (`state_root()` itself honors `DOCINTEL_STATE_DIR`, else `var`, matching the
    historical hardcoded default this replaced).

    A function, not the `"var/eval_history.sqlite3"` constant it replaced, so
    the root is resolved per call: a module-level constant would freeze
    whatever `DOCINTEL_STATE_DIR`/CWD looked like at import time. Same shape as
    `jobs.store._default_db_path`.
    """
    return str(state_root() / "eval_history.sqlite3")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    suite TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    vision_mode TEXT NOT NULL,
    run_at TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    documents_json TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class EvalRun:
    id: int
    suite: str
    label: str
    vision_mode: str
    run_at: str
    summary: dict[str, Any]
    documents: list[dict[str, Any]]

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> EvalRun:
        return cls(
            id=row["id"],
            suite=row["suite"],
            label=row["label"],
            vision_mode=row["vision_mode"],
            run_at=row["run_at"],
            summary=json.loads(row["summary_json"]),
            documents=json.loads(row["documents_json"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "suite": self.suite,
            "label": self.label,
            "vision_mode": self.vision_mode,
            "run_at": self.run_at,
            "summary": self.summary,
            "documents": self.documents,
        }


def _now() -> str:
    return datetime.now(UTC).isoformat()


class EvalHistoryStore:
    """One SQLite file, one table, opened fresh per call - see this module's
    own docstring and `docintel.jobs.store` for why."""

    def __init__(self, path: str | Path | None = None) -> None:
        resolved = path or os.environ.get("DOCINTEL_EVAL_HISTORY_DB") or _default_db_path()
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

    def record(
        self, suite: str, label: str, vision_mode: str, card: dict[str, Any]
    ) -> int:
        """Store one scorecard. Stores the entire card, not just the summary,
        so a later diff (see `docintel.evals.compare`) can name the exact
        gold_id/assertion that flipped, not just report a changed total."""
        conn = self._connect()
        try:
            with conn:
                cursor = conn.execute(
                    "INSERT INTO eval_runs "
                    "(suite, label, vision_mode, run_at, summary_json, documents_json) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        suite, label, vision_mode, _now(),
                        json.dumps(card["summary"]), json.dumps(card["documents"]),
                    ),
                )
                assert cursor.lastrowid is not None
                return cursor.lastrowid
        finally:
            conn.close()

    def get(self, run_id: int) -> EvalRun | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM eval_runs WHERE id = ?", (run_id,)
            ).fetchone()
        finally:
            conn.close()
        return EvalRun._from_row(row) if row is not None else None

    def latest(self, suite: str, label: str | None = None) -> EvalRun | None:
        query = "SELECT * FROM eval_runs WHERE suite = ?"
        params: list[Any] = [suite]
        if label is not None:
            query += " AND label = ?"
            params.append(label)
        query += " ORDER BY id DESC LIMIT 1"
        conn = self._connect()
        try:
            row = conn.execute(query, params).fetchone()
        finally:
            conn.close()
        return EvalRun._from_row(row) if row is not None else None

    def history(self, suite: str, limit: int = 20) -> list[EvalRun]:
        """The trend query - oldest to newest, within the last `limit` runs."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM eval_runs WHERE suite = ? ORDER BY id DESC LIMIT ?",
                (suite, limit),
            ).fetchall()
        finally:
            conn.close()
        return [EvalRun._from_row(row) for row in reversed(rows)]

    def find(self, suite: str, label_or_id: str) -> EvalRun | None:
        """Resolve a run by numeric id (as a string) or by label - the latest
        run under that label if more than one shares it. Used by
        `docintel eval-compare`, which takes either shape on the command
        line."""
        if label_or_id.isdigit():
            run = self.get(int(label_or_id))
            if run is not None and run.suite == suite:
                return run
            return None
        return self.latest(suite, label=label_or_id)
