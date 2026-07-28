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
    """Collapse every printed rendering of a sender onto one canonical key (F5).

    Three rungs, and `vendor_basis` records which answered:

    1. the extracted `remit_payee` matches the pack's alias table -> `remit_payee_alias`
    2. the extracted `vendor_name` matches it -> `letterhead_alias`
    3. **the page text matches it** -> `page_text_alias`

    Rung 3 is what makes this work at all on two corpus documents, and it is the
    reason the op reads page text rather than only extracted fields:

    * **Lumen's letterhead is an IMAGE.** The token `LUMEN` appears zero times in
      the text layer, so no selector can capture it. The alias table still matches
      `How to reach Lumen:`.
    * **Windstream's text layer breaks the brand mid-word** - `Kinetic Business by
      Windstre am`. No pattern yields the real name. The table matches on
      `kinetic business` instead.

    Having the canonical key, the pack's `display_names` table supplies a
    `vendor_name` **only when no selector extracted one**. Printed evidence wins
    where it exists, which is F5's principle; the table is for where the print is
    unreadable.

    `carrier_canonical` is emitted alongside `vendor_canonical` with the same
    value. They are one fact under two names - the Digital Direction pack spec
    calls it `carrier_canonical` and every gold label in that pack asserts it
    under that name.
    """
    payee = _clean(ctx.extracted.get("remit_payee"))
    letterhead = _clean(ctx.extracted.get("vendor_name"))
    table = _pack_aliases(ctx)

    canonical: str | None = None
    basis: str | None = None
    for candidate, name in ((payee, "remit_payee"), (letterhead, "letterhead")):
        if candidate is None:
            continue
        found = table.get(candidate.casefold())
        if found is not None:
            canonical, basis = found, f"{name}_alias"
            break

    if canonical is None:
        canonical = _canonical_from_page(ctx, table)
        basis = "page_text_alias" if canonical is not None else None

    if canonical is not None:
        ctx.derived.set("vendor_canonical", canonical)
        ctx.derived.set("carrier_canonical", canonical)
        ctx.derived.set("vendor_basis", basis)
        display = _pack_display_names(ctx).get(canonical)
        if display is not None and letterhead is None:
            ctx.derived.set("vendor_name", display)
            ctx.log(f"s6: vendor_name {display!r} from the alias table (not printed)")
        if payee is not None and letterhead is not None and (
            payee.casefold() != letterhead.casefold()
        ):
            ctx.log(
                f"s6: remittance payee {payee!r} differs from letterhead "
                f"{letterhead!r}; both collapse to {canonical!r} (F5)"
            )
        return ctx

    # No alias table entry matched. Fall back to the printed names themselves,
    # preferring the payee - the legal entity survives rebrands, the logo does not.
    fallback = payee or letterhead
    if fallback is not None:
        ctx.derived.set("vendor_canonical", fallback)
        ctx.derived.set("vendor_basis", "remit_payee" if payee else "letterhead")
        if payee is not None and letterhead is not None and (
            payee.casefold() != letterhead.casefold()
        ):
            # Logged on this path too. An unrecognized vendor printing two
            # different names is exactly the case that most needs to be visible -
            # it is a new alias-table entry waiting to be written.
            ctx.log(
                f"s6: remittance payee {payee!r} differs from letterhead "
                f"{letterhead!r}; the payee wins (F5)"
            )
    return ctx


def _canonical_from_page(ctx: JobContext, table: dict[str, str]) -> str | None:
    """The canonical key implied by anything printed on a primary page.

    Substring matching against the alias table's own keys, which is safe because
    those keys are whole company names rather than common words.
    """
    if not table:
        return None
    haystack = re.sub(r"[^a-z0-9]+", " ", _primary_text(ctx).casefold())
    best: tuple[int, str] | None = None
    for printed, canonical in table.items():
        key = re.sub(r"[^a-z0-9]+", " ", printed.casefold()).strip()
        if key and key in haystack:
            # Longest match wins: `level 3 communications llc` is more specific
            # than `level 3 communications`, and both beat a bare brand token.
            if best is None or len(key) > best[0]:
                best = (len(key), canonical)
    return best[1] if best is not None else None


def _pack_display_names(ctx: JobContext) -> dict[str, str]:
    pack = ctx.pack if ctx.pack is not None else getattr(ctx.persona, "pack", None)
    table = getattr(pack, "display_names", None)
    if not isinstance(table, dict):
        return {}
    return {str(k): str(v) for k, v in table.items()}


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
