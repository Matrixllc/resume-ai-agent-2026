"""Choose the template or generic planner path for a normalized query."""

from __future__ import annotations

from typing import Literal

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.rules.execution_policy_rules import resolve_execution_decision
from resume_query_ai_qa.core.schemas import ExecutionDecision, RouterOutput


def resolve_execution_policy(
    question: str,
    router_output: RouterOutput,
    config: ResumeQAConfig,
) -> ExecutionDecision:
    """返回执行图使用的明确调度决策。"""
    return resolve_execution_decision(question, router_output, config)


def route_after_execution_policy(decision: ExecutionDecision) -> Literal["template", "generic"]:
    """将执行决策映射为执行图边标签。"""
    return "template" if decision.compiler == "workflow_template" else "generic"
