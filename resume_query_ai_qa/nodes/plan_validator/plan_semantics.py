"""Plan semantics checks against RouterOutput.

这个文件负责什么：
- 检查 QueryPlan 是否满足 RouterOutput 的语义合同。
- 确认 intent、normalized_conditions、context_policy、requires_evidence 都进入计划。

应该从哪个函数读起：
- validate_plan_semantics
"""

from __future__ import annotations

from typing import List

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.rules.execution_policy_rules import scenario_for_intent
from resume_query_ai_qa.core.rules.context_resolver import candidate_ids_for_context, has_required_context
from resume_query_ai_qa.core.rules.taxonomy import taxonomy_entry_types
from resume_query_ai_qa.core.inspection.plan_inspection import (
    is_structured_argument_ref as _is_structured_argument_ref,
    plan_intent_calls as _intent_calls,
)
from resume_query_ai_qa.core.inspection.result_inspection import normalize_string_list
from resume_query_ai_qa.core.schemas import QueryPlan, RouterOutput, ToolCallSpec


def validate_plan_semantics(
    plan: QueryPlan,
    router_output: RouterOutput,
    *,
    session_context: dict | None = None,
    config: ResumeQAConfig | None = None,
) -> List[str]:
    """校验 QueryPlan 是否满足 RouterOutput 的语义要求。"""
    cfg = config or load_config()
    errors: List[str] = []
    intent_calls = _intent_calls(plan)
    all_calls = [call for _intent, calls in intent_calls for call in calls]
    all_tool_names = {call.name for call in all_calls}

    if router_output.intent == "out_of_scope":
        if all_calls:
            errors.append("semantic: out_of_scope must not execute tools")
        return errors

    if router_output.intent == "compound":
        planned = {intent for intent, _calls in intent_calls}
        for sub_intent in router_output.sub_intent_candidates:
            if sub_intent not in planned:
                errors.append(f"semantic: compound plan missing sub intent {sub_intent}")

    if router_output.intent == "candidate_ranking" or "candidate_ranking" in router_output.sub_intent_candidates:
        if not ({"load_default_jd_criteria", "load_general_resume_criteria", "extract_jd_criteria"} & all_tool_names):
            errors.append("semantic: candidate_ranking requires JD criteria tool")
        if "score_candidates_for_jd" not in all_tool_names:
            errors.append("semantic: candidate_ranking requires scoring tool")
        if "rank_candidates" not in all_tool_names:
            errors.append("semantic: candidate_ranking requires ranking tool")

    if router_output.intent == "candidate_filter":
        for call in all_calls:
            if call.name == "filter_candidates" and not call.arguments:
                errors.append("semantic: filter_candidates arguments are empty; current intent/scenario is allowed, but preference_target was not compiled into filter args")
            if call.name == "hybrid_search_candidates" and not str((call.arguments or {}).get("query") or "").strip():
                errors.append("semantic: hybrid_search_candidates query is empty; current intent/scenario is allowed, but preference_target was not compiled into recall query")

    planned_intents = {intent for intent, _calls in intent_calls}
    hard_domain_source_required = requires_hard_domain_source(planned_intents, router_output, config)
    hard_candidate_pool_required = bool(planned_intents & {"candidate_count", "candidate_list", "candidate_filter", "candidate_ranking"})
    for condition in router_output.normalized_conditions:
        if condition.matched_by.startswith("preference_target:"):
            continue
        if condition.type not in {"domain", "skill", "concept"} or not str(condition.normalized_value).strip():
            continue
        if hard_domain_source_required and condition.type == "domain":
            if not plan_uses_structured_filter(all_calls, "domain", str(condition.normalized_value)):
                errors.append(f"semantic: hard domain {condition.normalized_value} must be used by filter_candidates domain arrays")
            continue
        if hard_candidate_pool_required and condition.type in {"skill", "concept"} and not router_looks_like_open_recall(router_output, config):
            if not plan_uses_structured_filter(all_calls, condition.type, str(condition.normalized_value)):
                errors.append(f"semantic: hard {condition.type} {condition.normalized_value} must be used by filter_candidates structured arrays")
            continue
        terms = [str(condition.normalized_value), *[str(item) for item in condition.retrieval_terms]]
        if not any(plan_uses_term(all_calls, term) for term in terms if str(term).strip()):
            errors.append(f"semantic: normalized domain {condition.normalized_value} is not used by plan")

    if router_output.context_policy.uses_context and _missing_required_context(router_output, session_context or {}, cfg):
        errors.append(f"semantic: missing required {router_output.context_policy.context_ref_type} context")

    if router_output.context_policy.uses_context and _context_candidate_ids(router_output, session_context or {}) and not plan_limits_candidate_ids(all_calls):
        errors.append(f"semantic: {router_output.context_policy.context_ref_type} context was not applied to plan candidate_ids")

    evidence_relevant_intents = planned_intents - {"candidate_count", "candidate_list"}
    hard_filter_without_evidence = (
        evidence_relevant_intents == {"candidate_filter"}
        and scenario_for_intent(router_output, "candidate_filter") == "hard_filter"
    )
    if (
        router_output.requires_evidence
        and evidence_relevant_intents
        and not hard_filter_without_evidence
        and not (all_tool_names & set(cfg.tools_with_role("evidence_capable")))
    ):
        errors.append("semantic: evidence-required intent has no evidence-capable tool")

    if router_output.intent == "candidate_list" and _looks_like_candidate_scoped_evidence(router_output):
        errors.append("semantic: candidate-scoped evidence question cannot be planned as candidate_list")

    return errors


