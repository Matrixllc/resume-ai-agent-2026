"""Rule answer fallback node helpers."""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.answer_generation import aggregate_answer
from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.schemas import AggregatedAnswer, QueryPlan, ToolResult


def build_rule_fallback(
    question: str,
    plan: QueryPlan,
    tool_results: list[ToolResult],
    config: ResumeQAConfig,
) -> tuple[AggregatedAnswer, dict[str, Any]]:
    """根据工具事实生成规则兜底答案并返回。"""
    answer = aggregate_answer(question, plan, tool_results, config=config)
    return answer, {"node": "rule_answer_fallback", "engine": "rule", "fallback_reason": "deterministic_rule_fallback"}
