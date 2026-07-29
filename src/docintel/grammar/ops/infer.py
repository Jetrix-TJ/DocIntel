"""Inference ops (`selector-grammar.md` section 4.4).

Both record *how* they reached their answer, and both apply a confidence penalty
on the weaker rungs. That is the whole design: an inferred value is usable
precisely because the record says it was inferred and from what.
"""

from __future__ import annotations

import re
from typing import Any

from docintel.core.models import JobContext
from docintel.core.senders import bill_to_matches_roster

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

# Bounds on the bill-to block read from under the party name. Mirrors the
# `label-block` region's own limits rather than inventing new numbers: a postal
# address is a handful of lines, and anything longer means the column cut missed.
LABEL_BLOCK_MAX_LINES = 5
LABEL_BLOCK_LINE_GAP = 24.0  # points; regions.LABEL_BLOCK_GAP_FLOOR
# How far LEFT of the party's own left edge a continuation line may start. A
# postal address is flush with the name above it; this only absorbs the ragged
# couple of points a PDF text layer reports for a differently-hinted glyph.
_COLUMN_SLACK = 4.0


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


def resolve_bill_to_alias(ctx: JobContext) -> JobContext:
    """Read the bill-to party off the page using the pack's roster of known parties.

    Two rungs, and `bill_to_basis` records which answered:

    1. a selector already extracted `bill_to_name` -> `printed`
    2. a name on the pack's roster appears on a primary page -> `roster_page_text`

    **Why a roster rather than a selector.** Two of the four telecom templates
    print their bill-to with no label anywhere near it - no `Bill To:`, no
    `Account Name:`, nothing - so there is no anchor for a selector to hang on.
    That absence is why those personas carried the client's name as their pattern,
    which meant an unseen client returned nothing. The roster moves the string out
    of the per-document rule into the pack's business registry: one entry serves
    every carrier and every billing period, and adding a client is a config change
    rather than four rule rewrites.

    **It returns the name AS PRINTED.** Each vendor renders the same party its own
    way - `Northstar Recycling`, `Northstar Recycling Company LLC` and `NorthStar
    Recycling Company, LLC` are one AP department - and every gold label asserts
    the rendering on its own document. Canonicalising here would be a second,
    quieter kind of hardcoding.

    **An unknown party stays empty.** `core.coverage` escalates a missing required
    field to review, which is the right answer for a newly onboarded client:
    somebody has to add them. Guessing would put a wrong party on a payment.
    """
    printed = _clean(ctx.extracted.get("bill_to_name"))
    if printed is not None:
        ctx.derived.set("bill_to_basis", "printed")
        party: str | None = printed
        # The pack claim is a substring match over the whole primary page, so a
        # document that merely MENTIONS the client is claimed. Comparing the
        # printed party against the roster is what turns that into a signal
        # instead of a silent auto-approval. Only the PRINTED rung can disagree;
        # rung 2 read the name off the roster itself.
        if not bill_to_matches_roster(printed, _pack_bill_to_roster(ctx)):
            ctx.add_tag("bill_to_mismatch")
            ctx.log(
                f"s6: bill_to_name {printed!r} is not on the pack roster - "
                "this document may have arrived in the wrong inbox"
            )
    else:
        party = _roster_match(ctx, _pack_bill_to_roster(ctx))
        if party is not None:
            ctx.derived.set("bill_to_name", party)
            ctx.derived.set("bill_to_basis", "roster_page_text")
            ctx.log(
                f"s6: bill_to_name {party!r} from the pack roster "
                "(the page prints no label)"
            )
    if party is None:
        return ctx

    # The address is the block under the party, and it is attempted however the
    # party was found. A selector that could anchor on a printed `Name` label still
    # has nothing to anchor the ADDRESS on - the block below the name carries no
    # label of its own - so returning early when the name was extracted would leave
    # the address unread on exactly the documents whose name was easiest to read.
    if _clean(ctx.extracted.get("bill_to_address")) is None:
        match = party
        block = _block_under(ctx, match)
        if block is not None:
            ctx.derived.set("bill_to_address", block)
            ctx.log(f"s6: bill_to_address {block!r} from the lines under the party")
    return ctx


