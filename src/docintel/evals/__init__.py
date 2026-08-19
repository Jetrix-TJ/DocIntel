"""Everything an eval needs beyond `docintel.scorecard`'s own read-only scoring:

persisting a run over time (`history`), turning human review corrections into
new gold data (`corrections`), and diffing two stored runs (`compare`).
"""

from __future__ import annotations
