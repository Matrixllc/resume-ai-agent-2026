"""Plan compiler entrypoints.

这个文件负责什么：
- 把 SemanticPlan 编译成 executor 可执行的 QueryPlan。
- 按 compiler mode 分流 workflow_template / generic_tool_binding / hybrid_template_binding。
- 在 generic 路径里把 tool hints 过滤、绑定并转成 ToolCallSpec。

应该从哪个函数读起：
- compile_semantic_plan_with_meta
- compile_with_hybrid_template_binding
- compile_with_generic_tool_binding

不会负责什么：
- 不重新理解用户问题。
- 不调用 tools。
- 不修复非法计划，非法计划交给 plan_validator / plan_repair。
"""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.inspection.plan_artifacts import with_artifact_bindings
from resume_query_ai_qa.core.rules.execution_policy_rules import resolve_execution_decision
from resume_query_ai_qa.core.rules.semantic_plan import normalize_semantic_plan
from resume_query_ai_qa.core.schemas import ExecutionDecision, QueryPlan, RouterOutput, SemanticPlan, SubTaskPlan, ToolHint
from resume_query_ai_qa.tools import get_tool_registry

from resume_query_ai_qa.core.rules.plan_building import (
    bind_compound_consumers_to_canonical_source,
    bind_current_calls_to_source,
    candidate_source_conflict,
    dedupe_tool_hints,
    generic_call_for_tool,
    hybrid_source_call,
    infer_execution_scenario,
    is_candidate_source_tool,
    ranking_output_limit,
    rejected_hint,
    scored_tool_hints,
    should_use_hybrid_recall,
    source_signature,
    tool_query,
    preference_recall_query,
    replace_ref_root,
    with_structured_refs,
)
from .templates import compile_with_workflow_templates, template_reject_reason, template_rejected_hints, template_tool_names
from .trace import compiler_trace_meta


def compile_semantic_plan_with_meta(
    question: str,
    router_output: RouterOutput,
    semantic_plan: SemanticPlan,
    *,
    session_context: dict | None = None,
    config: ResumeQAConfig | None = None,
    decision: ExecutionDecision | None = None,
) -> tuple[QueryPlan, dict[str, Any]]:
    """编译语义计划并返回查询计划及编译元信息。

    这是 plan_compiler 的主入口。它先把 SemanticPlan 重新 normalize，
    再根据 compiler flags 选择 template、generic 或 hybrid 路径。
    """
    cfg = config or load_config()
    flags = cfg.compiler_flags()
    resolved = decision or resolve_execution_decision(question, router_output, cfg)
    normalized = normalize_semantic_plan(router_output, semantic_plan, resolved, cfg)
    mode = str(flags["mode"])
    if mode == "generic_tool_binding":
        return compile_with_generic_tool_binding(question, router_output, normalized, session_context=session_context, config=cfg)
    if mode == "hybrid_template_binding":
        return compile_with_hybrid_template_binding(question, router_output, normalized, session_context=session_context, config=cfg, decision=resolved)
    plan = compile_with_workflow_templates(question, router_output, normalized, session_context=session_context, config=cfg, workflow_name=resolved.workflow_name)
    return plan, compiler_trace_meta(normalized, plan, mode="workflow_template", flags=flags, router_output=router_output, strategy="workflow_template", workflow_name=resolved.workflow_name)


def compile_semantic_plan(
    question: str,
    router_output: RouterOutput,
    semantic_plan: SemanticPlan,
    *,
    session_context: dict | None = None,
    config: ResumeQAConfig | None = None,
    decision: ExecutionDecision | None = None,
) -> QueryPlan:
    """编译语义计划并只返回 QueryPlan。

    调用方不需要 compiler meta 时使用这个简化入口。
    """
    plan, _meta = compile_semantic_plan_with_meta(question, router_output, semantic_plan, session_context=session_context, config=config, decision=decision)
    return plan


