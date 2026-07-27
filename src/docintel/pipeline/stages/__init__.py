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
    "VisionOneShot", "build_default_stages",
]


def build_default_stages(vision: object) -> list[object]:
    return [
        Intake(),
        AttachmentFilter(),
        Classify(),
        PersonaLookup(),
        ApplyCachedRules(),
        VisionOneShot(vision=vision),
        AgentEscalation(),
        CaptureFields(),
        ConfidenceGate(),
        EmitRecord(),
    ]
