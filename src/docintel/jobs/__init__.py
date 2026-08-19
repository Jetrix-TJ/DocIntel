"""Human-in-the-loop job queue.

Stage 5c (`AgentEscalation`) and Stage 7 (`ConfidenceGate`) enqueue into this
queue instead of guessing; a reviewer resolves what lands here through the web
UI. See `docintel.jobs.store.SQLiteJobQueue`.
"""

from __future__ import annotations

from docintel.jobs.store import Job, SQLiteJobQueue

__all__ = ["Job", "SQLiteJobQueue"]