def refresh_artifact_bindings(
    plan: QueryPlan,
    router_output: RouterOutput | None,
    config: ResumeQAConfig | None = None,
) -> QueryPlan:
    """刷新计划的结构化引用和产物绑定。

    主要供 repair 或外部调用在修改 QueryPlan 后重新生成 artifact_bindings。
    """
    return with_artifact_bindings(with_structured_refs(plan), router_output, config=config)


def compile_with_hybrid_template_binding(
    question: str,
    router_output: RouterOutput,
    semantic_plan: SemanticPlan,
    *,
    session_context: dict | None,
    config: ResumeQAConfig,
    decision: ExecutionDecision,
) -> tuple[QueryPlan, dict[str, Any]]:
    """在 hybrid mode 下选择 template 或 generic 编译路径。

    ExecutionDecision 命中 workflow_template 时走稳定模板；否则回落到
    generic tool binding。
    """
    if decision.compiler == "workflow_template":
        plan = compile_with_workflow_templates(question, router_output, semantic_plan, session_context=session_context, config=config, workflow_name=decision.workflow_name)
        meta = compiler_trace_meta(semantic_plan, plan, mode="hybrid_template_binding", flags=config.compiler_flags(), router_output=router_output, strategy="workflow_template", workflow_name=decision.workflow_name)
        rejected = template_rejected_hints(semantic_plan, config)
        if rejected:
            meta["rejected_tool_hints"] = rejected
        return plan, meta
    plan, meta = compile_with_generic_tool_binding(question, router_output, semantic_plan, session_context=session_context, config=config)
    meta["strategy"] = "generic"
    debug = dict(meta.get("debug") or {})
    debug["compiler_config_mode"] = "hybrid_template_binding"
    debug["compiler_strategy"] = "generic_tool_binding"
    meta["debug"] = debug
    meta["workflow_name"] = ""
    return plan, meta


