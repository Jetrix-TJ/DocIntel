"""Default stage sequence: 8 stages across 10 modules (stage 5 has three variants)."""

from __future__ import annotations

from docintel.pipeline.stages.s1_intake import Intake
from docintel.pipeline.stages.s2_filter import AttachmentFilter
from docintel.pipeline.stages.s3_classify import Classify
from docintel.pipeline.stages.s4_persona import PersonaLookup
from docintel.pipeline.stages.s5a_cached import ApplyCachedRules
from docintel.pipeline.stages.s5b_vision import VisionOneShot
from docintel.pipeline.stages.s5c_agent import AgentEscalation
from docintel.pipeline.stages.s6_capture import CaptureFields
from docintel.pipeline.stages.s7_gate import ConfidenceGate
from docintel.pipeline.stages.s8_emit import EmitRecord

__all__ = [
    "AgentEscalation", "ApplyCachedRules", "AttachmentFilter", "CaptureFields",
    "Classify", "ConfidenceGate", "EmitRecord", "Intake", "PersonaLookup",
    "VisionOneShot", "build_default_stages", "build_pipeline",
]


def build_default_stages(
    vision: object,
    hooks: object | None = None,
    packs: object | None = None,
    store: object | None = None,
) -> list[object]:
    """The eight stages, wired to whatever packs are loaded.

    `hooks` is threaded into `Classify` because `classifySignals` fires *inside*
    Stage 3 rather than at a stage boundary - a pack's ladder has to run before
    the default classification, not after it. Every other socket is a boundary
    the Runner owns.
    """
    return [
        Intake(),
        AttachmentFilter(),
        Classify(hooks=hooks, packs=packs),      # type: ignore[arg-type]
        PersonaLookup(store=store),
        ApplyCachedRules(),
        VisionOneShot(vision=vision),
        AgentEscalation(),
        CaptureFields(),
        ConfidenceGate(),
        EmitRecord(),
    ]


def build_pipeline(vision: object) -> object:
    """A Runner with every pack loaded, its hooks registered and its personas indexed.

    One function so the three things that must agree cannot drift: the packs whose
    hooks are registered, the packs `Classify` resolves against, and the packs
    whose personas Stage 4 can find.
    """
    from docintel.packs.registry import load_packs, register_all
    from docintel.packs.store import PackPersonaStore
    from docintel.pipeline.hooks import HookRegistry
    from docintel.pipeline.runner import Runner

    packs = load_packs()
    hooks = HookRegistry()
    register_all(hooks, packs)
    return Runner(
        stages=build_default_stages(
            vision=vision,
            hooks=hooks,
            packs=packs,
            store=PackPersonaStore(packs),
        ),
        hooks=hooks,
    )
