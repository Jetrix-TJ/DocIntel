"""Invoice <-> contract reconciliation.

Deliberately NOT a pipeline stage. `Runner.process()` handles exactly one
document and returns exactly one record; the only cross-document state
anywhere in the pipeline (`core.duplicates.IdentityIndex`) is a narrow
single-run dedup dict that carries no field data. There is no seam to hook a
two-document comparison into mid-pipeline, so this is new infrastructure: a
second pass over already-emitted records (the same shape `cli.py::_cmd_process`
already uses to drive `Runner.process()` in a loop), not a stage inside it.

Scope stops at a finding landing in the same human-review queue
`docintel.jobs`/`docintel.webui.app` already serve - no payment scheduling,
no approval workflow, no AP/payment-system integration of any kind.
"""

from docintel.reconciliation.findings import Finding, enqueue, evaluate
from docintel.reconciliation.match import MatchResult, resolve

__all__ = ["Finding", "MatchResult", "enqueue", "evaluate", "resolve"]