def _candidate_lines(
    lines: list[list[Any]], needle: re.Pattern[str]
) -> list[tuple[int, list[Any]]]:
    """Lines carrying the party, the ones where it STARTS the line first.

    A party name printed mid-line is a mention; at the head of a line it is the top
    of a block. Centracom prints both - `Account Name: CLYDE COMPANIES` in the
    summary table, whose neighbours below are `Bill Date:` and `Due Date:`, and the
    same party again heading the remittance block, which is the one with an address
    under it. Reading order alone picks the wrong one, every time.

    Mid-line matches are still returned, after the others: a template that only ever
    prints the party mid-line should not lose its address entirely.
    """
    heads: list[tuple[int, list[Any]]] = []
    mentions: list[tuple[int, list[Any]]] = []
    for index, line in enumerate(lines):
        text = " ".join(w.text for w in line)
        found = needle.search(text)
        if found is None:
            continue
        (heads if found.start() == 0 else mentions).append((index, line))
    return heads + mentions


def _block_under(ctx: JobContext, party: str) -> str | None:
    """The lines printed below `party`, in the party's own column, comma-joined.

    Bounded on three sides, each for a reason the corpus demonstrates:

    * **The column gutter**, via `regions.column_cut` - the same function the
      `text_block` pattern uses, rather than a second implementation of it. Both
      packs print the bill-to beside the vendor's own remittance address, so
      without the cut every address reads as two addresses spliced together.
    * **A vertical gap** wider than the block's own line pitch, so the next
      unrelated line is not absorbed.
    * **`LABEL_BLOCK_MAX_LINES`** as a backstop, because a block that runs on is a
      sign the first two bounds failed rather than a very long address.
    """
    from docintel.grammar import regions

    primary = {m.page_number for m in ctx.page_meta if m.role == "primary"}
    needle = re.compile(r"\s+".join(re.escape(t) for t in party.split()), re.IGNORECASE)

    for page in ctx.pages:
        if page.page_number not in primary:
            continue
        lines = page.lines()
        for index, line in _candidate_lines(lines, needle):
            left = min(w.x0 for w in line)
            following = lines[index + 1 : index + 1 + LABEL_BLOCK_MAX_LINES]
            if not following:
                return None
            pitch = line[0].y0
            bands: list[list[Any]] = []
            for below in following:
                if below[0].y0 - pitch > LABEL_BLOCK_LINE_GAP:
                    break
                pitch = below[0].y0
                bands.append([w for w in below if w.x0 >= left - _COLUMN_SLACK])
            if not bands:
                return None
            cut = regions.column_cut(bands, left, page.width)
            rows = [
                " ".join(w.text for w in band if w.x0 < cut).strip()
                for band in bands
            ]
            kept = [row for row in rows if row]
            return ", ".join(kept) if kept else None
    return None


def _pack_bill_to_roster(ctx: JobContext) -> tuple[str, ...]:
    pack = ctx.pack if ctx.pack is not None else getattr(ctx.persona, "pack", None)
    roster = getattr(pack, "bill_to_roster", None)
    if isinstance(roster, str) or not isinstance(roster, (list, tuple)):
        return ()
    return tuple(str(name) for name in roster)


def _roster_match(ctx: JobContext, roster: tuple[str, ...]) -> str | None:
    """The longest roster name printed on a primary page, exactly as printed.

    Longest first because `Northstar Recycling` is a prefix of `Northstar
    Recycling Company, LLC`; taking the shorter one would truncate the party on
    every vendor printing the full legal name.

    Whitespace between tokens is matched loosely (`\\s+`) because a PDF text layer
    breaks lines wherever the layout does, and everything else is escaped - a
    roster entry is a company name, not a pattern the pack author gets to write.
    """
    if not roster:
        return None
    text = _primary_text(ctx)
    for name in sorted(roster, key=len, reverse=True):
        tokens = [re.escape(token) for token in name.split()]
        if not tokens:
            continue
        found = re.search(r"\s+".join(tokens), text, re.IGNORECASE)
        if found is not None:
            return " ".join(found.group(0).split())
    return None


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
