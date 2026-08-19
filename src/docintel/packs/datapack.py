"""A pack built entirely from data — no Python module, no entry in a tuple.

**This is what the declarative work was for.** The two shipped packs are ~1,150
and ~1,290 lines of Python across eight modules each, and every line of that is
engineer time before a client's first invoice can be processed. A `DataPack` is
a directory: one `pack.json` and a `personas/` folder.

It implements exactly the same `registry.Pack` protocol the module-backed packs
do, so the pipeline, the grammar validator and the scorecard cannot tell the
difference — which is the point. A data pack is not a lesser kind of pack.

**Discovery stays deliberate.** `registry.PACK_FILES` names pack files the way
`PACK_MODULES` names modules: a pack is a business decision with a spec, so it
must not become active because somebody dropped a folder on disk
(`registry.py`). What changes is the *cost* of the decision, not whether one
gets made.

**What still needs Python, honestly.** A data pack gets the classification
ladder, the tag rules, the claim guard, field sets, thresholds, aliases, and
(see `_resolve_vendor_fingerprint` below) declarative vendor-fingerprint
resolution. It does NOT get pack-specific hooks — a bespoke reference-pattern
collector or a billing-convention rule of the kind `northstar/references.py`
and `digitaldirection/conventions.py` provide. A company needing one of those
still needs a module. Both shipped packs would today need `references` and
`conventions`; nothing else about them is code.
"""

from __future__ import annotations

import functools
import json
import os
import re
from typing import Any

from docintel.core.models import JobContext
from docintel.core.senders import normalize_name
from docintel.packs import claims, declarative
from docintel.pipeline.hooks import HookRegistry, Next


class PackSpecError(ValueError):
    """A pack file that cannot be loaded. Raised at load time, never later."""


def _frozen(value: Any) -> frozenset[str]:
    return frozenset(value or ())


def _primary_text(ctx: JobContext) -> str:
    """`registry.primary_text`, imported lazily: `registry.py` imports this
    module at its own top level (`from docintel.packs import datapack,
    signals`), so a top-level import the other way would be a real cycle.
    Both modules are fully loaded by the time any hook actually runs, so a
    deferred import here is safe - the same pattern `pipeline.stages.
    build_pipeline` already uses for its own late imports.
    """
    from docintel.packs.registry import primary_text

    return primary_text(ctx)


