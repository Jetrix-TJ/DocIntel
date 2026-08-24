"""No pack may claim a document outside its domain.

**A wrong claim is worse than no claim.** An unclaimed document is emitted and
tagged `unclaimed_document` for a human to look at (`registry.py:117`); a
wrongly-claimed one runs a whole rulebook of another organization's assumptions
against it - the wrong ladder, the wrong personas, the wrong thresholds.

Until this file existed, that direction was never measured. All 111
second-sample documents belong to a vendor that is already in a pack, so the
corpus contains no negative example at all, and the only negative test in the
suite was one synthetic `ACME WIDGETS / SPRINGFIELD IL` fixture
(`test_northstar_claims.py:54`). Meanwhile the markers were being deliberately
LOOSENED - `BILL_TO_MARKERS` gained the bare ZIP `ma 01028` so that four real
EDCO invoices with typo'd company names would still be claimed. Recall was
measured (`unclaimed_document: 3 -> 0` in the 2026-08-06 audit); precision was
not.

Measured on 2026-08-07, before the fixes below: **three of these six documents
were claimed**, two by Northstar via the bare ZIP and one by Digital Direction
via a managed-client name appearing in a line item.

The fixtures are synthetic because the real risk is a class of document the
corpus does not contain - an invoice from a business in neither pack's domain.
Each one names the specific over-claim it probes. None contains a real vendor or
carrier name from either pack's alias table; that would test the claim rather
than its precision.
"""

from __future__ import annotations

import pytest

from digitaldirection import PACK as DIGITALDIRECTION_PACK
from northstar import PACK as NORTHSTAR_PACK

from docintel.core.models import PageMeta, PageText, Word, new_context
from docintel.packs.registry import load_packs, resolve_pack

_ALL_PACKS = load_packs() + [NORTHSTAR_PACK, DIGITALDIRECTION_PACK]

# Each entry: why it must not be claimed.
OUT_OF_DOMAIN: dict[str, str] = {
    # The bare ZIP `ma 01028` is a Northstar bill-to marker. Any OTHER business
    # at that ZIP must not be claimed. (Claimed by northstar before the fix.)
    "different_company_same_zip": (
        "ACME PACKAGING LLC|INVOICE 40122|"
        "BILL TO: HAMPDEN MILLS INC|22 SHAKER RD EAST LONGMEADOW MA 01028|"
        "TOTAL DUE 4,182.00"
    ),
    # The same ZIP reached only through a SHIP-TO block, on an invoice billed to
    # a company in Texas. The bill-to guard must key on who is BILLED, not on
    # every address printed. (Claimed by northstar before the fix.)
    "ship_to_only_at_the_marker_zip": (
        "GLOBEX SUPPLY CO|INVOICE 88231|"
        "BILL TO: GLOBEX CORPORATE OFFICE 400 W 5TH ST AUSTIN TX 78701|"
        "SHIP TO: 94 MAPLE ST EAST LONGMEADOW MA 01028|TOTAL DUE 912.44"
    ),
    # A managed client's name inside a LINE ITEM on an unrelated vendor's
    # invoice, billed to somebody else entirely. Digital Direction's
    # managed-client list is a bill-to signal, not a keyword search.
    # (Claimed by digitaldirection before the fix.)
    "managed_client_named_in_a_line_item": (
        "PRINTWORKS INC|INVOICE 5521|BILL TO: RIVERSIDE HOLDINGS|"
        "1x SIGNAGE FOR CITY OF DUBLIN PROJECT 2,400.00|TOTAL DUE 2,400.00"
    ),
    # A carrier-shaped telecom bill from a carrier this pack does not manage.
    # Correctly unclaimed before the fix; pinned so a future alias-table
    # widening cannot quietly swallow the whole telecom industry.
    "unmanaged_carrier": (
        "VERIZON BUSINESS|Account Number 992-118-4471|"
        "BILL TO: CLYDE PARTNERS UNLIMITED|TOTAL AMOUNT DUE 1,204.55"
    ),
    # Ordinary invoices from businesses in neither domain. Correctly unclaimed
    # before the fix; they are the control group.
    "plain_office_supply_invoice": (
        "NORTHWIND OFFICE SUPPLY|INVOICE 7781|"
        "BILL TO: PARKER & SONS 88 BROAD ST BOSTON MA 02110|TOTAL DUE 341.20"
    ),
    "plain_freight_invoice": (
        "SUMMIT FREIGHT LINES|PRO NUMBER 5541209|"
        "BILL TO: DELTA FOODS 900 INDUSTRIAL PKWY TOLEDO OH 43615|"
        "AMOUNT DUE 8,220.00"
    ),
}


