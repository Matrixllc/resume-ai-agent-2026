"""Stable core contracts for resume QA.

Nodes should import rule helpers from their concrete core modules instead of
using this package as a broad compatibility barrel.
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
