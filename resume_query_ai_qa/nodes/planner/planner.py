"""Select the rule or LLM SemanticPlan generator for the generic path."""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.llm import is_llm_enabled, llm_identity
from resume_query_ai_qa.core.schemas import ExecutionDecision, RouterOutput, SemanticPlan

from .llm import semantic_plan_llm
from .rules import semantic_plan_from_router


def resolve_semantic_plan(
    question: str,
    router_output: RouterOutput,
    decision: ExecutionDecision,
    *,
    use_llm: bool,
    config: ResumeQAConfig,
) -> tuple[SemanticPlan, dict[str, Any]]:
    """生成由执行决策指定的语义计划。"""
    if decision.planner == "rule":
        return semantic_plan_from_router(router_output, decision, config), _meta("rule")
    if not use_llm or not is_llm_enabled(config):
        return semantic_plan_from_router(router_output, decision, config), _meta("rule")
    semantic_plan, fallback_reason = semantic_plan_llm(question, router_output, decision, config)
    if fallback_reason:
        return semantic_plan, _meta("rule_fallback", fallback_reason, config)
    return semantic_plan, _meta("llm", config=config)


def _meta(engine: str, fallback_reason: str = "", config: ResumeQAConfig | None = None) -> dict[str, Any]:
    """实现节点内的元信息处理；输入来自当前节点契约，输出不越过节点职责边界。"""
    meta: dict[str, Any] = {"node": "planner", "engine": engine, "fallback_reason": fallback_reason}
    if config is not None:
        meta["llm"] = llm_identity(config)
    return meta