class DataPack:
    """The `registry.Pack` protocol, implemented from a spec dict."""

    def __init__(self, spec: dict[str, Any], *, directory: str) -> None:
        self.directory = directory
        self._spec = spec

        name = spec.get("name")
        if not isinstance(name, str) or not name:
            raise PackSpecError(f"{directory}: pack.name is required")
        self.name = name

        doc_types = spec.get("doc_types")
        if not isinstance(doc_types, list) or not doc_types:
            raise PackSpecError(f"{name}: doc_types must be a non-empty list")
        self.doc_types: tuple[str, ...] = tuple(doc_types)

        self.default_currency = spec.get("default_currency", "USD")
        self._thresholds: dict[str, float] = dict(spec.get("thresholds", {}))
        self._fields: dict[str, Any] = spec.get("fields", {})
        self._aliases: dict[str, str] = dict(spec.get("aliases", {}).get("literal", {}))
        self._display: dict[str, str] = dict(spec.get("aliases", {}).get("display", {}))
        self._roster: tuple[str, ...] = tuple(spec.get("bill_to_roster", ()))

        # Compiled at load, so a malformed rule is an error when the pack is
        # registered rather than a rung that silently never fires.
        self.ladder, self.tag_rules = declarative.compile_classification(spec)
        claim_spec = spec.get("claim")
        if not isinstance(claim_spec, dict):
            raise PackSpecError(f"{name}: a pack must declare how it claims a document")
        self.claim_guard = claims.compile_claim(claim_spec, aliases=self._aliases)

        unknown = set(self._fields) - set(self.doc_types)
        if unknown:
            raise PackSpecError(
                f"{name}: fields declared for undeclared doc_types {sorted(unknown)}"
            )
        ladder_types = {doc_type for _, doc_type, _ in self.ladder.rungs} | {
            self.ladder.default
        }
        stray = ladder_types - set(self.doc_types)
        if stray:
            raise PackSpecError(
                f"{name}: ladder produces doc_types {sorted(stray)} that the pack "
                f"does not declare - a document would classify into a type with no "
                f"field set, and extraction would have nothing to read"
            )

    # -- classification ------------------------------------------------------

    def claims(self, ctx: JobContext) -> bool:
        return self.claim_guard.claims(ctx)

    def classify(self, ctx: JobContext) -> JobContext:
        doc_type, signal = self.ladder.doc_type_for(ctx)
        ctx.doc_type = doc_type
        ctx.signal_that_fired = signal
        ctx.classification_confidence = 0.95 if signal != "default" else 0.80
        for tag in self.tag_rules.tags_for(ctx):
            ctx.add_tag(tag)
        return ctx

    # -- grammar.schema.Pack -------------------------------------------------

    @property
    def thresholds(self) -> dict[str, float]:
        return dict(self._thresholds)

    @property
    def vendor_aliases(self) -> dict[str, str]:
        return dict(self._aliases)

    @property
    def display_names(self) -> dict[str, str]:
        return dict(self._display)

    @property
    def bill_to_roster(self) -> tuple[str, ...]:
        return self._roster

    def _for(self, doc_type: str, key: str) -> Any:
        return self._fields.get(doc_type, {}).get(key)

    def fields_for(self, doc_type: str) -> frozenset[str]:
        return _frozen(self._for(doc_type, "all"))

    field_set = fields_for

    def required_fields(self, doc_type: str) -> frozenset[str]:
        return _frozen(self._for(doc_type, "required"))

    def required_any_of(self, doc_type: str) -> tuple[frozenset[str], ...]:
        return tuple(frozenset(group) for group in self._for(doc_type, "any_of") or ())

    def derived_only_fields(self, doc_type: str) -> frozenset[str]:
        return _frozen(self._for(doc_type, "derived_only"))

    def adjust_ops(self) -> frozenset[str]:
        """No pack ops. A data pack composes the grammar's closed enum; adding an
        op is a business-logic change that needs a PR and an eval, which is
        exactly the kind of decision that should not be reachable from a config
        file."""
        return frozenset()

    # -- personas ------------------------------------------------------------

    def personas(self) -> list[dict[str, Any]]:
        """Read from disk on every call, matching the module-backed packs: a
        persona is data, the files are small, and a cache would mean an authoring
        session had to restart the process to see its own edit."""
        out: list[dict[str, Any]] = []
        directory = os.path.join(self.directory, "personas")
        if not os.path.isdir(directory):
            return out
        for filename in sorted(os.listdir(directory)):
            if filename.endswith(".json"):
                with open(os.path.join(directory, filename)) as fh:
                    out.append(json.load(fh))
        return out

    # -- vendor fingerprint ---------------------------------------------------

    def _canonical_vendor(self, ctx: JobContext) -> str | None:
        """The canonical vendor key for this document, from data alone.

        Matches each `(printed, canonical)` pair in `aliases.literal` against
        the primary-page text - substring, word-boundary safe, on normalized
        names - so a pack author writes a plain company name, never a regex.
        This is the same matching power `northstar.aliases`' `PATTERN_ALIASES`
        gives it (its own `LITERAL_ALIASES` alone would need an exact
        whole-page match to fire, which real page text never gives it); here
        it comes for free from a name string.

        Falls back to this pack's own single shipped persona when nothing
        matched and there is exactly one - the common case for a newly
        onboarded, single-vendor pack, where writing an alias table that maps
        a name to itself would be pure ceremony. Safe specifically because
        this method is only ever called from a hook `registry.
        _ClaimGatedRegistry` has already gated on THIS pack having claimed the
        document - so "this pack's one vendor" is not a guess, it is the only
        vendor this pack could possibly mean.
        """
        text = normalize_name(_primary_text(ctx))
        if text:
            for printed, canonical in self._aliases.items():
                needle = normalize_name(printed)
                if needle and re.search(rf"\b{re.escape(needle)}\b", text):
                    return canonical

        personas = self.personas()
        if len(personas) == 1:
            fingerprint = str(personas[0].get("sender_fingerprint", ""))
            _, _, vendor = fingerprint.partition("|")
            return vendor or None
        return None

    def _resolve_vendor_fingerprint(self, ctx: JobContext, next_: Next) -> JobContext:
        canonical = self._canonical_vendor(ctx)
        if canonical is not None:
            ctx.sender_fingerprint = f"{self.name}|{canonical}"
        return next_(ctx)

    # -- hooks ---------------------------------------------------------------

    def register_hooks(self, registry: HookRegistry) -> None:
        """The ladder, and vendor-fingerprint resolution. `registry.
        _ClaimGatedRegistry` gates both on this pack having claimed, so a data
        pack cannot overwrite another pack's doc_type or fingerprint - the
        failure that cost DTSS 19 of its 23 passing assertions when the second
        pack was first registered."""

        def ladder_hook(ctx: JobContext, next_: Next) -> JobContext:
            return next_(self.classify(ctx))

        ladder_hook.__name__ = f"{self.name}_ladder"
        registry.register("classifySignals", ladder_hook, self.name)

        def fingerprint_hook(ctx: JobContext, next_: Next) -> JobContext:
            return self._resolve_vendor_fingerprint(ctx, next_)

        fingerprint_hook.__name__ = f"{self.name}_fingerprint"
        registry.register("beforePersonaLookup", fingerprint_hook, self.name)


@functools.lru_cache(maxsize=None)
def load_pack_file(path: str) -> DataPack:
    """Load and compile one pack file. Raises on anything malformed.

    **Memoized, so one pack file is one object for the life of the process.**
    That is not an optimization - it is required for correctness, and the bug it
    prevents is silent. `registry._ClaimGatedRegistry` gates each pack's hooks on
    `ctx.pack is owner`, an IDENTITY test. A module-backed pack is a singleton
    (`module.PACK`), so identity holds however many times `load_packs()` is
    called. Without this cache a data pack would be a fresh object per call, and
    any caller that loaded packs twice - once to register hooks, once to resolve
    - would find the gate never matching: the pack would claim documents
    correctly and then its ladder would never run, leaving every one of them at
    the pipeline default. `build_pipeline` happens to load once and share the
    list, so the shipped path was safe, but "happens to" is not a contract.

    The cache means an authoring session must restart the process to see an edit
    to `pack.json` - exactly as it must for a change to a pack MODULE, which the
    import system caches the same way. Personas are still read from disk on every
    call, so the thing being iterated on stays live.
    """
    try:
        with open(path) as fh:
            spec = json.load(fh)
    except OSError as exc:
        raise PackSpecError(f"{path}: cannot be read: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PackSpecError(f"{path}: is not valid JSON: {exc}") from exc
    if not isinstance(spec, dict):
        raise PackSpecError(f"{path}: expected a JSON object")
    return DataPack(spec, directory=os.path.dirname(os.path.abspath(path)))
