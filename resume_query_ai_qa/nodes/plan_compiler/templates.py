"""Workflow-template compilation."""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.schemas import QueryPlan, RouterOutput, SemanticPlan, SubTaskPlan, ToolCallSpec, ToolHint

from .artifacts import with_artifact_bindings
from .binding import (
    bind_compound_consumers_to_canonical_source,
    filter_args,
    generic_call_for_tool,
    normalize_sub_task,
    ranking_output_limit,
    ranking_criteria_tool,
    ranking_has_named_scope,
    reuse_candidate_source_for_count_list,
    scored_tool_hints,
    structured_arg_ref,
    sub_task_for_intent,
    tool_query,
    with_structured_refs,
)


def compile_with_workflow_templates(
    question: str,
    router_output: RouterOutput,
    semantic_plan: SemanticPlan,
    *,
    session_context: dict | None,
    config: ResumeQAConfig,
    workflow_name: str = "",
) -> QueryPlan:
    """将语义计划中的compilewith工作流templates编译为受配置约束的 QueryPlan 内容，不执行工具。"""
    scoped = scoped_count_rank_evidence_plan(
        question,
        router_output,
        semantic_plan,
        session_context=session_context,
        config=config,
        workflow_name=workflow_name,
    )
    if scoped is not None:
        return with_artifact_bindings(with_structured_refs(scoped), router_output, config=config)
    if semantic_plan.intent == "compound":
        tasks = [
            sub_task_from_workflow_template(step.intent, question, router_output=router_output, session_context=session_context, config=config)
            or sub_task_for_intent(step.intent, question, router_output=router_output, session_context=session_context, config=config)
            for step in semantic_plan.steps
        ]
        plan = QueryPlan(intent="compound", is_compound=True, sub_tasks=reuse_candidate_source_for_count_list(tasks))
    else:
        intent = semantic_plan.steps[0].intent if semantic_plan.steps else router_output.intent
        task = (
            sub_task_from_workflow_template(intent, question, router_output=router_output, session_context=session_context, config=config)
            or sub_task_for_intent(intent, question, router_output=router_output, session_context=session_context, config=config)
        )
        plan = QueryPlan(intent=intent, tool_calls=task.tool_calls)
    plan = _with_ranking_output_limit(plan, question)
    plan = bind_compound_consumers_to_canonical_source(plan.model_copy(update={"notes": [*plan.notes, "compiled_from_semantic_plan"]}), router_output)
    return with_artifact_bindings(with_structured_refs(plan), router_output, config=config)


def scoped_count_rank_evidence_plan(
    question: str,
    router_output: RouterOutput,
    semantic_plan: SemanticPlan,
    *,
    session_context: dict | None,
    config: ResumeQAConfig,
    workflow_name: str = "",
) -> QueryPlan | None:
    """构建限定范围的计数、排序和证据计划并返回。"""
    if workflow_name and workflow_name != "scoped_count_rank_evidence":
        return None
    pattern = dict((config.compiler_templates.get("workflows", {}) or {}).get("scoped_count_rank_evidence", {}) or {})
    if not pattern or not looks_like_scoped_count_rank_evidence(router_output, semantic_plan, pattern):
        return None
    bindings: dict[str, Any] = {
        "filter_args": filter_args(question, router_output, session_context),
        "ranking_criteria_tool": ranking_criteria_tool(router_output, config),
        "retrieval_query": tool_query(question, "candidate_ranking", router_output),
        "workflow_evidence_max_candidates": int(dict(pattern.get("evidence", {}) or {}).get("max_candidates", 3) or 3),
    }
    tasks = [_sub_task_from_declarative_spec(raw, bindings) for raw in list(pattern.get("sub_tasks", []) or [])]
    if not tasks:
        return None
    return _with_ranking_output_limit(QueryPlan(
        intent="compound",
        is_compound=True,
        sub_tasks=tasks,
        notes=[str(item) for item in list(pattern.get("notes", []) or [])],
    ), question)


def _with_ranking_output_limit(plan: QueryPlan, question: str) -> QueryPlan:
    """Attach current-turn TopK display limits to plan constraints."""
    limit = ranking_output_limit(question)
    if not limit:
        return plan
    return plan.model_copy(update={"constraints": plan.constraints.model_copy(update={"ranking_output_limit": limit})})


