"""Server-callable generation tools - a first draft, never a finished answer.

Everything here produces a candidate a human reviews before it affects any
real document. Nothing in this package writes into a pack's `personas/`
directory, changes `registry.PACK_MODULES`, or is reachable from the real
processing pipeline (`pipeline.stages.build_pipeline`) at all - it is a
separate, offline tool a reviewer runs deliberately.
"""

from __future__ import annotations
