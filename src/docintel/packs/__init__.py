"""Domain packs.

A pack is everything about one customer's document domain that the pipeline
itself must not know: which document types exist, which fields matter, what the
vendor names collapse to, and where the confidence bar sits. The pipeline stays
generic; the pack carries the judgement.

Packs reach the pipeline through two seams and no others - the `HookRegistry`
sockets, and the `Pack` protocol in `registry`. A pack that needed to import a
stage would be a pack that has escaped its boundary.
"""

from __future__ import annotations
