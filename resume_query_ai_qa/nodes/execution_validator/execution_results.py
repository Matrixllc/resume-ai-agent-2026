"""Execution tool result consistency checks.

这个文件负责什么：
  检查工具结果之间是否自洽，例如 count 数量、compare 人数、open_recall 空结果。

应该从哪个函数读起：
  validate_count_results() -> validate_compare_results() -> validate_empty_retrieval_results()。

不会负责什么：
  不检查必需工具是否齐全，不检查 evidence 覆盖，不检查 candidate lineage。
"""

from __future__ import annotations

from typing import List

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.rules.execution_policy_rules import scenario_for_intent
from resume_query_ai_qa.core.inspection.plan_inspection import plan_intent_calls as _intent_calls
from resume_query_ai_qa.core.inspection.result_inspection import (
    last_candidate_list_before_count as _last_candidate_list_before_count,
    last_ok_data as _last_ok_data,
)
from resume_query_ai_qa.core.schemas import QueryPlan, RouterOutput, ToolResult


def validate_count_results(plan: QueryPlan, tool_results: List[ToolResult]) -> List[str]:
    """检查 count_candidates 的数量是否等于前序候选人集合长度。"""
    intents = [intent for intent, _calls in _intent_calls(plan)]
    if "candidate_count" not in intents:
        return []
    errors: List[str] = []
    count = _last_ok_data(tool_results, "count_candidates")
    if count is None:
        return errors
    candidates = _last_candidate_list_before_count(tool_results)
    if candidates is not None and int(count) != len(candidates):
        errors.append(f"count_candidates returned {count}, but candidate source has {len(candidates)} items")
    return errors


def validate_compare_results(
    plan: QueryPlan,
    tool_results: List[ToolResult],
    config: ResumeQAConfig,
) -> List[str]:
    """检查 build_comparison_pack 是否返回 validation.yaml 要求的候选人数。"""
    intents = [intent for intent, _calls in _intent_calls(plan)]
    if "candidate_compare_pair" not in intents:
        return []
    compare = dict(config.validation.get("compare_pair", {}) or {})
    exact_count = int(compare.get("exact_candidate_count", 2) or 2)
    payload = _last_ok_data(tool_results, "build_comparison_pack")
    if not isinstance(payload, dict):
        return []
    candidate_ids = [str(item) for item in payload.get("candidate_ids", []) if str(item).strip()]
    if len(candidate_ids) != exact_count:
        return [f"build_comparison_pack returned {len(candidate_ids)} candidates, expected {exact_count}"]
    return []


def validate_empty_retrieval_results(
    plan: QueryPlan,
    tool_results: List[ToolResult],
    router_output: RouterOutput | None = None,
    config: ResumeQAConfig | None = None,
) -> List[str]:
    """检查 open_recall 下 filter_candidates 空结果是否需要进入 query fallback。"""
    if not _allows_open_recall_query_fallback(plan, router_output, config):
        return []
    if any(result.ok and result.tool_name == "hybrid_search_candidates" for result in tool_results):
        return []
    if any(result.ok and result.tool_name == "filter_candidates" and result.data == [] for result in tool_results):
        return ["filter_candidates returned no candidates"]
    return []


__all__ = ["validate_compare_results", "validate_count_results", "validate_empty_retrieval_results"]


def _allows_open_recall_query_fallback(plan: QueryPlan, router_output: RouterOutput | None, config: ResumeQAConfig | None = None) -> bool:
    """判断当前 plan 中是否存在 open_recall scenario。"""
    if router_output is None:
        return False
    intents = [intent for intent, _calls in _intent_calls(plan)]
    return any(scenario_for_intent(router_output, intent) == "open_recall" for intent in intents)
