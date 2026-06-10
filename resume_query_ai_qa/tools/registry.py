"""Deterministic read-only QA tool registry.

The implementation lives in focused tool modules. This file is intentionally only
an import-与-register facade so graph nodes can keep using one stable registry
entrypoint while tool behavior remains reviewable by domain.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from resume_query_ai_qa.scoring import (
    extract_jd_criteria,
    load_default_jd_criteria,
    load_general_resume_criteria,
    rank_candidates,
)

from .candidate_tools import count_candidates, filter_candidates, get_candidate_brief, list_all_candidates
from .comparison_tools import build_comparison_pack
from .evidence_tools import get_candidate_evidence, hybrid_search_candidates, search_candidate_evidence
from .profile_tools import get_candidate_profile_intro, get_candidate_profiles_intro
from .reference_tools import resolve_candidate_reference
from .scoring_tools import score_candidate_for_jd, score_candidates_for_jd

ToolFunction = Callable[..., Any]

TOOL_REGISTRY: Dict[str, ToolFunction] = {
    "list_all_candidates": list_all_candidates,
    "filter_candidates": filter_candidates,
    "count_candidates": count_candidates,
    "get_candidate_brief": get_candidate_brief,
    "get_candidate_profile_intro": get_candidate_profile_intro,
    "get_candidate_profiles_intro": get_candidate_profiles_intro,
    "get_candidate_evidence": get_candidate_evidence,
    "search_candidate_evidence": search_candidate_evidence,
    "hybrid_search_candidates": hybrid_search_candidates,
    "resolve_candidate_reference": resolve_candidate_reference,
    "build_comparison_pack": build_comparison_pack,
    "load_default_jd_criteria": load_default_jd_criteria,
    "load_general_resume_criteria": load_general_resume_criteria,
    "extract_jd_criteria": extract_jd_criteria,
    "score_candidate_for_jd": score_candidate_for_jd,
    "score_candidates_for_jd": score_candidates_for_jd,
    "rank_candidates": rank_candidates,
}


def get_tool_registry() -> Dict[str, ToolFunction]:
    """返回可供执行图调用的只读工具表副本。"""
    return dict(TOOL_REGISTRY)
