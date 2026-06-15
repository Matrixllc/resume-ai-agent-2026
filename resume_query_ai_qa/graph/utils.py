from __future__ import annotations

import time
from typing import Any

from resume_query_ai_qa.core.rules.session_context import scoped_session_context
from resume_query_ai_qa.core.schemas import QueryPlan, ResumeQAState

from .state import _GraphState


def elapsed_ms(started: float) -> float:
    """为执行图耗时ms；仅处理编排、状态投影或 trace，不承载业务判断。"""
    return (time.perf_counter() - started) * 1000


def require_plan(qa: ResumeQAState) -> QueryPlan:
    """为执行图require计划；仅处理编排、状态投影或 trace，不承载业务判断。"""
    if qa.plan is None:
        raise ValueError("graph state is missing plan")
    return qa.plan


def current_session_context(state: _GraphState) -> dict[str, Any]:
    """返回本轮允许下游节点使用的会话上下文。

    graph 只负责把 router 的 context policy 投影到后续节点可读的上下文范围；
    具体上下文规则在 core.rules.session_context 中。
    """
    return scoped_session_context(state.get("router_output"), state["qa"].session_context)


def iter_plan_calls(plan: QueryPlan) -> list[Any]:
    """为执行图iter计划调用；仅处理编排、状态投影或 trace，不承载业务判断。"""
    calls = list(plan.tool_calls)
    for sub_task in plan.sub_tasks:
        calls.extend(sub_task.tool_calls)
    return calls


def preview(text: str, limit: int) -> str:
    """为执行图预览；仅处理编排、状态投影或 trace，不承载业务判断。"""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."
