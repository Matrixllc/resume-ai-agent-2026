"""答案生成公共 facade，保持 aggregator/rewrite/fallback 的旧入口兼容。"""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.schemas import AggregatedAnswer, ExecutionDecision, QueryPlan, RouterOutput, ToolResult

from .fallback import render_fallback_answer
from .llm_flow import LLMFlowResult, run_fill_flow, run_rewrite_flow
from .orchestration import (
    AnswerInputs,
    answer_decision_meta,
    answer_trace_meta,
    dedupe_warnings,
    prepare_answer_inputs,
    render_grounded_answer,
)


def aggregate_answer_llm(
    question: str,
    plan: QueryPlan,
    tool_results: list[ToolResult],
    config: ResumeQAConfig | None = None,
) -> AggregatedAnswer:
    """对外 LLM 聚合入口；节点只调用这里，不感知内部 fill/fallback 分支。"""
    answer, _meta = aggregate_answer_with_meta(question, plan, tool_results, config=config, use_llm=True)
    return answer


def rewrite_answer_llm(
    question: str,
    plan: QueryPlan,
    tool_results: list[ToolResult],
    previous_answer: AggregatedAnswer,
    answer_errors: list[str],
    config: ResumeQAConfig | None = None,
) -> AggregatedAnswer:
    """对外 LLM rewrite 入口；失败时仍按规则 fallback 返回可校验答案。"""
    answer, _meta = rewrite_answer_with_meta(question, plan, tool_results, previous_answer, answer_errors, config=config, use_llm=True)
    return answer


def aggregate_answer_with_meta(
    question: str,
    plan: QueryPlan,
    tool_results: list[ToolResult],
    config: ResumeQAConfig | None = None,
    *,
    use_llm: bool = True,
    node: str = "aggregator",
    execution_decision: ExecutionDecision | None = None,
    router_output: RouterOutput | None = None,
) -> tuple[AggregatedAnswer, dict[str, Any]]:
    """聚合答案并返回 trace meta；规则 grounding 是事实源，LLM 只做受控填充。"""
    cfg = config or load_config()
    inputs = prepare_answer_inputs(
        question,
        plan,
        tool_results,
        cfg,
        execution_decision=execution_decision,
        router_output=router_output,
    )
    grounded = render_grounded_answer(inputs)
    result = run_fill_flow(inputs, grounded, cfg, use_llm=use_llm)
    meta = _meta_from_flow(node, result, inputs, cfg)
    return result.answer or grounded, meta


def generate_rewrite_candidate_with_meta(
    question: str,
    plan: QueryPlan,
    tool_results: list[ToolResult],
    previous_answer: AggregatedAnswer,
    answer_errors: list[str],
    config: ResumeQAConfig | None = None,
    *,
    use_llm: bool = True,
    node: str = "answer_rewrite",
    execution_decision: ExecutionDecision | None = None,
    router_output: RouterOutput | None = None,
) -> tuple[AggregatedAnswer | None, dict[str, Any]]:
    """生成 rewrite 候选答案；候选为空时调用方必须回落规则聚合。"""
    cfg = config or load_config()
    inputs = prepare_answer_inputs(
        question,
        plan,
        tool_results,
        cfg,
        execution_decision=execution_decision,
        router_output=router_output,
    )
    grounded = render_grounded_answer(inputs)
    result = run_rewrite_flow(inputs, grounded, previous_answer, answer_errors, cfg, use_llm=use_llm)
    meta = _meta_from_flow(node, result, inputs, cfg)
    return result.answer, meta


def rewrite_answer_with_meta(
    question: str,
    plan: QueryPlan,
    tool_results: list[ToolResult],
    previous_answer: AggregatedAnswer,
    answer_errors: list[str],
    config: ResumeQAConfig | None = None,
    *,
    use_llm: bool = True,
    node: str = "answer_rewrite",
    execution_decision: ExecutionDecision | None = None,
    router_output: RouterOutput | None = None,
) -> tuple[AggregatedAnswer, dict[str, Any]]:
    """执行 rewrite 并在候选不可用时回落规则聚合，保证节点拿到完整答案。"""
    answer, meta = generate_rewrite_candidate_with_meta(
        question,
        plan,
        tool_results,
        previous_answer,
        answer_errors,
        config=config,
        use_llm=use_llm,
        node=node,
        execution_decision=execution_decision,
        router_output=router_output,
    )
    if answer is not None:
        return answer, meta
    fallback = aggregate_answer(question, plan, tool_results, config=config)
    reason = meta.get("fallback_reason") or "rewrite_candidate_unavailable"
    fallback = fallback.model_copy(update={"warnings": dedupe_warnings([*fallback.warnings, f"rewrite_fallback:{reason}"])})
    return fallback, meta


def aggregate_answer(
    question: str,
    plan: QueryPlan,
    tool_results: list[ToolResult],
    config: ResumeQAConfig | None = None,
) -> AggregatedAnswer:
    """纯规则聚合答案；用于 LLM 关闭、rewrite 回落和硬兜底前的稳定路径。"""
    cfg = config or load_config()
    inputs = prepare_answer_inputs(
        question,
        plan,
        tool_results,
        cfg,
        execution_decision=None,
        router_output=None,
    )
    return render_grounded_answer(inputs)


def render_hard_fallback(
    question: str,
    plan: QueryPlan,
    tool_results: list[ToolResult],
    config: ResumeQAConfig | None = None,
    *,
    execution_decision: ExecutionDecision | None = None,
    router_output: RouterOutput | None = None,
) -> AggregatedAnswer:
    """渲染硬兜底答案；只使用确定性 context，不调用 LLM。"""
    cfg = config or load_config()
    inputs = prepare_answer_inputs(
        question,
        plan,
        tool_results,
        cfg,
        execution_decision=execution_decision,
        router_output=router_output,
    )
    return render_fallback_answer(question, inputs.query_frame, inputs.layout_name, inputs.context)


def _meta_from_flow(node: str, result: LLMFlowResult, inputs: AnswerInputs, config: ResumeQAConfig) -> dict[str, Any]:
    """把 LLM flow 结果转成旧 trace 结构，避免调用方感知内部拆分。"""
    meta = answer_decision_meta(node, result.engine, result.fallback_reason, config if result.engine == "llm" or result.fallback_reason else None)
    meta["aggregator_io"] = {"mode": result.mode, "prompt": result.prompt, "response": result.llm_response.model_dump()}
    meta.update(
        answer_trace_meta(
            inputs,
            llm_mode=result.mode,
            fallback_reason=result.fallback_reason,
            drift_rejection_reason=result.drift_reason,
        )
    )
    meta["rule_draft"] = inputs.rule_draft
    return meta
