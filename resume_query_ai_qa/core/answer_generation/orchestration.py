"""Deterministic answer preparation and grounding orchestration.

这个文件负责什么：
  准备 LLM/rule 共同使用的 query_frame、layout、context、rule_draft 和 prompt payload。

应该从哪个函数读起：
  prepare_answer_inputs() -> render_grounded_answer() -> grounded_authority()。

不会负责什么：
  不调用 LLM，不调用工具，不改写 ToolResult。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.llm import llm_identity
from resume_query_ai_qa.core.schemas import AggregatedAnswer, ExecutionDecision, QueryPlan, RouterOutput, ToolResult

from .context import build_answer_context
from .draft import build_rule_draft
from .grounding import build_grounded_claims, build_used_evidence_refs
from .layout import infer_answer_layout
from .logging import aggregator_decision_meta
from .prompt_payload import build_prompt_payload
from .renderer import render_rule_answer
from .task import build_query_frame


@dataclass(frozen=True)
class AnswerInputs:
    """答案生成阶段的内部上下文；集中承载 layout/context/prompt，不向外暴露新 API。"""

    query_frame: dict[str, Any]
    layout_name: str
    layout_config: dict[str, Any]
    layout_reason: str
    context: dict[str, Any]
    rule_draft: dict[str, Any]
    payload: dict[str, Any]


def prepare_answer_inputs(
    question: str,
    plan: QueryPlan,
    tool_results: list[ToolResult],
    config: ResumeQAConfig,
    *,
    execution_decision: ExecutionDecision | None,
    router_output: RouterOutput | None,
) -> AnswerInputs:
    """准备答案生成所需的确定性输入；不调用 LLM，也不改写工具结果。"""
    query_frame = build_query_frame(question, plan, tool_results, config, execution_decision=execution_decision, router_output=router_output)
    ok_tools = {result.tool_name for result in tool_results if result.ok}
    layout_name, layout_config, layout_reason = infer_answer_layout(question, query_frame, ok_tools, config)
    context = build_answer_context(query_frame, plan, tool_results)
    rule_draft = build_rule_draft(query_frame, layout_name, layout_config)
    payload = build_prompt_payload(question, query_frame, rule_draft, context, tool_results)
    return AnswerInputs(query_frame, layout_name, layout_config, layout_reason, context, rule_draft, payload)


def render_grounded_answer(inputs: AnswerInputs) -> AggregatedAnswer:
    """每次先生成 grounded rule answer；它既是 fallback，也是 claims/evidence 权威来源。"""
    rule_answer = render_rule_answer(inputs.query_frame, inputs.layout_name, inputs.layout_config, inputs.context)
    return grounded_authority(rule_answer, inputs.context, inputs.layout_name)


def grounded_authority(answer: AggregatedAnswer, context: dict[str, Any], layout_name: str) -> AggregatedAnswer:
    """把 claims、used_evidence_refs、warnings 收口到 ToolResult 派生的 grounded context。"""
    warnings = [f"answer_layout:{layout_name}", "answer_layout_source:answer_layouts.yaml"]
    if "evidence.empty" in (context.get("empty_flags") or {}):
        warnings.append("empty_evidence:search_candidate_evidence_returned_no_refs")
    return AggregatedAnswer(
        answer=answer.answer,
        claims=build_grounded_claims(context) or answer.claims,
        used_evidence_refs=build_used_evidence_refs(context) or answer.used_evidence_refs,
        warnings=warnings,
    )


def answer_decision_meta(node: str, engine: str, fallback_reason: str = "", config: ResumeQAConfig | None = None) -> dict[str, Any]:
    """生成 aggregator/rewrite trace meta；只记录决策，不参与答案内容生成。"""
    meta: dict[str, Any] = {"node": node, "engine": engine, "fallback_reason": fallback_reason}
    if config is not None:
        meta["llm"] = llm_identity(config)
    return meta


def answer_trace_meta(
    inputs: AnswerInputs,
    *,
    llm_mode: str,
    fallback_reason: str,
    drift_rejection_reason: str,
) -> dict[str, Any]:
    """把 layout/context/LLM 决策整理成 trace 字段，供 graph trace 展示。"""
    return aggregator_decision_meta(
        inputs.query_frame,
        inputs.layout_name,
        inputs.layout_reason,
        inputs.context,
        llm_mode=llm_mode,
        fallback_reason=fallback_reason,
        drift_rejection_reason=drift_rejection_reason,
    )


def dedupe_warnings(values: list[str]) -> list[str]:
    """按出现顺序去重 warning，避免多次 fallback 时 trace 噪音膨胀。"""
    output: list[str] = []
    for value in values:
        if value not in output:
            output.append(value)
    return output
