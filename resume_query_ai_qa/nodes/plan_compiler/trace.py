"""Compiler trace helpers.

这个文件负责什么：
- 从 QueryPlan 和 SemanticPlan 生成 compiler meta/debug。
- 给日志、观测和问题排查提供可读摘要。

不会负责什么：
- 不修改 QueryPlan。
- 不参与工具选择或参数绑定。
"""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.rules.plan_building import plan_calls
from resume_query_ai_qa.core.schemas import QueryPlan, RouterOutput, SemanticPlan


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
    """生成 compiler trace meta。

    meta 面向正常日志；debug 保留完整 compiled_plan、artifact_bindings 和
    tool hint 分数，方便定位 compiler 选择路径。
    """
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
    """提取 filter_candidates 的结构化筛选参数用于 trace。"""
    return [call.arguments for call in plan_calls(plan) if call.name == "filter_candidates"]


def artifacts_summary(plan: QueryPlan) -> list[dict[str, Any]]:
    """把 ArtifactBinding 压缩成面向日志的产物摘要。"""
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
    """把内部 artifact_type 转成更适合展示的中文标签。"""
    return {
        "candidate_collection": "候选人集合",
        "candidate_count": "候选人数",
        "candidate_profile": "候选人画像",
        "evidence_collection": "证据集合",
        "scored_candidates": "候选人评分",
        "ranked_candidates": "候选人排序",
    }.get(value, value)


def _scope_label(scope: dict[str, Any]) -> str:
    """把 artifact scope dict 转成简短展示文本。"""
    if not scope:
        return ""
    if scope.get("domains_any"):
        return "、".join(str(item) for item in list(scope.get("domains_any") or []) if str(item))
    if scope.get("domain"):
        return str(scope.get("domain") or "")
    return ", ".join(f"{key}={value}" for key, value in scope.items())
