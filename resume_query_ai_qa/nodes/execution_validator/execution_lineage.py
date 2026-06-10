"""Execution candidate lineage checks."""

from __future__ import annotations

from typing import List

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.inspection.result_inspection import (
    candidate_ids_from_data as _candidate_ids_from_data,
    normalize_string_list,
    profile_candidate_ids as _profile_candidate_ids,
    ranked_candidate_ids as _ranked_candidate_ids,
    resolved_candidate_ids as _resolved_candidate_ids,
)
from resume_query_ai_qa.core.schemas import QueryPlan, RouterOutput, ToolResult
from resume_query_ai_qa.core.rules.evidence_policy import collect_evidence_refs


def validate_candidate_lineage(
    plan: QueryPlan,
    tool_results: List[ToolResult],
    *,
    router_output: RouterOutput | None = None,
    session_context: dict | None = None,
    config: ResumeQAConfig | None = None,
) -> List[str]:
    """校验候选人结果依赖链并返回错误列表。"""
    errors: List[str] = []
    canonical_ids = _canonical_candidate_ids(plan, tool_results, config or load_config())
    resolved_ids = _resolved_candidate_ids(tool_results)
    session_pool = set(normalize_string_list((session_context or {}).get("last_candidate_pool_ids")))
    if router_output and router_output.context_policy.uses_context and router_output.context_policy.context_ref_type == "candidate_pool" and session_pool:
        leaked = sorted(candidate_id for candidate_id in canonical_ids if candidate_id not in session_pool)
        if leaked:
            errors.append(f"semantic: canonical candidate_pool escaped session context: {leaked}")

    profile_ids = _profile_candidate_ids(tool_results)
    expected_for_profile = resolved_ids or canonical_ids
    if expected_for_profile:
        leaked = sorted(candidate_id for candidate_id in profile_ids if candidate_id not in expected_for_profile)
        if leaked:
            errors.append(f"semantic: candidate_profile escaped resolved candidates: {leaked}")

    ranked_ids = _ranked_candidate_ids(tool_results)
    if canonical_ids:
        leaked = sorted(candidate_id for candidate_id in ranked_ids if candidate_id not in canonical_ids)
        if leaked:
            errors.append(f"semantic: ranked_candidates escaped canonical candidate_pool: {leaked}")

    evidence_expected = resolved_ids or canonical_ids
    if evidence_expected:
        evidence_ids = {
            ref.resume_identity
            for ref in collect_evidence_refs(tool_results)
            if ref.resume_identity
        }
        leaked = sorted(candidate_id for candidate_id in evidence_ids if candidate_id not in evidence_expected)
        if leaked:
            errors.append(f"semantic: evidence_collection escaped candidate lineage: {leaked}")
    return errors


def _canonical_candidate_ids(plan: QueryPlan, tool_results: List[ToolResult], config: ResumeQAConfig) -> set[str]:
    """获取规范候选人标识集合并返回。"""
    bindings = [binding for binding in plan.artifact_bindings if binding.artifact_type == "candidate_collection"]
    accepted = bindings[0].accepted_producer if bindings else ""
    source_tools = set(config.tools_with_role("candidate_source")) - {"resolve_candidate_reference"}
    for result in tool_results:
        if not result.ok or result.tool_name not in source_tools:
            continue
        if accepted and result.tool_name != accepted:
            continue
        ids = set(_candidate_ids_from_data(result.data))
        if ids:
            return ids
    for result in tool_results:
        if result.ok and result.tool_name in source_tools:
            ids = set(_candidate_ids_from_data(result.data))
            if ids:
                return ids
    return set()


__all__ = ["validate_candidate_lineage"]
