"""Sub-task orchestration and ToolCallSpec normalization."""

from __future__ import annotations

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.rules.context_resolver import candidate_ids_for_context
from resume_query_ai_qa.core.rules.execution_policy_rules import scenario_for_intent
from resume_query_ai_qa.core.schemas import RouterOutput, SubTaskPlan, ToolCallSpec

from .builders import generic_call_for_tool, hybrid_source_call, ranking_criteria_tool
from .query_args import filter_args, preference_filter_args, preference_recall_query, ranking_filter_args, tool_query
from .source_policy import dedupe_repeated_calls


def sub_task_for_intent(
    intent: str,
    question: str,
    *,
    router_output: RouterOutput | None = None,
    session_context: dict | None = None,
    config: ResumeQAConfig | None = None,
) -> SubTaskPlan:
    """根据意图生成子任务并返回。"""
    output = router_output or RouterOutput(intent=intent)
    cfg = config or load_config()
    scenario = scenario_for_intent(output, intent)
    names = tool_sequence_for_intent(cfg, intent, scenario, output)
    defaults = cfg.semantic_defaults_for_intent(intent, scenario)
    calls: list[ToolCallSpec] = []
    for name in names:
        call = generic_call_for_tool(name, intent, question, output, session_context, calls, config=cfg)
        if call is not None:
            calls.append(call)
    return normalize_sub_task(
        SubTaskPlan(
            intent=intent,  # type: ignore[arg-type]
            tool_calls=calls,
            requires_jd_criteria=defaults["requires_jd"],
            requires_evidence=defaults["requires_evidence"],
        ),
        question,
        router_output=output,
        session_context=session_context,
        config=cfg,
    )


def tool_sequence_for_intent(
    config: ResumeQAConfig,
    intent: str,
    scenario: str = "",
    router_output: RouterOutput | None = None,
) -> list[str]:
    """根据意图生成工具sequence并返回。"""
    names = [name for name in config.preferred_tools_for_scenario(intent, scenario) if name]
    if router_output is not None and intent in {"candidate_ranking", "jd_scoring"}:
        criteria_tool = ranking_criteria_tool(router_output, config)
        names = [criteria_tool if config.tool_binding_kind(name) == "criteria_source" else name for name in names]
    return list(dict.fromkeys(names))


def normalize_sub_task(
    sub_task: SubTaskPlan,
    question: str,
    *,
    router_output: RouterOutput | None,
    session_context: dict | None,
    config: ResumeQAConfig | None = None,
) -> SubTaskPlan:
    """标准化子任务并返回。"""
    calls = [normalize_call(call, question, sub_task.intent, router_output, session_context, config=config) for call in sub_task.tool_calls]
    return sub_task.model_copy(update={"tool_calls": dedupe_repeated_calls(calls)})


def normalize_call(
    call: ToolCallSpec,
    question: str,
    intent: str,
    router_output: RouterOutput | None,
    session_context: dict | None,
    *,
    config: ResumeQAConfig | None = None,
) -> ToolCallSpec:
    """标准化调用并返回。"""
    if router_output is None:
        return call
    cfg = config or load_config()
    kind = cfg.tool_binding_kind(call.name)
    if kind == "structured_filter":
        context_ids = candidate_ids_for_context(router_output.context_policy, session_context)
        if intent in {"candidate_ranking", "jd_scoring"} and context_ids:
            return call.model_copy(update={"arguments": {"candidate_ids": context_ids}})
        if intent in {"candidate_ranking", "jd_scoring"}:
            args = ranking_filter_args(question, router_output, session_context)
            if not args:
                return call.model_copy(
                    update={
                        "name": cfg.first_tool_with_binding_kind("list_candidates"),
                        "arguments": {},
                    }
                )
            return call.model_copy(update={"arguments": args})
        args = filter_args(question, router_output, session_context)
        if not args:
            args = preference_filter_args(question, router_output, session_context)
        return call.model_copy(update={"arguments": args})
    if kind == "semantic_search":
        query = tool_query(question, intent, router_output) or preference_recall_query(question, router_output)
        return hybrid_source_call(
            query,
            router_output,
            session_context,
            output_key=call.output_key or "candidate_pool",
            config=cfg,
        )
    return call