def compile_with_generic_tool_binding(
    question: str,
    router_output: RouterOutput,
    semantic_plan: SemanticPlan,
    *,
    session_context: dict | None,
    config: ResumeQAConfig,
) -> tuple[QueryPlan, dict[str, Any]]:
    """把 generic 路径的 tool hints 编译成 QueryPlan。

    这里会检查 registry、allowed/forbidden tools、candidate source contract，
    只有通过检查的 hint 才会变成 ToolCallSpec。
    """
    registry = get_tool_registry()
    sub_tasks: list[SubTaskPlan] = []
    source_registry: dict[str, Any] = {}
    candidate_source = None
    rejected: list[dict[str, Any]] = []
    for step in semantic_plan.steps:
        scenario = step.scenario or infer_execution_scenario(question, router_output, step.intent)
        allowed = set(config.allowed_tools_for_intent(step.intent, scenario))
        forbidden = set(config.forbidden_tools_for_scenario(step.intent, scenario))
        required = set(template_tool_names(step.intent, config, scenario))
        calls = []
        for hint in tool_hints_for_generic_step(step, config):
            if hint.name in forbidden:
                rejected.append(rejected_hint(hint, "tool_forbidden_by_scenario_policy", intent=step.intent))
                continue
            if hint.name not in registry or (allowed and hint.name not in allowed):
                rejected.append(rejected_hint(hint, "tool_not_allowed", intent=step.intent))
                continue
            if step.intent == "candidate_filter" and not is_candidate_source_tool(hint.name):
                rejected.append(rejected_hint(hint, "candidate_filter_requires_candidate_source", intent=step.intent))
                continue
            if required and hint.source != "compiler_required" and hint.name not in required:
                if is_candidate_source_tool(hint.name):
                    source = generic_call_for_tool(hint.name, step.intent, question, router_output, session_context, calls, config=config)
                    if source is not None:
                        conflict = candidate_source_conflict(source, candidate_source, router_output)
                        if conflict:
                            rejected.append({**rejected_hint(hint, str(conflict["reason"]), intent=step.intent), **conflict})
                            continue
                rejected.append(rejected_hint(hint, template_reject_reason(step.intent, hint.name), intent=step.intent))
                continue
            call = generic_call_for_tool(hint.name, step.intent, question, router_output, session_context, calls, config=config)
            if call is None:
                continue
            if candidate_source is not None and call.name == "search_candidate_evidence":
                call = replace_ref_root(call, "resolved_candidate", candidate_source.output_key or "candidate_pool")
            if is_candidate_source_tool(call.name):
                conflict = candidate_source_conflict(call, candidate_source, router_output)
                if conflict:
                    rejected.append({**rejected_hint(hint, str(conflict["reason"]), intent=step.intent), **conflict})
                    calls = bind_current_calls_to_source(calls, candidate_source.output_key if candidate_source else "candidate_pool")
                    continue
                signature = source_signature(call)
                if signature in source_registry:
                    calls = bind_current_calls_to_source(calls, source_registry[signature].output_key or "candidate_pool")
                    continue
                source_registry[signature] = call
                candidate_source = candidate_source or call
            calls.append(call)
        if step.intent == "candidate_filter" and scenario == "open_recall" and should_use_hybrid_recall(question, router_output):
            calls = [call for call in calls if not is_candidate_source_tool(call.name)]
            query = preference_recall_query(question, router_output) or tool_query(question, step.intent, router_output)
            if query:
                calls.insert(0, hybrid_source_call(query, router_output, session_context, config=config))
        sub_tasks.append(SubTaskPlan(intent=step.intent, tool_calls=calls, requires_jd_criteria=step.requires_jd, requires_evidence=step.requires_evidence))
    if semantic_plan.intent == "compound":
        plan = QueryPlan(intent="compound", is_compound=True, sub_tasks=sub_tasks)
    else:
        first = sub_tasks[0] if sub_tasks else SubTaskPlan(intent=router_output.intent)
        plan = QueryPlan(intent=first.intent, tool_calls=first.tool_calls)
    plan = bind_compound_consumers_to_canonical_source(plan, router_output)
    plan = with_structured_refs(plan.model_copy(update={"notes": [*plan.notes, "compiled_with_generic_tool_binding"]}))
    plan = with_artifact_bindings(plan, router_output, rejected_producers=rejected, config=config)
    plan = _with_ranking_output_limit(plan, question)
    meta = compiler_trace_meta(semantic_plan, plan, mode="generic_tool_binding", flags=config.compiler_flags(), router_output=router_output, strategy="generic_tool_binding")
    if rejected:
        meta["rejected_tool_hints"] = rejected
    return plan, meta


def _with_ranking_output_limit(plan: QueryPlan, question: str) -> QueryPlan:
    """把当前问题里的 TopK 排序展示限制写入 QueryPlan constraints。"""
    limit = ranking_output_limit(question)
    if not limit:
        return plan
    return plan.model_copy(update={"constraints": plan.constraints.model_copy(update={"ranking_output_limit": limit})})


def tool_hints_for_generic_step(step, config: ResumeQAConfig) -> list[ToolHint]:
    """合并单个 SemanticStep 的工具建议。

    来源包括 SemanticStep 自带 hints、tool_policy.yaml 的 preferred hints，
    以及 workflow template 要求的 compiler_required tools。
    """
    scenario = step.scenario or ""
    policy = [
        ToolHint(name=str(item["name"]), confidence=float(item.get("confidence", 0.75) or 0.75), source="policy", scenario=scenario)
        for item in config.preferred_tool_hints_for_scenario(step.intent, scenario)
        if str(item.get("name", "") or "").strip()
    ]
    forbidden = set(config.forbidden_tools_for_scenario(step.intent, scenario))
    hints = [hint for hint in dedupe_tool_hints([*scored_tool_hints(step), *policy]) if hint.name not in forbidden]
    allowed = set(config.allowed_tools_for_intent(step.intent, scenario))
    required = []
    for name in template_tool_names(step.intent, config, scenario):
        if (not allowed or name in allowed) and name not in forbidden:
            required.append(ToolHint(name=name, confidence=1.0, source="compiler_required", scenario=scenario, reason="compiler required by workflow template"))
    return dedupe_tool_hints([*required, *hints])
