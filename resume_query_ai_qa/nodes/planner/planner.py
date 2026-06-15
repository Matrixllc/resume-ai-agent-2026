"""Planner node entrypoint.

这个文件负责什么：
- generic 路径下选择 rule planner 或 LLM planner。
- 输出 SemanticPlan 和 trace meta。

应该从哪个函数读起：
- resolve_semantic_plan

不会负责什么：
- 不决定 template/generic 分流，那是 execution_policy 的职责。
- 不生成 QueryPlan / ToolCallSpec，那是 plan_compiler 的职责。
"""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.llm import is_llm_enabled, llm_identity
from resume_query_ai_qa.core.rules.semantic_plan import semantic_plan_from_router
from resume_query_ai_qa.core.schemas import ExecutionDecision, RouterOutput, SemanticPlan

from .llm import semantic_plan_llm


def resolve_semantic_plan(
    question: str,
    router_output: RouterOutput,
    decision: ExecutionDecision,
    *,
    use_llm: bool,
    config: ResumeQAConfig,
) -> tuple[SemanticPlan, dict[str, Any]]:
    """生成由执行决策指定的语义计划。

    decision.planner 是本函数的入口开关。rule 路径完全确定；LLM 路径
    只产 draft，并由 semantic_plan_llm 内部做 YAML/router 权威收口。
    """
    if decision.planner == "rule":
        return semantic_plan_from_router(router_output, decision, config), _meta("rule")
    if not use_llm or not is_llm_enabled(config):
        return semantic_plan_from_router(router_output, decision, config), _meta("rule")
    semantic_plan, fallback_reason = semantic_plan_llm(question, router_output, decision, config)
    if fallback_reason:
        return semantic_plan, _meta("rule_fallback", fallback_reason, config)
    return semantic_plan, _meta("llm", config=config)


def _meta(engine: str, fallback_reason: str = "", config: ResumeQAConfig | None = None) -> dict[str, Any]:
    """生成 planner trace meta，不影响 SemanticPlan 内容。"""
    meta: dict[str, Any] = {"node": "planner", "engine": engine, "fallback_reason": fallback_reason}
    if config is not None:
        meta["llm"] = llm_identity(config)
    return meta
