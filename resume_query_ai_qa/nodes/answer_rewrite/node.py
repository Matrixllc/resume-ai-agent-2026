"""Answer rewrite orchestration.

This node repairs answers after answer_validator reports structured issues. It
does not call tools or add facts; deterministic repair rebuilds from existing
tool results, and LLM rewrite remains constrained by aggregator grounding.
"""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.answer_generation import generate_rewrite_candidate_with_meta
from resume_query_ai_qa.core.llm import llm_identity
from resume_query_ai_qa.core.schemas import AggregatedAnswer, ExecutionDecision, QueryPlan, RouterOutput, ToolResult, ValidationIssue

from .policy import classify_answer_repair_policy


def rewrite_answer(
    *,
    question: str,
    plan: QueryPlan,
    tool_results: list[ToolResult],
    previous_answer: AggregatedAnswer | None,
    answer_errors: list[str],
    answer_issues: list[ValidationIssue],
    config: ResumeQAConfig,
    use_llm: bool,
    execution_decision: ExecutionDecision | None = None,
    router_output: RouterOutput | None = None,
) -> tuple[AggregatedAnswer | None, dict[str, Any]]:
    """实现节点内的重写答案处理；输入来自当前节点契约，输出不越过节点职责边界。"""
    policy = classify_answer_repair_policy(answer_issues)
    if previous_answer is None:
        meta = _decision_meta("answer_rewrite", "fallback_request", "missing_previous_answer")
        meta["answer_repair_policy"] = {**policy, "action": "fallback_request"}
        return None, meta
    if policy["action"] == "rule_repair":
        meta = _decision_meta("answer_rewrite", "fallback_request", policy["reason"])
        meta["answer_repair_policy"] = policy
        return None, meta
    answer, meta = generate_rewrite_candidate_with_meta(
        question,
        plan,
        tool_results,
        previous_answer,
        _issue_prompts(answer_errors, answer_issues),
        config,
        use_llm=use_llm,
        node="answer_rewrite",
        execution_decision=execution_decision,
        router_output=router_output,
    )
    meta["answer_repair_policy"] = policy
    return answer, meta


def _issue_prompts(answer_errors: list[str], answer_issues: list[ValidationIssue]) -> list[str]:
    """实现节点内的issueprompts处理；输入来自当前节点契约，输出不越过节点职责边界。"""
    if not answer_issues:
        return answer_errors
    return [
        f"[{issue.category}/{issue.code}/repairable={issue.repairable}] {issue.message}"
        for issue in answer_issues
        if issue.severity == "error"
    ]


def _decision_meta(node: str, engine: str, fallback_reason: str = "", config: ResumeQAConfig | None = None) -> dict[str, Any]:
    """实现节点内的决策元信息处理；输入来自当前节点契约，输出不越过节点职责边界。"""
    meta: dict[str, Any] = {"node": node, "engine": engine, "fallback_reason": fallback_reason}
    if config is not None and engine in {"llm", "rule_fallback"}:
        meta["llm"] = llm_identity(config)
    return meta