def plan_uses_term(calls: List[ToolCallSpec], term: str) -> bool:
    """判断计划参数或 query 中是否使用了某个 normalized term。"""
    target = str(term or "").strip().lower()
    if not target:
        return True
    for call in calls:
        args = call.arguments or {}
        if str(args.get("domain", "")).lower() == target:
            return True
        if _argument_tree_contains_value(args, target):
            return True
        query = str(args.get("query", "") or "").lower()
        if target in query:
            return True
    return False


def plan_uses_structured_filter(calls: List[ToolCallSpec], condition_type: str, value: str) -> bool:
    """判断 hard 条件是否进入 filter_candidates 的结构化参数。"""
    target = str(value or "").strip().lower()
    if not target:
        return True
    keys = {
        "domain": {"domain", "domains_any", "domains_all"},
        "skill": {"skills", "skills_all"},
        "concept": {"project_tags", "concepts_all"},
    }.get(condition_type, set())
    return any(
        call.name == "filter_candidates"
        and any(_argument_contains_value((call.arguments or {}).get(key), target) for key in keys)
        for call in calls
    )


def requires_hard_domain_source(planned_intents: set[str], router_output: RouterOutput, config: ResumeQAConfig | None = None) -> bool:
    """判断当前计划是否必须使用结构化 domain 候选来源。"""
    if not planned_intents & {"candidate_count", "candidate_list", "candidate_filter", "candidate_ranking"}:
        return False
    if router_looks_like_open_recall(router_output, config):
        return False
    return any(is_hard_domain_condition(condition) for condition in router_output.normalized_conditions)


def router_looks_like_open_recall(router_output: RouterOutput, config: ResumeQAConfig | None = None) -> bool:
    """判断 RouterOutput 中是否存在 open_recall scenario。"""
    intents = router_output.sub_intent_candidates if router_output.intent == "compound" else [router_output.intent]
    return any(scenario_for_intent(router_output, str(intent)) == "open_recall" for intent in intents)


def is_hard_domain_condition(condition) -> bool:
    """判断某个 normalized condition 是否是真正的 domain 硬条件。"""
    if getattr(condition, "type", "") != "domain" or not str(getattr(condition, "normalized_value", "") or "").strip():
        return False
    entry_types = taxonomy_entry_types(str(getattr(condition, "normalized_value", "") or ""))
    if entry_types and "domain" not in entry_types:
        return False
    return True


def plan_limits_candidate_ids(calls: List[ToolCallSpec]) -> bool:
    """判断计划是否把上下文候选人 ID 限制传入工具参数。"""
    for call in calls:
        if call.name not in {"filter_candidates", "hybrid_search_candidates", "search_candidate_evidence"}:
            continue
        raw = call.arguments.get("candidate_ids")
        if isinstance(raw, list) and raw:
            return True
        if isinstance(raw, str) and raw.strip():
            return True
        if _is_structured_argument_ref(raw):
            return True
    return False


def _missing_required_context(router_output: RouterOutput, session_context: dict, config: ResumeQAConfig) -> bool:
    """判断当前 session_context 是否缺少 router 要求的上下文。"""
    ref_type = router_output.context_policy.context_ref_type
    if not has_required_context(ref_type, session_context, config.router_rules):
        return True
    if ref_type == "candidate_pool":
        return not normalize_string_list(session_context.get("last_candidate_pool_ids"))
    if ref_type == "last_candidate":
        return not str(session_context.get("last_candidate_id") or "").strip()
    if ref_type in {"ranking_top", "ranking_top_k"}:
        return not normalize_string_list(session_context.get("last_ranking_candidate_ids"))
    if ref_type == "comparison_pair":
        return len(normalize_string_list(session_context.get("last_comparison_candidate_ids"))) < 2
    if ref_type == "jd":
        return not session_context.get("last_jd_criteria")
    return False


def _context_candidate_ids(router_output: RouterOutput, session_context: dict) -> list[str]:
    """获取当前上下文策略要求进入计划的候选人集合。"""
    if any(condition.type == "candidate_name" for condition in router_output.normalized_conditions):
        return []
    return candidate_ids_for_context(router_output.context_policy, session_context)


def _looks_like_candidate_scoped_evidence(router_output: RouterOutput) -> bool:
    """判断证据查询是否限定候选人范围并返回布尔值。"""
    has_candidate = any(condition.type == "candidate_name" for condition in router_output.conditions + router_output.normalized_conditions)
    has_domain = any(condition.type == "domain" for condition in router_output.normalized_conditions)
    evidence_text = " ".join(
        evidence
        for item in router_output.sub_intent_evidence
        for evidence in item.evidence
    )
    return bool(has_candidate and has_domain and any(token in evidence_text for token in ["经验", "经历", "experience"]))


def _argument_contains_value(raw, target: str) -> bool:
    """获取参数contains值并返回。"""
    values = raw if isinstance(raw, list) else [raw]
    return any(str(item or "").strip().lower() == target for item in values)


def _argument_tree_contains_value(raw, target: str) -> bool:
    """递归判断参数树是否包含某个结构化条件值。"""
    if isinstance(raw, dict):
        if "$ref" in raw:
            return False
        return any(_argument_tree_contains_value(value, target) for value in raw.values())
    if isinstance(raw, list):
        return any(_argument_tree_contains_value(value, target) for value in raw)
    return str(raw or "").strip().lower() == target


__all__ = [
    "is_hard_domain_condition",
    "plan_limits_candidate_ids",
    "plan_uses_structured_filter",
    "plan_uses_term",
    "requires_hard_domain_source",
    "router_looks_like_open_recall",
    "validate_plan_semantics",
]
