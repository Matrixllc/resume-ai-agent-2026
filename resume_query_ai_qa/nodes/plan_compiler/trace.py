"""Compiler trace helpers."""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.schemas import QueryPlan, RouterOutput, SemanticPlan

from .binding import plan_calls


def compiler_trace_meta(
    semantic_plan: SemanticPlan,
    plan: QueryPlan,
    *,
    mode: str,
    flags: dict[str, Any],
    router_output: RouterOutput | None = None,
    strategy: str = "",
    workflow_name: str = "",
) -> dict[str, Any]:
    """将语义计划中的编译追踪元信息编译为受配置约束的 QueryPlan 内容，不执行工具。"""
    calls = plan_calls(plan)
    strategy_name = "template" if (strategy or mode) in {"workflow_template", "hybrid_template_binding"} and strategy != "generic_tool_binding" else "generic"
    execution_scenarios = {step.intent: step.scenario for step in semantic_plan.steps if step.scenario}
    llm_tool_hints = [name for step in semantic_plan.steps for name in step.tool_hints]
    llm_tool_hint_scores = [hint.model_dump() for step in semantic_plan.steps for hint in step.tool_hint_scores]
    artifact_bindings = [binding.model_dump() for binding in plan.artifact_bindings]
    compiled_plan = plan.model_dump()
    return {
        "strategy": strategy_name,
        "workflow_name": workflow_name,
        "compiled_tools": [call.name for call in calls],
        "filters": structured_filter_trace(plan),
        "artifacts_summary": artifacts_summary(plan),
        "debug": {
            "compiler_mode": mode,
            "compiler_config_mode": mode,
            "compiler_source": strategy_name,
            "compiler_strategy": strategy or mode,
            "compiler_flags": flags,
            "execution_scenarios": execution_scenarios,
            "llm_tool_hints": llm_tool_hints,
            "llm_tool_hint_scores": llm_tool_hint_scores,
            "artifact_bindings": artifact_bindings,
            "compiled_plan": compiled_plan,
        },
    }


def structured_filter_trace(plan: QueryPlan) -> list[dict[str, Any]]:
    """将语义计划中的structured筛选追踪编译为受配置约束的 QueryPlan 内容，不执行工具。"""
    return [call.arguments for call in plan_calls(plan) if call.name == "filter_candidates"]


def artifacts_summary(plan: QueryPlan) -> list[dict[str, Any]]:
    """将语义计划中的产物摘要编译为受配置约束的 QueryPlan 内容，不执行工具。"""
    output: list[dict[str, Any]] = []
    for binding in plan.artifact_bindings:
        if binding.artifact_type == "candidate_collection" and binding.accepted_producer == "resolve_candidate_reference":
            continue
        item: dict[str, Any] = {
            "name": binding.artifact_id,
            "type": _artifact_type_label(binding.artifact_type),
            "producer": binding.accepted_producer,
        }
        scope = _scope_label(binding.accepted_scope or binding.required_scope)
        if scope:
            item["scope"] = scope
        if binding.consumers:
            item["used_by"] = binding.consumers
        if binding.source_artifact_id:
            item["source"] = binding.source_artifact_id
        output.append(item)
    return output


def _artifact_type_label(value: str) -> str:
    """将语义计划中的产物typelabel编译为受配置约束的 QueryPlan 内容，不执行工具。"""
    return {
        "candidate_collection": "候选人集合",
        "candidate_count": "候选人数",
        "candidate_profile": "候选人画像",
        "evidence_collection": "证据集合",
        "scored_candidates": "候选人评分",
        "ranked_candidates": "候选人排序",
    }.get(value, value)


def _scope_label(scope: dict[str, Any]) -> str:
    """将语义计划中的范围label编译为受配置约束的 QueryPlan 内容，不执行工具。"""
    if not scope:
        return ""
    if scope.get("domains_any"):
        return "、".join(str(item) for item in list(scope.get("domains_any") or []) if str(item))
    if scope.get("domain"):
        return str(scope.get("domain") or "")
    return ", ".join(f"{key}={value}" for key, value in scope.items())
