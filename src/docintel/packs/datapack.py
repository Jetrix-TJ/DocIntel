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


def _validate_vision_defaults(pack_name: str, spec: dict[str, Any]) -> None:
    """Fail loudly on a typo'd type name AT PACK-LOAD TIME, not silently at
    extraction time. `vision_defaults` is GEMINI-ONLY - see `DataPack.
    vision_defaults`'s own docstring - so a bad type name here can never be
    caught by the grammar validator (V1-V14), which never sees this key at
    all."""
    from docintel.adapters.vision.hints import recognized_vision_types

    recognized = recognized_vision_types()
    for doc_type, entry in spec.items():
        if not isinstance(entry, dict):
            raise PackSpecError(f"{pack_name}: vision_defaults.{doc_type} must be an object")
        fields = entry.get("fields", {})
        if not isinstance(fields, dict):
            raise PackSpecError(f"{pack_name}: vision_defaults.{doc_type}.fields must be an object")
        for field_name, type_name in fields.items():
            if type_name not in recognized:
                raise PackSpecError(
                    f"{pack_name}: vision_defaults.{doc_type}.fields.{field_name} has "
                    f"unrecognized type {type_name!r}; expected one of {sorted(recognized)}"
                )
        tables = entry.get("tables", {})
        if not isinstance(tables, dict):
            raise PackSpecError(f"{pack_name}: vision_defaults.{doc_type}.tables must be an object")
        for table_name, columns in tables.items():
            if not isinstance(columns, dict) or not columns:
                raise PackSpecError(
                    f"{pack_name}: vision_defaults.{doc_type}.tables.{table_name} must be "
                    "a non-empty object of column -> type"
                )
            for col_name, type_name in columns.items():
                if type_name not in recognized:
                    raise PackSpecError(
                        f"{pack_name}: vision_defaults.{doc_type}.tables.{table_name}."
                        f"{col_name} has unrecognized type {type_name!r}; expected one "
                        f"of {sorted(recognized)}"
                    )


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


def _load_extra_personas(pack_name: str) -> list[dict[str, Any]]:
    """`registry.load_extra_personas`, imported lazily - same cycle reason as
    `_primary_text` above."""
    from docintel.packs.registry import load_extra_personas

    return load_extra_personas(pack_name)


def _load_extra_aliases(pack_name: str) -> dict[str, str]:
    """`registry.load_extra_aliases`, imported lazily - same cycle reason as
    `_primary_text` above."""
    from docintel.packs.registry import load_extra_aliases

    return load_extra_aliases(pack_name)


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

        vision_defaults_spec = spec.get("vision_defaults", {})
        if not isinstance(vision_defaults_spec, dict):
            raise PackSpecError(f"{name}: vision_defaults must be an object")
        self._vision_defaults: dict[str, Any] = {
            k: v for k, v in vision_defaults_spec.items() if k != "_why"
        }
        _validate_vision_defaults(name, self._vision_defaults)

        # Compiled at load, so a malformed rule is an error when the pack is
        # registered rather than a rung that silently never fires.
        self.ladder, self.tag_rules = declarative.compile_classification(spec)
        claim_spec = spec.get("claim")
        if not isinstance(claim_spec, dict):
            raise PackSpecError(f"{name}: a pack must declare how it claims a document")
        self.claim_guard = claims.compile_claim(
            claim_spec, aliases=self._aliases, pack_name=name
        )

        unknown = set(self._fields) - set(self.doc_types)
        if unknown:
            raise PackSpecError(
                f"{name}: fields declared for undeclared doc_types {sorted(unknown)}"
            )

        # Validate that each fields.<doc_type> entry only has allowed keys. A typo
        # like "require" instead of "required" would otherwise silently disable
        # required-field enforcement with no error anywhere.
        _ALLOWED_FIELDS_KEYS = frozenset({"all", "required", "any_of", "derived_only", "_why"})
        for doc_type, field_spec in self._fields.items():
            if not isinstance(field_spec, dict):
                raise PackSpecError(f"{name}: fields[{doc_type!r}] must be an object")
            bad_keys = set(field_spec) - _ALLOWED_FIELDS_KEYS
            if bad_keys:
                raise PackSpecError(
                    f"{name}: fields[{doc_type!r}] has unrecognized key(s) {sorted(bad_keys)} - "
                    f"only {sorted(_ALLOWED_FIELDS_KEYS)} are valid. A typo here (e.g. 'require' "
                    f"instead of 'required') would otherwise silently disable that key's "
                    f"enforcement with no error."
                )

        unknown_vision = set(self._vision_defaults) - set(self.doc_types)
        if unknown_vision:
            raise PackSpecError(
                f"{name}: vision_defaults declared for undeclared doc_types "
                f"{sorted(unknown_vision)}"
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

    def vision_defaults(self, doc_type: str) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
        """`(field_name -> type, table_name -> {column -> type})` for a
        persona-less document of this doc_type - or `({}, {})` if this pack
        declares none.

        **GEMINI-ONLY. Never read by the rule-based grammar/persona engine
        (Stage 5a).** This is the declarative answer for the case a
        `row_group` persona selector cannot cover: 1000+ vendors this pack
        accepts with no persona and no single fixed layout to anchor a
        selector against. A user writes plain type names here (`"text"`,
        `"currency"`/`"$"`, `"decimal"`, `"date"`...) - the same vocabulary
        `adapters.vision.hints.recognized_vision_types()` validates at load
        time - never anchors, regions, or other grammar concepts, because
        Stage 5b's vision call has no page geometry to walk; it reads
        visually, regardless of layout.

        **Not on the `registry.Pack` Protocol.** Adding a required method
        there would force the two hand-coded module packs (`northstar`,
        `digitaldirection`) to implement it immediately even though neither
        declares any today. `s5b_vision.py` reads this defensively via
        `getattr(ctx.pack, "vision_defaults", None)`.
        """
        entry = self._vision_defaults.get(doc_type, {})
        fields = dict(entry.get("fields", {}))
        tables = {name: dict(columns) for name, columns in entry.get("tables", {}).items()}
        return fields, tables

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
        if os.path.isdir(directory):
            for filename in sorted(os.listdir(directory)):
                if filename.endswith(".json"):
                    with open(os.path.join(directory, filename)) as fh:
                        out.append(json.load(fh))
        # A vendor from a directory the CALLER owns (DOCINTEL_EXTRA_PERSONAS_DIR)
        # - lets a third party extend even a shared, community data pack's own
        # vendor list without editing its pack.json/personas/ at all. See
        # registry.load_extra_personas's own docstring; `spt_metals` (a thin
        # wrapper delegating straight to a DataPack) gets this for free.
        out.extend(_load_extra_personas(self.name))
        return out

    # -- vendor fingerprint ---------------------------------------------------

    def _canonical_vendor(self, ctx: JobContext) -> str | None:
        """The canonical vendor key for this document, from data alone.

        Matches each `(printed, canonical)` pair in `aliases.literal`, merged
        with any external `DOCINTEL_EXTRA_PERSONAS_DIR` overlay
        (`registry.load_extra_aliases`), against the primary-page text -
        substring, word-boundary safe, on normalized names - so a pack author
        writes a plain company name, never a regex. This is the same matching
        power `northstar.aliases`' `PATTERN_ALIASES` gives it (its own
        `LITERAL_ALIASES` alone would need an exact whole-page match to fire,
        which real page text never gives it); here it comes for free from a
        name string.

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
            merged_aliases = {**self._aliases, **_load_extra_aliases(self.name)}
            for printed, canonical in merged_aliases.items():
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
