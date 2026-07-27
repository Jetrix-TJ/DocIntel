"""Stage 1: catch the document, keep everything. Nothing is ever discarded here."""

from __future__ import annotations

import hashlib
import os

from docintel.core.models import JobContext


class Intake:
    name = "intake"

    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("s1: intake")
        # Soft fingerprint: clusters likely duplicates, never rejects them.
        try:
            size = os.path.getsize(ctx.source_path)
        except OSError:
            size = -1
        basename = os.path.basename(ctx.source_path)
        ctx.derived.set(
            "soft_fingerprint",
            hashlib.sha256(f"{ctx.sender_email}|{basename}|{size}".encode()).hexdigest()[:16],
        )
        return ctx
