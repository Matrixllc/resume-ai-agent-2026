"""Graph adapters for terminal states.

这个文件负责什么：
  final、clarification、fail 三个终端节点的 state 收口和 trace 记录。

应该从哪个函数读起：
  final_node() -> clarification_node() -> fail_node()。

不会负责什么：
  不继续规划、不调用工具、不生成新的业务事实。
"""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.schemas import AggregatedAnswer
from resume_query_ai_qa.nodes.clarification import build_clarification
from resume_query_ai_qa.state import build_updated_session_context

from .state import _GraphState
from .trace_logging import log_decision


def final_node(state: _GraphState) -> dict[str, Any]:
    """成功终端：构建下一轮会话上下文，并标记 final_status=ok。"""
    qa = state["qa"]
    qa.updated_session_context = build_updated_session_context(qa)
    qa.trace.updated_session_context = qa.updated_session_context
    log_decision(qa, node="final", engine="graph", output={"status": "ok", "updated_session_context_keys": sorted(qa.updated_session_context)})
    return {"qa": qa, "final_status": "ok"}


def clarification_node(state: _GraphState) -> dict[str, Any]:
    """澄清终端：根据当前 issue 生成用户可回答的问题和选项。"""
    qa = state["qa"]
    issues = state.get("current_plan_issues", []) or state.get("current_execution_issues", []) or state.get("current_answer_issues", [])
    question, options = build_clarification(qa, issues=issues, router_output=state.get("router_output"))
    qa.clarification_required = True
    qa.clarification_question = question
    qa.clarification_options = options
    qa.answer = AggregatedAnswer(answer=question, warnings=["needs_clarification"])
    qa.trace.clarification_required = True
    qa.trace.clarification_question = question
    qa.trace.clarification_options = options
    log_decision(qa, node="clarification", engine="graph", output={"status": "needs_clarification", "question": question, "options": options})
    return {"qa": qa, "final_status": "needs_clarification"}


def fail_node(state: _GraphState) -> dict[str, Any]:
    """失败终端：保留各阶段错误，供 trace 和调用方诊断。"""
    qa = state["qa"]
    log_decision(qa, node="fail", engine="graph", output={"status": "failed", "plan_errors": qa.plan_errors, "execution_errors": qa.execution_errors, "answer_errors": qa.answer_errors})
    return {"qa": qa, "final_status": "failed"}
