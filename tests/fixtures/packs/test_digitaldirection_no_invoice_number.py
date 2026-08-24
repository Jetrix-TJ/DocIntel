"""`no_invoice_number` is a statement about what extraction FOUND.

Specified in `docs/packs/digital-direction.md` for three of the four carriers
since the pack spec was written, and never implemented - it is 3 of the 4
failing gold `tags` assertions.

It cannot be computed in `tags_for`, because Stage 3 runs before extraction and
therefore cannot know what was found. The retag socket exists for exactly this
shape (`retag_prior_balance`, `beforeConfidenceGate`) and had been used once.

**The tag is honest, which was verified before implementing it rather than
assumed.** Measured 2026-08-07 with a regex covering `Invoice|Bill|Statement|
Document Number` and its abbreviations, over every page:

| document | invoice-number label |
|---|---|
| Lumen | `Invoice Number 752233001`, page 1, a 3-word line |
| Centracom | 0 matching lines |
| Comcast | 0 matching lines |
| Windstream | 0 matching lines |

So `no_invoice_number` means "this carrier does not print one", not "nobody
wrote a selector". Lumen's selector already exists in `personas/lumen.json` and
already passes gold, which is what makes the distinction real.
"""

from __future__ import annotations

from docintel.core.models import new_context
from digitaldirection.ladder import retag_missing_invoice_number


def _ctx(invoice_number: object = None):
    ctx = new_context("d", "/x.pdf")
    ctx.doc_type = "telecom_bill"
    if invoice_number is not None:
        ctx.extracted.set("invoice_number", invoice_number, 0.95)
    return ctx


def test_tags_when_no_invoice_number_was_extracted() -> None:
    assert "no_invoice_number" in retag_missing_invoice_number(_ctx()).tags


def test_does_not_tag_when_one_was_extracted() -> None:
    assert "no_invoice_number" not in retag_missing_invoice_number(_ctx("752233001")).tags


def test_an_empty_value_counts_as_missing() -> None:
    """A selector that matched its anchor and captured nothing has not found an
    invoice number, and the record must not imply that it did."""
    assert "no_invoice_number" in retag_missing_invoice_number(_ctx("   ")).tags


def test_is_idempotent() -> None:
    ctx = retag_missing_invoice_number(retag_missing_invoice_number(_ctx()))
    assert ctx.tags.count("no_invoice_number") == 1


def test_the_retag_is_actually_wired_into_the_pipeline() -> None:
    """The half the unit tests above cannot see.

    Directly modelled on `test_the_refinement_is_actually_wired_into_the_pipeline`
    in `test_digitaldirection_ladder.py`, and for the same reason it was written:
    `retag_prior_balance` was correct code the whole time it was unregistered, and
    every unit test of it passed while the pipeline shipped the unrefined guess.
    This is the same shape at the same socket, so the wiring is pinned too.
    """
    from digitaldirection import PACK
    from docintel.packs.registry import register_all
    from docintel.pipeline.hooks import HookRegistry

    registry = HookRegistry()
    register_all(registry, packs=[PACK])
    assert (
        "digitaldirection.refine_invoice_number_tag"
        in registry.registered("beforeConfidenceGate")
    ), (
        "nothing emits no_invoice_number, so three carriers' records silently omit "
        "a fact the pack spec requires - see this module's docstring"
    )
