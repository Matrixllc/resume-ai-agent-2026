"""Tool adapters for JD scoring."""

from __future__ import annotations

from typing import Any, Dict, List

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.schemas import CandidateScore, JDScoringCriteria
from resume_query_ai_qa.scoring import score_candidate_material_for_jd

from .candidate_tools import get_candidate_brief, list_all_candidates
from .evidence_tools import get_candidate_evidence


def score_candidate_for_jd(
    resume_identity: str,
    criteria: JDScoringCriteria | Dict[str, Any],
    config: ResumeQAConfig | None = None,
) -> CandidateScore:
    """加载单个候选人的事实，并按 JD 标准评分。"""
    brief = get_candidate_brief(resume_identity)
    evidence_refs = get_candidate_evidence(resume_identity, limit=12)
    return score_candidate_material_for_jd(brief, evidence_refs, criteria, config=config)


def score_candidates_for_jd(
    candidate_ids: List[str] | None,
    criteria: JDScoringCriteria | Dict[str, Any],
    config: ResumeQAConfig | None = None,
) -> List[CandidateScore]:
    """加载候选人事实，并按 JD 标准批量评分。

    空的限定候选池是真实结果，不能把空列表解释为全部候选人。
    """
    ids = candidate_ids if candidate_ids is not None else [item.resume_identity for item in list_all_candidates()]
    return [score_candidate_for_jd(candidate_id, criteria, config=config) for candidate_id in ids]
