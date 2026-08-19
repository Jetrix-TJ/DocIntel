"""Default stage sequence: 9 stages across 11 modules (stage 5 has three variants)."""

from __future__ import annotations

from docintel.pipeline.stages.s1_intake import Intake
from docintel.pipeline.stages.s2_filter import AttachmentFilter
from docintel.pipeline.stages.s3_classify import Classify
from docintel.pipeline.stages.s4_persona import PersonaLookup
from docintel.pipeline.stages.s4b_processing_profile import ResolveProcessingProfile
from docintel.pipeline.stages.s5a_cached import ApplyCachedRules
from docintel.pipeline.stages.s5b_vision import VisionOneShot
from docintel.pipeline.stages.s5c_agent import AgentEscalation
from docintel.pipeline.stages.s6_capture import CaptureFields
from docintel.pipeline.stages.s7_gate import ConfidenceGate
from docintel.pipeline.stages.s8_emit import EmitRecord

__all__ = [
    "AgentEscalation", "ApplyCachedRules", "AttachmentFilter", "CaptureFields",
    "Classify", "ConfidenceGate", "EmitRecord", "Intake", "PersonaLookup",
    "ResolveProcessingProfile", "VisionOneShot", "build_default_stages", "build_pipeline",
]


def build_default_stages(
    vision: object,
    hooks: object | None = None,
    packs: object | None = None,
    store: object | None = None,
    jobs: object | None = None,
    export_layouts: frozenset[str] = frozenset(),
) -> list[object]:
    """The eight stages (plus the processing-profile decision), wired to
    whatever packs are loaded.

    `hooks` is threaded into `Classify` because `classifySignals` fires *inside*
    Stage 3 rather than at a stage boundary - a pack's ladder has to run before
    the default classification, not after it. Every other socket is a boundary
    the Runner owns.

    `jobs` (a `docintel.jobs.store.SQLiteJobQueue`, or any object with the same
    `enqueue_once` signature) goes to BOTH `AgentEscalation` and
    `ConfidenceGate` - they enqueue two different kinds of job (a hard-miss
    sender with no persona vs. a persona hit with no known prior_balance_basis)
    from two different points in the pipeline, and one queue instance keeps
    both writing to the same store. Defaults to `None` everywhere, exactly
    like `vision`/`store` above, so omitting it stays a fully safe no-op.

    `export_layouts` is the set of layout names `ResolveProcessingProfile` will
    accept in a persona's `processing_profile.export` list - injected rather
    than importing `docintel.export` directly, so building the default stage
    list never requires the optional `openpyxl` extra just to validate a
    string. Defaults to empty, which means any persona naming an export layout
    fails loudly at resolution time until a real caller passes the registry.
    """
    return [
        Intake(),
        AttachmentFilter(),
        Classify(hooks=hooks, packs=packs),      # type: ignore[arg-type]
        PersonaLookup(store=store),
        ResolveProcessingProfile(store=store, export_layouts=export_layouts),
        ApplyCachedRules(),
        VisionOneShot(vision=vision),
        AgentEscalation(jobs=jobs),
        CaptureFields(),
        ConfidenceGate(jobs=jobs),
        EmitRecord(),
    ]


def build_pipeline(
    vision: object,
    jobs: object | None = None,
    hooks: object | None = None,
    extra_packs: list[object] | None = None,
) -> object:
    """A Runner with every pack loaded, its hooks registered and its personas indexed.

    One function so the three things that must agree cannot drift: the packs whose
    hooks are registered, the packs `Classify` resolves against, and the packs
    whose personas Stage 4 can find.

    `jobs` defaults to `None` - a safe no-op, exactly like `vision`/`store` in
    `build_default_stages` - rather than silently opening a real, shared
    `var/jobs.sqlite3`. A function used from tests, the CLI, and the web UI is
    the wrong place for a surprising disk side effect; each real caller that
    wants human-in-the-loop escalation live constructs its own
    `docintel.jobs.store.SQLiteJobQueue` and passes it explicitly (see
    `cli.py::_build_runner` and `webui/app.py::create_app`).

    `hooks`, if given, is a `HookRegistry` the caller already registered their own
    hooks on (e.g. a `beforeEmit` hook that inspects `ctx.review_flag`/`ctx.lane` and
    fires a real-time notification) - this function adds the domain packs' own
    hooks to that SAME registry rather than building a fresh one, so a caller's
    hooks and the packs' hooks coexist instead of the caller's being silently
    discarded. Omitting `hooks` reproduces the old behavior exactly: a fresh
    registry with only the packs' own hooks on it.

    `extra_packs`, if given, is a list of caller-supplied `Pack`-protocol objects
    (e.g. `docintel.packs.datapack.load_pack_file("my_packs/acme/pack.json")`)
    appended after the shipped packs. This is the extension point for a wholly
    new company that no shipped pack claims at all - the caller's `pack.json`/
    `personas/` live entirely in their own project, never inside this installed
    package, so nothing here needs editing or upgrading in lockstep. For adding
    a new vendor to an EXISTING shipped pack instead (e.g. a new carrier under
    `digitaldirection`), see `DOCINTEL_EXTRA_PERSONAS_DIR`
    (`registry.load_extra_personas`/`load_extra_aliases`) - a different
    extension point, since that data has to reach a pack already in this list,
    not arrive as a new entry in it.
    """
    from docintel.export import layout_names
    from docintel.packs.registry import load_packs, register_all
    from docintel.packs.store import PackPersonaStore
    from docintel.pipeline.hooks import HookRegistry
    from docintel.pipeline.runner import Runner

    packs = load_packs() + list(extra_packs or [])
    hooks = hooks if hooks is not None else HookRegistry()
    register_all(hooks, packs)
    return Runner(
        stages=build_default_stages(
            vision=vision,
            hooks=hooks,
            packs=packs,
            store=PackPersonaStore(packs),
            jobs=jobs,
            export_layouts=layout_names(),
        ),
        hooks=hooks,
    )
