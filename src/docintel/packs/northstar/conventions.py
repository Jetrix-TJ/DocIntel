"""Per-vendor billing conventions — facts about the VENDOR, not the document.

One entry so far, and it is the F1b keystone.

`prior_balance_basis` decides what a printed prior balance *means*, and the two
readings produce opposite errors (`resolve_carried_balance`): reading a gross
balance as net carries a paid-off amount forward, and reading a net balance as
gross subtracts a payment twice. F1b therefore refuses to guess — a missing basis
is a review flag.

No selector can supply it, because it is not printed anywhere. EDCO's invoice says
"THIS INVOICE INCLUDES PAYMENTS RECEIVED BY 04/23/25" and prints no payment line;
that its `BALANCE FORWARD` is carried in full is a fact about how EDCO bills,
learned once by whoever read the invoice against the remittance history. That is
precisely what a pack is for.

Deliberately NOT a grammar feature. Adding a "literal value" selector kind would
let a rule agent write arbitrary constants into any field, which is a much larger
hole than one hand-maintained table per pack. A wrong entry here is a reviewed
code change; a wrong constant in a persona would be an agent write.
"""

from __future__ import annotations

from docintel.core.models import JobContext
from docintel.packs.northstar import aliases
from docintel.packs.registry import primary_text

# canonical vendor -> "gross" | "net_of_payments"
PRIOR_BALANCE_BASIS: dict[str, str] = {
    # BALANCE FORWARD is carried in full; payments received through the stated
    # date are already reflected in it and no separate payment line is printed.
    "edco": "gross",
}


def apply_prior_balance_basis(ctx: JobContext) -> JobContext:
    """Supply `prior_balance_basis` when this vendor's convention is known.

    Does nothing when no prior balance was extracted - there is no balance to
    characterize - and nothing when the vendor is not in the table, which leaves
    F1b's review flag to fire exactly as designed.
    """
    if ctx.extracted.get("prior_balance") is None:
        return ctx
    if ctx.extracted.get("prior_balance_basis") is not None:
        return ctx

    vendor = aliases.canonical(primary_text(ctx))
    basis = PRIOR_BALANCE_BASIS.get(vendor or "")
    if basis is None:
        ctx.log(
            f"s6: no prior-balance convention recorded for vendor {vendor!r}; "
            "the carried balance will not be guessed (F1b)"
        )
        return ctx

    ctx.extracted.set("prior_balance_basis", basis, 1.0)
    ctx.log(f"s6: prior_balance_basis {basis!r} from the {vendor!r} billing convention")
    return ctx
