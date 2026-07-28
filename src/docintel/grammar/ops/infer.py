"""Inference ops (`selector-grammar.md` section 4.4).

Both record *how* they reached their answer, and both apply a confidence penalty
on the weaker rungs. That is the whole design: an inferred value is usable
precisely because the record says it was inferred and from what.
"""

from __future__ import annotations

import re
from typing import Any

from docintel.core.models import JobContext

ISO_CODES: frozenset[str] = frozenset({"USD", "CAD", "EUR", "GBP"})

# The `currency_basis` vocabulary. These strings are the gold labels' own, not a
# fresh invention: all ten gold files record a `currency_basis`, using
# `explicit_iso_code`, `tax_regime_marker` and `pack_default`. Naming the rungs
# anything else would make the field unassertable, so the scorecard would
# silently stop measuring the F14 ladder it exists to check.
BASIS_ISO_CODE = "explicit_iso_code"
BASIS_TAX_REGIME = "tax_regime_marker"
BASIS_PACK_DEFAULT = "pack_default"
# Not used by any gold label. Kept because section 4.4 lists the vendor-address
# rung between the tax regime and the pack default, and dropping it would mean a
# CAD invoice with no tax line silently fell through to a USD pack default.
BASIS_VENDOR_ADDRESS = "vendor_address"

# Tax regimes that name a country unambiguously. VAT is deliberately absent: it
# is used across the UK and the whole euro area, so it narrows the currency to
# "one of several" and inferring either would be a guess wearing a basis.
_TAX_REGIME_CURRENCY: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bH\.?\s?S\.?\s?T\.?\b"), "CAD"),
    (re.compile(r"\bG\.?\s?S\.?\s?T\.?\b"), "CAD"),
    (re.compile(r"\bQ\.?\s?S\.?\s?T\.?\b"), "CAD"),
)

# A Canadian postal code, which is a country signal (F14).
_CA_POSTAL = re.compile(r"\b[A-Za-z]\d[A-Za-z]\s?\d[A-Za-z]\d\b")

# Rungs at or below which the answer is an inference rather than a reading, and
# the record has to say so.
_WEAK_BASES = frozenset({BASIS_VENDOR_ADDRESS, BASIS_PACK_DEFAULT})


def _primary_text(ctx: JobContext) -> str:
    """Text of the pages field values may be read from.

    Restricted to `primary` pages for the same reason extraction is (section 7):
    a supporting Bill of Lading may mention a tax regime that has nothing to do
    with how this invoice is denominated.
    """
    primary = {m.page_number for m in ctx.page_meta if m.role == "primary"}
    return "\n".join(p.text for p in ctx.pages if p.page_number in primary)


def infer_currency(ctx: JobContext) -> JobContext:
    """Resolve the currency down a ladder, recording which rung answered (F14).

    1. `currency` already extracted as an ISO code -> basis `iso_code`
    2. a tax regime that names one country (`H.S.T.`/`G.S.T.`/`Q.S.T.` -> CAD)
       -> basis `tax_regime`
    3. a Canadian postal code in the vendor address -> basis `vendor_address`
    4. the pack's default -> basis `pack_default`

    Rungs 3 and 4 add `currency_inferred_weak`. Rung 4 needs a pack, which
    arrives in C5 - until then nine of the ten corpus documents legitimately
    resolve to nothing here, because "most invoices are USD" is a *pack policy*,
    not something this document says. Only U-PAK is CAD, and it says so via its
    H.S.T. line, which is rung 2.
    """
    existing = ctx.extracted.get("currency")
    if isinstance(existing, str) and existing.strip().upper() in ISO_CODES:
        ctx.derived.set("currency", existing.strip().upper())
        ctx.derived.set("currency_basis", BASIS_ISO_CODE)
        return ctx

    text = _primary_text(ctx)
    for pattern, code in _TAX_REGIME_CURRENCY:
        if pattern.search(text):
            ctx.derived.set("currency", code)
            ctx.derived.set("currency_basis", BASIS_TAX_REGIME)
            return ctx

    postal = ctx.extracted.get("postal_code")
    if (postal is not None and _CA_POSTAL.search(str(postal))) or _CA_POSTAL.search(text):
        _set_weak(ctx, "CAD", BASIS_VENDOR_ADDRESS)
        return ctx

    default = _pack_default(ctx)
    if default is not None:
        _set_weak(ctx, default, BASIS_PACK_DEFAULT)
        return ctx

    ctx.log(
        "s6: currency could not be inferred - no ISO code, no tax regime, no "
        "country signal, and no pack default is attached"
    )
    return ctx


def _set_weak(ctx: JobContext, code: str, basis: str) -> None:
    ctx.derived.set("currency", code)
    ctx.derived.set("currency_basis", basis)
    if basis in _WEAK_BASES:
        # Scoped to `currency`: a weakly-inferred currency is no reason to trust
        # the invoice number less.
        ctx.add_field_modifier("currency", "currency_inferred_weak")


def _pack_default(ctx: JobContext) -> str | None:
    """The pack's default currency, if a pack is attached. Wired in C5.

    Read off `ctx.pack` - set by Stage 3 when a pack claimed the document -
    duck-typed rather than imported, so an op never depends on the registry.
    """
    pack = ctx.pack if ctx.pack is not None else getattr(ctx.persona, "pack", None)
    default = getattr(pack, "default_currency", None)
    return default if isinstance(default, str) and default in ISO_CODES else None


def resolve_vendor_alias(ctx: JobContext) -> JobContext:
    """Settle on one vendor name, preferring the remittance payee (F5).

    Two of the corpus senders print one brand on the letterhead and bill under
    another - the money goes where the remittance block says, not where the logo
    says, so `remit_payee` wins whenever both are present. `vendor_basis` records
    which one answered so a mismatch is auditable rather than invisible.

    The pack's alias table is the rung above this and arrives in C5; without one,
    the preference order is the whole op.
    """
    payee = _clean(ctx.extracted.get("remit_payee"))
    letterhead = _clean(ctx.extracted.get("vendor_name"))

    aliases = _pack_aliases(ctx)
    for candidate, basis in ((payee, "remit_payee"), (letterhead, "letterhead")):
        if candidate is None:
            continue
        canonical = aliases.get(candidate.casefold())
        if canonical is not None:
            ctx.derived.set("vendor_canonical", canonical)
            ctx.derived.set("vendor_basis", f"{basis}_alias")
            return ctx

    if payee is not None:
        ctx.derived.set("vendor_canonical", payee)
        ctx.derived.set("vendor_basis", "remit_payee")
        if letterhead is not None and letterhead.casefold() != payee.casefold():
            ctx.log(
                f"s6: remittance payee {payee!r} differs from letterhead "
                f"{letterhead!r}; the payee wins (F5)"
            )
        return ctx

    if letterhead is not None:
        ctx.derived.set("vendor_canonical", letterhead)
        ctx.derived.set("vendor_basis", "letterhead")
    return ctx


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _pack_aliases(ctx: JobContext) -> dict[str, str]:
    """The pack's alias table, keyed casefolded. Empty when no pack claimed."""
    pack = ctx.pack if ctx.pack is not None else getattr(ctx.persona, "pack", None)
    table = getattr(pack, "vendor_aliases", None)
    if not isinstance(table, dict):
        return {}
    return {str(k).casefold(): str(v) for k, v in table.items()}
