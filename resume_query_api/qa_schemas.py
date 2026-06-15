from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


class QAAskRequest(BaseModel):
    question: str
    session_context: Dict[str, Any] = Field(default_factory=dict)
    use_llm: bool = True
    debug: bool = False


class QAAskResponse(BaseModel):
    status: Literal["ok", "needs_clarification", "failed"]
    answer: str = ""
    clarification_required: bool = False
    clarification_question: str = ""
    clarification_options: List[str] = Field(default_factory=list)
    used_evidence_refs: List[Dict[str, Any]] = Field(default_factory=list)
    ranking: List[Dict[str, Any]] = Field(default_factory=list)
    comparison_profiles: List[Dict[str, Any]] = Field(default_factory=list)
    comparison_candidate_ids: List[str] = Field(default_factory=list)
    updated_session_context: Dict[str, Any] = Field(default_factory=dict)
    trace: Dict[str, Any] | None = None
