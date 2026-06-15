"""Stable public exports for deterministic read-only resume QA tools.

上层代码优先通过 get_tool_registry() 调用工具；这里保留直接导出是为了兼容
已有 import 路径。
"""

from .registry import (
    TOOL_REGISTRY,
    build_comparison_pack,
    count_candidates,
    filter_candidates,
    get_candidate_brief,
    get_candidate_evidence,
    get_candidate_profile_intro,
    get_candidate_profiles_intro,
    get_tool_registry,
    hybrid_search_candidates,
    list_all_candidates,
    load_default_jd_criteria,
    load_general_resume_criteria,
    rank_candidates,
    resolve_candidate_reference,
    score_candidate_for_jd,
    score_candidates_for_jd,
    search_candidate_evidence,
)

__all__ = [
    "TOOL_REGISTRY",
    "build_comparison_pack",
    "count_candidates",
    "filter_candidates",
    "get_candidate_brief",
    "get_candidate_evidence",
    "get_candidate_profile_intro",
    "get_candidate_profiles_intro",
    "get_tool_registry",
    "hybrid_search_candidates",
    "list_all_candidates",
    "load_default_jd_criteria",
    "load_general_resume_criteria",
    "rank_candidates",
    "resolve_candidate_reference",
    "score_candidate_for_jd",
    "score_candidates_for_jd",
    "search_candidate_evidence",
]
