"""Stable core exports for resume QA.

这个包只导出最常用的 schema/config 合同，方便外部调用方稳定 import。
规则、inspection、answer generation 等能力应从具体 core 子包导入，避免
把根包变成隐藏业务逻辑的大 barrel。
"""

from .config import ResumeQAConfig, load_config
from .schemas import (
    CandidateBrief,
    CandidateScore,
    EvidenceRef,
    IntentName,
    JDScoringCriteria,
    QueryPlan,
    ResumeQAState,
    SubTaskPlan,
    ToolCallSpec,
)

__all__ = [
    "CandidateBrief",
    "CandidateScore",
    "EvidenceRef",
    "IntentName",
    "JDScoringCriteria",
    "QueryPlan",
    "ResumeQAConfig",
    "ResumeQAState",
    "SubTaskPlan",
    "ToolCallSpec",
    "load_config",
]
