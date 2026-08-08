"""Compile a pack's claim guard from data.

**"Which company does this document belong to?" is the first question the
pipeline asks, and the most expensive one to get wrong.** An unclaimed document
is emitted and tagged `unclaimed_document` for a human to look at; a
wrongly-claimed one runs a whole rulebook of another organization's assumptions
against it - the wrong ladder, the wrong personas, the wrong thresholds
(`registry.resolve_pack`).

The two shipped packs claim on genuinely different grounds, which is why the
schema is a small closed set of RULE KINDS rather than one shape:

* **Northstar** is an AP department; every invoice it handles is billed *to*
  Northstar, so its guard is the bill-to.
* **Digital Direction** is a telecom expense manager billing for several managed
  clients, so there is no single recipient to guard on - what its documents share
  is that the sender is a known carrier.

A pack claims when **any rule holds and no veto holds.** Vetoes exist because a
marker can be present for the wrong reason: Northstar's own street address
printed inside a SHIP-TO block says where a pallet went, not who owes the money.

Every kind here was derived from a measurement, not invented: see
`tests/packs/test_claim_precision.py`, which measured 3 of 6 out-of-domain
documents being claimed before these rules were tightened on 2026-08-07.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from docintel.core.models import JobContext
from docintel.core.senders import normalize_name
from docintel.packs import signals


class ClaimError(ValueError):
    """A claim spec that cannot be compiled. Raised at load time."""


def _normalized_scope(ctx: JobContext, scope: str) -> str:
    return normalize_name(signals.scope_text(ctx, scope))


def _markers(spec: Mapping[str, Any], where: str) -> Any:
    """Any of these substrings, in normalized text.

    Each must name the organization or an address specific enough that no other
    business prints it. A marker that is merely *associated* with the company -
    a bare ZIP code - belongs in `corroborated_markers` instead.
    """
    values = spec.get("values")
    if not isinstance(values, Sequence) or isinstance(values, str) or not values:
        raise ClaimError(f"{where}.values: expected a non-empty list of strings")
    needles = [normalize_name(v) for v in values]
    scope = spec.get("scope", "primary")

    def rule(ctx: JobContext) -> bool:
        haystack = _normalized_scope(ctx, scope)
        return any(n in haystack for n in needles)

    return rule


def _corroborated_markers(spec: Mapping[str, Any], where: str) -> Any:
    """A marker that is not specific enough alone, paired with a token that makes
    it safe.

    Northstar's `ma 01028` is the case this exists for: the bare ZIP was added so
    that four real EDCO invoices with typo'd company names would still be
    claimed, and a bare ZIP claims any document that prints it. Requiring a
    co-occurring `northst` keeps all four - measured, all 28 real EDCO samples
    carry it - while rejecting an unrelated vendor at the same ZIP.
    """
    pairs = spec.get("pairs")
    if not isinstance(pairs, Sequence) or not pairs:
        raise ClaimError(f"{where}.pairs: expected a non-empty list")
    compiled: list[tuple[str, str]] = []
    for i, pair in enumerate(pairs):
        if not isinstance(pair, Mapping):
            raise ClaimError(f"{where}.pairs[{i}]: expected a mapping")
        marker, requires = pair.get("marker"), pair.get("requires")
        if not isinstance(marker, str) or not isinstance(requires, str):
            raise ClaimError(f"{where}.pairs[{i}]: expected `marker` and `requires` strings")
        compiled.append((normalize_name(marker), normalize_name(requires)))
    scope = spec.get("scope", "primary")

    def rule(ctx: JobContext) -> bool:
        haystack = _normalized_scope(ctx, scope)
        return any(m in haystack and r in haystack for m, r in compiled)

    return rule


def _alias_table(spec: Mapping[str, Any], where: str) -> Any:
    """The pack's own alias table resolves a canonical sender.

    Digital Direction's primary guard. The alias table is short and stable
    (carriers), whereas the client roster grows every time the business signs
    one - which is why the carrier is the claim and the roster is secondary.
    """
    scope = spec.get("scope", "primary")

    def rule(ctx: JobContext) -> bool:
        pack = ctx.pack
        aliases: dict[str, str] = getattr(pack, "vendor_aliases", {}) or {}
        if not aliases:
            return False
        haystack = _normalized_scope(ctx, scope)
        return any(phrase in haystack for phrase in aliases)

    return rule


def _roster_on_short_line(spec: Mapping[str, Any], where: str) -> Any:
    """A roster name printed on a SHORT line, i.e. in a bill-to block.

    Not anywhere in the text: an unrelated vendor's invoice claimed Digital
    Direction merely by naming a managed client in a line-item description
    (`1x SIGNAGE FOR CITY OF DUBLIN PROJECT`). Measured 2026-08-07: zero of the
    111 second-samples reach this rule at all, so its cutoff is fitted to the
    over-claim it rejects rather than to a real document - the one constant in
    this pack without real-document backing, kept because the pack's growth path
    is a bill from a carrier not yet in the alias table addressed to a client
    who is.
    """
    values = spec.get("values")
    if not isinstance(values, Sequence) or isinstance(values, str) or not values:
        raise ClaimError(f"{where}.values: expected a non-empty list of strings")
    names = [normalize_name(v) for v in values]
    max_words = spec.get("max_words")
    if not isinstance(max_words, int) or max_words < 1:
        raise ClaimError(f"{where}.max_words: expected a positive integer")

    def rule(ctx: JobContext) -> bool:
        for page in signals.primary_pages(ctx):
            for line in page.lines():
                if len(line) > max_words:
                    continue
                haystack = normalize_name(signals.line_text(line))
                if any(n in haystack for n in names):
                    return True
        return False

    return rule


RULES: dict[str, Any] = {
    "markers": _markers,
    "corroborated_markers": _corroborated_markers,
    "alias_table": _alias_table,
    "roster_on_short_line": _roster_on_short_line,
}


def _every_marker_hit_in_block(spec: Mapping[str, Any], where: str, markers: list[str]) -> Any:
    """Veto: every line-level marker hit sits inside a named block.

    Northstar's addresses appear on documents that ship goods there but bill
    somebody else. A marker hit inside a SHIP-TO block says where a pallet went,
    not who owes the money, which is the opposite of what a bill-to guard is for.

    Deliberately a veto on the text-level match rather than a line-by-line
    rewrite of the guard: a marker can legitimately wrap across two visual lines
    and so match the joined text while matching no single line. When there is no
    line-level hit at all this returns False and the rules' answer stands
    unchanged, so the veto can only ever remove a claim it can see evidence for.

    Measured 2026-08-07 across all 111 second-samples: 100 documents carry a
    marker on a primary-page line, and for zero of them is every such line a
    ship-to line. Vetoing this case costs nothing real.
    """
    anchor_src = spec.get("anchor")
    if not isinstance(anchor_src, str) or not anchor_src:
        raise ClaimError(f"{where}.anchor: expected a regex naming the block")
    try:
        anchor = re.compile(anchor_src, re.I)
    except re.error as exc:
        raise ClaimError(f"{where}.anchor: bad regex {anchor_src!r}: {exc}") from exc

    def veto(ctx: JobContext) -> bool:
        hits: list[str] = []
        for page in signals.primary_pages(ctx):
            for line in page.lines():
                text = signals.line_text(line)
                if any(m in normalize_name(text) for m in markers):
                    hits.append(text)
        return bool(hits) and all(anchor.search(text) for text in hits)

    return veto


VETOES: dict[str, Any] = {"every_marker_hit_in_block": _every_marker_hit_in_block}


class ClaimGuard:
    """A compiled claim guard. `claims(ctx)` matches the Pack protocol exactly, so
    a pack swaps representation without the pipeline noticing."""

    def __init__(self, rules: list[Any], vetoes: list[Any]) -> None:
        self._rules = rules
        self._vetoes = vetoes

    def claims(self, ctx: JobContext) -> bool:
        if not any(rule(ctx) for rule in self._rules):
            return False
        return not any(veto(ctx) for veto in self._vetoes)


def compile_claim(spec: Mapping[str, Any]) -> ClaimGuard:
    """Compile a pack's `claim` block. Raises `ClaimError` at load on any problem.

    Fail-loud for the same reason the ladder compiler is: a claim rule that
    silently evaluates false is a pack that silently stops recognising its own
    documents, and every one of them would be emitted as `unclaimed_document`
    with zero fields extracted.
    """
    rules_spec = spec.get("rules")
    if not isinstance(rules_spec, Sequence) or not rules_spec:
        raise ClaimError("claim.rules: expected a non-empty list")

    rules: list[Any] = []
    literal_markers: list[str] = []
    for i, rule_spec in enumerate(rules_spec):
        where = f"claim.rules[{i}]"
        if not isinstance(rule_spec, Mapping):
            raise ClaimError(f"{where}: expected a mapping")
        kind = rule_spec.get("kind")
        factory = RULES.get(kind)
        if factory is None:
            raise ClaimError(
                f"{where}.kind: unknown claim rule {kind!r}; expected one of {sorted(RULES)}"
            )
        scope = rule_spec.get("scope", "primary")
        if scope not in signals.SCOPES:
            raise ClaimError(f"{where}.scope: unknown scope {scope!r}")
        rules.append(factory(rule_spec, where))
        # Vetoes operate on the marker text the rules matched on, so collect it.
        if kind == "markers":
            literal_markers += [normalize_name(v) for v in rule_spec["values"]]
        elif kind == "corroborated_markers":
            literal_markers += [normalize_name(p["marker"]) for p in rule_spec["pairs"]]

    vetoes: list[Any] = []
    for i, veto_spec in enumerate(spec.get("vetoes", [])):
        where = f"claim.vetoes[{i}]"
        if not isinstance(veto_spec, Mapping):
            raise ClaimError(f"{where}: expected a mapping")
        kind = veto_spec.get("kind")
        factory = VETOES.get(kind)
        if factory is None:
            raise ClaimError(
                f"{where}.kind: unknown veto {kind!r}; expected one of {sorted(VETOES)}"
            )
        if not literal_markers:
            raise ClaimError(
                f"{where}: a marker veto needs at least one marker rule to veto"
            )
        vetoes.append(factory(veto_spec, where, literal_markers))

    return ClaimGuard(rules, vetoes)
