"""Per-carrier billing conventions — the F1b keystone for this pack.

**DEFERRED (printed-fields-only): nothing calls this.** `apply_billing_conventions`
is registered at no socket in either pack, so every present-tense statement below
describes what this module WOULD do, not what the pipeline does. Kept on disk
because re-enabling is a wiring change; see
`docs/superpowers/specs/2026-07-28-printed-fields-only-design.md` section 5.

Note that `ladder.retag_prior_balance` is NOT in the same state: it was
unregistered alongside this and has been re-wired against printed amounts, so the
prior-balance TAG pair is live again even though `prior_balance_basis` is not.

`prior_balance_basis` decides what a printed prior balance *means*, and the pack
spec's section 7 table makes the split explicit:

```
Centracom   net_of_payments   its printed prior is ALREADY net of a $24,120.20 payment
Comcast     gross             prints a gross prior alongside a signed credit that zeroes it
Windstream  gross             same
Lumen       gross             same
```

**One formula cannot serve both.** Reading Centracom's net prior as gross
subtracts its payment a second time; reading the other three's gross prior as net
carries a paid-off balance forward. F1b therefore refuses to guess, and this table
is how the question becomes answerable.

Nothing on any of these pages states its own convention, which is why this is pack
code and not a selector. See `packs.northstar.conventions` for the fuller argument
about why it is deliberately not a grammar feature.
"""

from __future__ import annotations

from docintel.core.models import JobContext
from docintel.packs.digitaldirection import aliases
from docintel.packs.registry import primary_text

PRIOR_BALANCE_BASIS: dict[str, str] = {
    "centracom": "net_of_payments",
    "comcast": "gross",
    "windstream": "gross",
    "lumen": "gross",
}


def apply_prior_balance_basis(ctx: JobContext) -> JobContext:
    """Supply `prior_balance_basis` from the carrier's known convention (F1b)."""
    if ctx.extracted.get("prior_balance") is None:
        return ctx
    if ctx.extracted.get("prior_balance_basis") is not None:
        return ctx

    carrier = aliases.canonical(primary_text(ctx))
    basis = PRIOR_BALANCE_BASIS.get(carrier or "")
    if basis is None:
        ctx.log(
            f"s6: no prior-balance convention recorded for carrier {carrier!r}; "
            "the carried balance will not be guessed (F1b)"
        )
        return ctx

    ctx.extracted.set("prior_balance_basis", basis, 1.0)
    ctx.log(f"s6: prior_balance_basis {basis!r} from the {carrier!r} billing convention")
    return ctx
