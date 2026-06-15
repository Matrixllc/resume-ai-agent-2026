"""Plan boundary checks for count, ranking, and pair comparison.

这个文件负责什么：
- 检查特定 intent 的硬边界。
- count/ranking/compare 这类 intent 不能只靠通用结构检查。

应该从哪个函数读起：
- validate_compare_boundaries
- validate_ranking_boundaries
- validate_count_boundaries
"""

from __future__ import annotations

from typing import List

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.inspection.plan_inspection import (
    candidate_ids_argument_from_calls as _candidate_ids_argument_from_calls,
    candidate_ids_from_calls as _candidate_ids_from_calls,
    is_argument_ref as _is_argument_ref,
    is_structured_argument_ref as _is_structured_argument_ref,
    plan_intent_calls as _intent_calls,
)
from resume_query_ai_qa.core.schemas import QueryPlan


def validate_compare_boundaries(plan: QueryPlan, config: ResumeQAConfig) -> List[str]:
    """校验 candidate_compare_pair 是否刚好限定两个候选人。"""
    errors: List[str] = []
    compare = dict(config.validation.get("compare_pair", {}) or {})
    exact_count = int(compare.get("exact_candidate_count", 2) or 2)
    for intent, calls in _intent_calls(plan):
        if intent != "candidate_compare_pair":
            continue
        candidate_ref = _candidate_ids_argument_from_calls(calls)
        if (isinstance(candidate_ref, str) and _is_argument_ref(candidate_ref)) or _is_structured_argument_ref(candidate_ref):
            continue
        candidate_ids = _candidate_ids_from_calls(calls)
        if len(candidate_ids) != exact_count:
            errors.append(f"candidate_compare_pair requires exactly {exact_count} candidates, got {len(candidate_ids)}")
    return errors


def validate_ranking_boundaries(plan: QueryPlan, config: ResumeQAConfig) -> List[str]:
    """校验 candidate_ranking 是否包含 criteria、score 和 rank。"""
    errors: List[str] = []
    ranking = dict(config.validation.get("ranking", {}) or {})
    for intent, calls in _intent_calls(plan):
        if intent != "candidate_ranking":
            continue
        tool_names = {call.name for call in calls}
        has_criteria = bool(set(config.tools_with_role("criteria_source")) & tool_names)
        if ranking.get("requires_jd_criteria", True) and not has_criteria:
            errors.append("candidate_ranking requires JD criteria before scoring")
        if "rank_candidates" in tool_names and "score_candidates_for_jd" not in tool_names:
            errors.append("rank_candidates requires score_candidates_for_jd first")
    return errors


def validate_count_boundaries(plan: QueryPlan, config: ResumeQAConfig | None = None) -> List[str]:
    """校验 candidate_count 是否有候选来源并调用 count_candidates。"""
    errors: List[str] = []
    all_calls = [call for _intent, calls in _intent_calls(plan) for call in calls]
    candidate_sources = set(config.tools_with_role("candidate_source")) if config else set()
    has_canonical_source = any(call.name in candidate_sources and call.name != "resolve_candidate_reference" for call in all_calls)
    for intent, calls in _intent_calls(plan):
        if intent != "candidate_count":
            continue
        tool_names = [call.name for call in calls]
        if "count_candidates" not in tool_names:
            errors.append("candidate_count requires count_candidates")
        if not has_canonical_source:
            errors.append("candidate_count requires a candidate source before count_candidates")
    return errors


__all__ = ["validate_compare_boundaries", "validate_count_boundaries", "validate_ranking_boundaries"]