def _ctx(text: str):
    """`|`-separated rows become visual lines, the convention already used in
    `test_digitaldirection_ladder.py` and `test_northstar_claims.py`."""
    words: list[Word] = []
    for row, line in enumerate(text.split("|")):
        y = 100.0 + row * 14.0
        for i, tok in enumerate(line.split()):
            words.append(
                Word(text=tok, x0=10.0 + 40.0 * i, y0=y, x1=45.0 + 40.0 * i, y1=y + 10.0)
            )
    ctx = new_context("d", "/x.pdf")
    ctx.pages = (
        PageText(
            page_number=1, words=tuple(words), width=612.0, height=792.0, source="native"
        ),
    )
    ctx.page_meta = (PageMeta(1, 100, 0, 0, "primary"),)
    return ctx


@pytest.mark.parametrize("name,text", sorted(OUT_OF_DOMAIN.items()))
def test_no_pack_claims_an_out_of_domain_document(name: str, text: str) -> None:
    assert resolve_pack(_ctx(text), _ALL_PACKS) is None


# --------------------------------------------------------------------------
# The other direction: a pack must still claim what IS its own
# --------------------------------------------------------------------------


IN_DOMAIN: dict[str, tuple[str, str]] = {
    # A carrier bill with NO managed-client name anywhere. Digital Direction must
    # claim it on the carrier alone - that is its primary guard, and the whole
    # reason this pack does not use a bill-to.
    #
    # This case exists because it once regressed and nothing caught it. A first
    # version of the `alias_table` rule read `ctx.pack.vendor_aliases`, which is
    # always None while a claim is being evaluated (`resolve_pack` is what SETS
    # `ctx.pack`), so the rule always returned False and all 7 real Digital
    # Direction documents went `unclaimed_document`. `replay-gold` stayed
    # BYTE-IDENTICAL through it: all four DD gold documents also print a
    # managed-client name on a short line, so the secondary roster rule claimed
    # them. Only the 111-document sweep saw it.
    "carrier_only_no_client_named": (
        "COMCAST BUSINESS|Account Number 8495 44 462 0365242|"
        "TOTAL AMOUNT DUE 212.87",
        "digitaldirection",
    ),
    "northstar_by_company_name": (
        "VERITIV|INVOICE 715-33905296|BILL TO: NORTHSTAR RECYCLING COMPANY LLC|"
        "TOTAL 4,908.00",
        "northstar",
    ),
    # The typo'd bill-to that the corroborated ZIP marker exists to rescue.
    "northstar_by_corroborated_zip": (
        "EDCO WASTE|INVOICE 823282|NORTHSTRAY RECYCLING|"
        "EASTE LONGMEADOWN MA 01028|TOTAL 894.98",
        "northstar",
    ),
}


@pytest.mark.parametrize("name,case", sorted(IN_DOMAIN.items()))
def test_a_pack_still_claims_its_own_documents(name: str, case: tuple[str, str]) -> None:
    text, expected = case
    pack = resolve_pack(_ctx(text), _ALL_PACKS)
    assert pack is not None, f"{name} should be claimed by {expected}"
    assert pack.name == expected


def test_an_alias_table_rule_without_a_table_is_rejected_at_load() -> None:
    """The rule cannot silently degrade to 'never matches'. That is precisely
    what the regression above did, and it cost seven documents."""
    from docintel.packs.claims import ClaimError, compile_claim

    spec = {"rules": [{"kind": "alias_table", "scope": "primary"}]}
    with pytest.raises(ClaimError, match="needs a non-empty alias table"):
        compile_claim(spec)