def _sub_task_from_declarative_spec(raw: Any, bindings: dict[str, Any]) -> SubTaskPlan:
    """将语义计划中的subtaskfromdeclarativespec编译为受配置约束的 QueryPlan 内容，不执行工具。"""
    spec = dict(raw or {})
    calls: list[ToolCallSpec] = []
    for raw_call in list(spec.get("tool_calls", []) or []):
        call = dict(raw_call or {})
        calls.append(
            ToolCallSpec(
                name=str(_resolve_binding(call.get("tool"), bindings)),
                arguments=dict(_resolve_binding(call.get("arguments", {}), bindings) or {}),
                depends_on=[str(item) for item in list(call.get("depends_on", []) or [])],
                output_key=str(call.get("output_key") or ""),
            )
        )
    return SubTaskPlan(
        intent=str(spec.get("intent")),  # type: ignore[arg-type]
        requires_jd_criteria=bool(spec.get("requires_jd_criteria", False)),
        requires_evidence=bool(spec.get("requires_evidence", False)),
        tool_calls=calls,
    )


def _resolve_binding(value: Any, bindings: dict[str, Any]) -> Any:
    """解析模板参数绑定并返回绑定值。"""
    if isinstance(value, dict):
        if set(value) == {"$binding"}:
            return bindings.get(str(value["$binding"]))
        return {key: _resolve_binding(item, bindings) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_binding(item, bindings) for item in value]
    return value


def looks_like_scoped_count_rank_evidence(router_output: RouterOutput, semantic_plan: SemanticPlan, pattern: dict[str, Any]) -> bool:
    """将语义计划中的lookslikescoped计数排序证据编译为受配置约束的 QueryPlan 内容，不执行工具。"""
    required = set(dict(pattern.get("match", {}) or {}).get("required_sub_intents", []) or [])
    return semantic_plan.intent == "compound" and required <= {step.intent for step in semantic_plan.steps}


def template_tool_names(intent: str, config: ResumeQAConfig, scenario: str = "") -> list[str]:
    """将语义计划中的模板工具姓名编译为受配置约束的 QueryPlan 内容，不执行工具。"""
    template = dict((config.compiler_templates.get("workflows", {}) or {}).get(intent, {}) or {})
    if scenario:
        scenarios = {str(item) for item in list(dict(template.get("match", {}) or {}).get("scenarios", []) or []) if str(item).strip()}
        if scenarios and scenario not in scenarios:
            return []
    return [str((item or {}).get("tool", "") if isinstance(item, dict) else item) for item in template.get("tool_calls", []) or []]


def template_rejected_hints(semantic_plan: SemanticPlan, config: ResumeQAConfig) -> list[dict[str, Any]]:
    """将语义计划中的模板rejectedhints编译为受配置约束的 QueryPlan 内容，不执行工具。"""
    rejected: list[dict[str, Any]] = []
    for step in semantic_plan.steps:
        allowed = set(template_tool_names(step.intent, config))
        for hint in scored_tool_hints(step):
            if hint.name not in allowed:
                rejected.append({"tool": hint.name, "confidence": hint.confidence, "source": hint.source, "intent": step.intent, "reason": template_reject_reason(step.intent, hint.name)})
    return rejected


def template_reject_reason(intent: str, tool_name: str) -> str:
    """将语义计划中的模板reject原因编译为受配置约束的 QueryPlan 内容，不执行工具。"""
    return f"tool_not_in_workflow_template:{intent}"


def sub_task_from_workflow_template(
    intent: str,
    question: str,
    *,
    router_output: RouterOutput,
    session_context: dict | None,
    config: ResumeQAConfig,
) -> SubTaskPlan | None:
    """将语义计划中的subtaskfrom工作流模板编译为受配置约束的 QueryPlan 内容，不执行工具。"""
    if intent == "candidate_ranking" and ranking_has_named_scope(router_output):
        return None
    template = dict((config.compiler_templates.get("workflows", {}) or {}).get(intent, {}) or {})
    specs = template.get("tool_calls") or []
    if not isinstance(specs, list) or not specs:
        return None
    calls: list[ToolCallSpec] = []
    for spec in specs:
        name = str((spec or {}).get("tool", "") if isinstance(spec, dict) else spec).strip()
        call = generic_call_for_tool(name, intent, question, router_output, session_context, calls, config=config)
        if call is None:
            continue
        if call.name == name and isinstance(spec, dict) and str(spec.get("default_output_key", "") or "").strip():
            call = call.model_copy(update={"output_key": str(spec["default_output_key"]).strip()})
        calls.append(call)
    defaults = config.semantic_defaults_for_intent(intent, str(router_output.scenario_decisions.get(intent).scenario if router_output.scenario_decisions.get(intent) else ""))
    return normalize_sub_task(
        SubTaskPlan(
            intent=intent,  # type: ignore[arg-type]
            tool_calls=calls,
            requires_jd_criteria=defaults["requires_jd"],
            requires_evidence=defaults["requires_evidence"],
        ),
        question,
        router_output=router_output,
        session_context=session_context,
        config=config,
    )
