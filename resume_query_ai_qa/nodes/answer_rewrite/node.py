"""Answer rewrite orchestration.

这个文件负责什么：
  在 answer_validator 报错后，决定是请求 rule_answer_fallback，还是生成一个
  LLM rewrite candidate。

应该从哪个函数读起：
  rewrite_answer()。

不会负责什么：
  不调用工具、不新增事实、不直接放行答案；rewrite 后必须回 answer_validator 复检。
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
    """根据 validator issues 生成 rewrite candidate，或返回 None 请求 rule fallback。"""
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
    """把结构化 ValidationIssue 压成 LLM rewrite prompt 可读的错误列表。"""
    if not answer_issues:
        return answer_errors
    return [
        f"[{issue.category}/{issue.code}/repairable={issue.repairable}] {issue.message}"
        for issue in answer_issues
        if issue.severity == "error"
    ]


def _decision_meta(node: str, engine: str, fallback_reason: str = "", config: ResumeQAConfig | None = None) -> dict[str, Any]:
    """构造 rewrite/fallback 决策 meta，供 graph trace 和 diagnosis 使用。"""
    meta: dict[str, Any] = {"node": node, "engine": engine, "fallback_reason": fallback_reason}
    if config is not None and engine in {"llm", "rule_fallback"}:
        meta["llm"] = llm_identity(config)
    return meta
