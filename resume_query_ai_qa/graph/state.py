from __future__ import annotations

from typing import Any, TypedDict

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.schemas import ExecutionDecision, ResumeQAState, RouterOutput, SemanticPlan, ValidationIssue


class _GraphState(TypedDict, total=False):
    qa: ResumeQAState
    config: ResumeQAConfig
    use_llm: bool
    max_plan_repairs: int
    max_execution_repairs: int
    max_answer_rewrites: int
    router_output: RouterOutput
    plan_validation_ok: bool
    execution_validation_ok: bool
    answer_validation_ok: bool
    plan_repairs: int
    execution_repairs: int
    answer_rewrites: int
    current_plan_errors: list[str]
    current_plan_issues: list[ValidationIssue]
    current_execution_errors: list[str]
    current_execution_issues: list[ValidationIssue]
    current_answer_errors: list[str]
    current_answer_issues: list[ValidationIssue]
    answer_fallback_requested: bool
    final_status: str
    last_decision_meta: dict[str, Any]
    semantic_plan: SemanticPlan
    execution_decision: ExecutionDecision


def build_initial_state(
    question: str,
    session_context: dict | None,
    *,
    use_llm: bool,
    max_plan_repairs: int,
    max_execution_repairs: int,
    max_answer_rewrites: int,
    config: ResumeQAConfig,
) -> _GraphState:
    """根据问题和运行配置构建初始图状态并返回。"""
    return {
        "qa": ResumeQAState(question=question, session_context=session_context or {}),
        "config": config,
        "use_llm": use_llm,
        "max_plan_repairs": max_plan_repairs,
        "max_execution_repairs": max_execution_repairs,
        "max_answer_rewrites": max_answer_rewrites,
        "plan_repairs": 0,
        "execution_repairs": 0,
        "answer_rewrites": 0,
        "final_status": "pending",
    }
