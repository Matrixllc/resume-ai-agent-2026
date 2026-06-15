"""Workflow-template compilation.

这个文件负责什么：
- 把 compiler_templates.yaml 中声明的 workflow 编译成 QueryPlan。
- 处理声明式复合 workflow，例如 scoped_count_rank_evidence。
- 解析 workflow YAML 里的 {$binding: ...}。

应该从哪个函数读起：
- compile_with_workflow_templates
- declarative_workflow_plan
- sub_task_from_workflow_template

不会负责什么：
- 不匹配 workflow，匹配由 execution_policy 完成。
- 不执行工具。
"""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.inspection.plan_artifacts import with_artifact_bindings
from resume_query_ai_qa.core.rules.plan_building import (
    bind_compound_consumers_to_canonical_source,
    filter_args,
    generic_call_for_tool,
    normalize_sub_task,
    ranking_output_limit,
    ranking_criteria_tool,
    ranking_has_named_scope,
    reuse_candidate_source_for_count_list,
    scored_tool_hints,
    sub_task_for_intent,
    tool_query,
    with_structured_refs,
)
from resume_query_ai_qa.core.schemas import QueryPlan, RouterOutput, SemanticPlan, SubTaskPlan, ToolCallSpec


def compile_with_workflow_templates(
    question: str,
    router_output: RouterOutput,
    semantic_plan: SemanticPlan,
    *,
    session_context: dict | None,
    config: ResumeQAConfig,
    workflow_name: str = "",
) -> QueryPlan:
    """用 workflow template 编译 QueryPlan。

    先尝试特殊复合 workflow；否则按 SemanticPlan steps 生成普通 template
    子任务，并补 structured refs / artifact bindings。
    """
    scoped = declarative_workflow_plan(
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


def declarative_workflow_plan(
    question: str,
    router_output: RouterOutput,
    semantic_plan: SemanticPlan,
    *,
    session_context: dict | None,
    config: ResumeQAConfig,
    workflow_name: str = "",
) -> QueryPlan | None:
    """Build a declarative compound workflow QueryPlan.

    Workflows with ``sub_tasks`` can be compiled directly from YAML. Bindings
    inject current-turn filter args, retrieval query, and optional ranking tools.
    """
    if not workflow_name or workflow_name == "composed_sub_intent_workflows":
        return None
    pattern = dict((config.compiler_templates.get("workflows", {}) or {}).get(workflow_name, {}) or {})
    if not pattern or not pattern.get("sub_tasks") or not looks_like_declarative_workflow(router_output, semantic_plan, pattern):
        return None
    evidence = dict(pattern.get("evidence", {}) or {})
    bindings: dict[str, Any] = {
        "filter_args": filter_args(question, router_output, session_context),
        "ranking_criteria_tool": ranking_criteria_tool(router_output, config),
        "retrieval_query": tool_query(question, "evidence_question", router_output),
        "workflow_evidence_max_candidates": int(evidence.get("max_candidates", 3) or 3),
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
    """把当前问题里的 TopK 排序展示限制写入 QueryPlan constraints。"""
    limit = ranking_output_limit(question)
    if not limit:
        return plan
    return plan.model_copy(update={"constraints": plan.constraints.model_copy(update={"ranking_output_limit": limit})})


def _sub_task_from_declarative_spec(raw: Any, bindings: dict[str, Any]) -> SubTaskPlan:
    """把 workflow YAML 的 sub_task 声明转成 SubTaskPlan。"""
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
    """递归解析 workflow YAML 里的 {$binding: name}。"""
    if isinstance(value, dict):
        if set(value) == {"$binding"}:
            return bindings.get(str(value["$binding"]))
        return {key: _resolve_binding(item, bindings) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_binding(item, bindings) for item in value]
    return value


def looks_like_declarative_workflow(router_output: RouterOutput, semantic_plan: SemanticPlan, pattern: dict[str, Any]) -> bool:
    """Return true when the SemanticPlan satisfies a declarative workflow."""
    required = set(dict(pattern.get("match", {}) or {}).get("required_sub_intents", []) or [])
    return semantic_plan.intent == "compound" and required <= {step.intent for step in semantic_plan.steps}


def template_tool_names(intent: str, config: ResumeQAConfig, scenario: str = "") -> list[str]:
    """读取某 intent/scenario 对应 workflow template 里的工具名。"""
    template = dict((config.compiler_templates.get("workflows", {}) or {}).get(intent, {}) or {})
    if scenario:
        scenarios = {str(item) for item in list(dict(template.get("match", {}) or {}).get("scenarios", []) or []) if str(item).strip()}
        if scenarios and scenario not in scenarios:
            return []
    return [str((item or {}).get("tool", "") if isinstance(item, dict) else item) for item in template.get("tool_calls", []) or []]


def template_rejected_hints(semantic_plan: SemanticPlan, config: ResumeQAConfig) -> list[dict[str, Any]]:
    """列出 template 路径会拒绝的非模板 tool hints，供 trace/debug 使用。"""
    rejected: list[dict[str, Any]] = []
    for step in semantic_plan.steps:
        allowed = set(template_tool_names(step.intent, config))
        for hint in scored_tool_hints(step):
            if hint.name not in allowed:
                rejected.append({"tool": hint.name, "confidence": hint.confidence, "source": hint.source, "intent": step.intent, "reason": template_reject_reason(step.intent, hint.name)})
    return rejected


def template_reject_reason(intent: str, tool_name: str) -> str:
    """生成 template 路径拒绝某工具 hint 的统一 reason。"""
    return f"tool_not_in_workflow_template:{intent}"


def sub_task_from_workflow_template(
    intent: str,
    question: str,
    *,
    router_output: RouterOutput,
    session_context: dict | None,
    config: ResumeQAConfig,
) -> SubTaskPlan | None:
    """用普通 workflow template 生成单个 SubTaskPlan。

    没有 template 时返回 None，调用方会回落到通用 sub_task_for_intent。
    """
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
