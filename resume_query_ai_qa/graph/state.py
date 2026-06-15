"""Internal state shape for one Query-AI graph run.

这个文件负责什么：
  定义 graph 节点之间传递的 `_GraphState`，以及一次运行的初始 state。

应该从哪个函数读起：
  _GraphState -> build_initial_state()。

不会负责什么：
  不记录业务规则，不做 route 判断，不持久化 trace。
"""

from __future__ import annotations

from typing import Any, TypedDict

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.schemas import ExecutionDecision, ResumeQAState, RouterOutput, SemanticPlan, ValidationIssue


class _GraphState(TypedDict, total=False):
    # 运行基础字段：贯穿整条 graph。
    qa: ResumeQAState
    config: ResumeQAConfig
    use_llm: bool

    # 重试上限：routes.py 只读这些字段决定是否还能 repair/rewrite。
    max_plan_repairs: int
    max_execution_repairs: int
    max_answer_rewrites: int

    # 上游语义产物：后续 planner/compiler/validator 会消费。
    router_output: RouterOutput
    semantic_plan: SemanticPlan
    execution_decision: ExecutionDecision

    # validator 布尔结果：routes.py 的第一层判断。
    plan_validation_ok: bool
    execution_validation_ok: bool
    answer_validation_ok: bool

    # 当前已用 repair/rewrite 次数。
    plan_repairs: int
    execution_repairs: int
    answer_rewrites: int

    # 当前阶段错误：repair/clarification/fail 节点用它们解释下一步。
    current_plan_errors: list[str]
    current_plan_issues: list[ValidationIssue]
    current_execution_errors: list[str]
    current_execution_issues: list[ValidationIssue]
    current_answer_errors: list[str]
    current_answer_issues: list[ValidationIssue]

    # answer 层 fallback 信号：answer_rewrite 请求确定性 rule fallback 时写入。
    answer_fallback_requested: bool

    # 终端和观测字段。
    final_status: str
    last_decision_meta: dict[str, Any]


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
    """根据问题、会话上下文和运行参数构建初始 graph state。"""
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
