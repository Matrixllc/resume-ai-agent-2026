"""Execution repair classification and fallback QueryPlan rewriting."""

from __future__ import annotations

from resume_query_ai_qa.core.inspection.plan_artifacts import with_artifact_bindings
from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.rules.behavior_contract import validation_action, validation_issues as build_validation_issues
from resume_query_ai_qa.core.rules.condition_rules import cleaned_retrieval_query
from resume_query_ai_qa.core.rules.execution_policy_rules import scenario_for_intent
from resume_query_ai_qa.core.rules.plan_building import with_structured_refs
from resume_query_ai_qa.core.schemas import QueryPlan, RouterOutput, ToolCallSpec, ToolResult, ValidationIssue


def classify_execution_repair_action(
    errors: list[str],
    tool_results: list[ToolResult],
    plan: QueryPlan,
    router_output: RouterOutput,
    *,
    config: ResumeQAConfig | None = None,
    validation_issues: list[ValidationIssue] | None = None,
) -> dict[str, str]:
    """根据结构化校验问题执行classify执行修复action修复，并保持原有安全边界和产物依赖。"""
    cfg = config or load_config()
    issues = validation_issues or build_validation_issues(errors, "execution")
    shared = validation_action(cfg, issues, "execution")
    if shared["action"] == "clarify":
        return shared
    codes = {issue.code for issue in issues}
    if "empty_retrieval" in codes:
        fallback_sources = {
            str(name)
            for name, raw in dict(cfg.tool_policy.get("tools", {}) or {}).items()
            if dict(raw or {}).get("fallback_tool")
        }
        if _allows_query_fallback(plan, router_output) and any(_has_tool_call(plan, name) for name in fallback_sources):
            return {"action": "query_fallback", "category": "empty_retrieval", "reason": "candidate_retrieval_empty"}
        return {"action": "fail", "category": "empty_retrieval", "reason": "structured_empty_result_should_not_recall"}
    return shared


def repair_execution_plan(
    question: str,
    plan: QueryPlan,
    router_output: RouterOutput,
    errors: list[str],
    tool_results: list[ToolResult],
    *,
    session_context: dict | None = None,
    config: ResumeQAConfig | None = None,
    validation_issues: list[ValidationIssue] | None = None,
) -> tuple[QueryPlan, dict[str, str]]:
    """根据结构化校验问题执行修复执行计划修复，并保持原有安全边界和产物依赖。"""
    decision = classify_execution_repair_action(
        errors,
        tool_results,
        plan,
        router_output,
        config=config,
        validation_issues=validation_issues,
    )
    if decision["action"] in {"clarify", "fail"}:
        return plan, decision
    if decision["action"] == "query_fallback":
        repaired = _fallback_recall_plan(question, plan, router_output, action=decision["action"], config=config or load_config())
    else:
        return plan, {"action": "fail", "category": decision["category"], "reason": decision["reason"]}
    return with_artifact_bindings(with_structured_refs(repaired), router_output, config=config), decision


def _allows_query_fallback(plan: QueryPlan, router_output: RouterOutput) -> bool:
    """根据结构化校验问题执行allows查询兜底修复，并保持原有安全边界和产物依赖。"""
    intents = [task.intent for task in plan.sub_tasks] if plan.intent == "compound" else [plan.intent]
    return any(scenario_for_intent(router_output, intent) == "open_recall" for intent in intents)


def _fallback_recall_plan(question: str, plan: QueryPlan, router_output: RouterOutput, *, action: str, config: ResumeQAConfig) -> QueryPlan:
    """根据结构化校验问题执行兜底召回计划修复，并保持原有安全边界和产物依赖。"""
    query = cleaned_retrieval_query(router_output.normalized_conditions, fallback=question) or question
    if plan.intent == "compound":
        return _fallback_compound_plan(plan, query, action=action, config=config)
    next_calls, replaced = _fallback_calls(plan.tool_calls, query, action=action, config=config)
    if not replaced and action == "query_fallback":
        fallback_tool = _default_fallback_tool(config)
        next_calls.insert(0, ToolCallSpec(name=fallback_tool, arguments={"query": query}, output_key=config.default_output_key(fallback_tool)))
    return plan.model_copy(update={"tool_calls": next_calls})


def _fallback_compound_plan(plan: QueryPlan, query: str, *, action: str, config: ResumeQAConfig) -> QueryPlan:
    """根据结构化校验问题执行兜底compound计划修复，并保持原有安全边界和产物依赖。"""
    sub_tasks = []
    for sub_task in plan.sub_tasks:
        calls, _replaced = _fallback_calls(sub_task.tool_calls, query, action=action, config=config)
        sub_tasks.append(sub_task.model_copy(update={"tool_calls": calls}))
    return plan.model_copy(update={"sub_tasks": sub_tasks})


def _fallback_calls(calls: list[ToolCallSpec], query: str, *, action: str, config: ResumeQAConfig) -> tuple[list[ToolCallSpec], bool]:
    """根据结构化校验问题执行兜底调用修复，并保持原有安全边界和产物依赖。"""
    next_calls: list[ToolCallSpec] = []
    replaced = False
    for call in calls:
        fallback_tool = str(dict(dict(config.tool_policy.get("tools", {}) or {}).get(call.name, {}) or {}).get("fallback_tool") or "")
        if action == "query_fallback" and fallback_tool:
            args = {"query": query}
            candidate_ids = call.arguments.get("candidate_ids")
            if candidate_ids:
                args["candidate_ids"] = candidate_ids
            next_calls.append(ToolCallSpec(
                name=fallback_tool,
                arguments=args,
                output_key=call.output_key,
                depends_on=call.depends_on,
                purpose=call.purpose,
                expected_output=call.expected_output,
            ))
            replaced = True
            continue
        next_calls.append(call)
    return next_calls, replaced


def _default_fallback_tool(config: ResumeQAConfig) -> str:
    """根据结构化校验问题执行default兜底工具修复，并保持原有安全边界和产物依赖。"""
    for raw in dict(config.tool_policy.get("tools", {}) or {}).values():
        fallback = str(dict(raw or {}).get("fallback_tool") or "")
        if fallback:
            return fallback
    raise ValueError("tool_policy.yaml must configure at least one fallback_tool")


def _iter_plan_calls(plan: QueryPlan) -> list[ToolCallSpec]:
    """根据结构化校验问题执行iter计划调用修复，并保持原有安全边界和产物依赖。"""
    if plan.intent == "compound":
        return [call for task in plan.sub_tasks for call in task.tool_calls]
    return list(plan.tool_calls)


def _has_tool_call(plan: QueryPlan, tool_name: str) -> bool:
    """判断计划是否包含指定工具调用并返回布尔值。"""
    return any(call.name == tool_name for call in _iter_plan_calls(plan))
