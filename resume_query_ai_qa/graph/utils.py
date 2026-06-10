from __future__ import annotations

import time
from typing import Any

from resume_query_ai_qa.core.schemas import QueryPlan, ResumeQAState


def elapsed_ms(started: float) -> float:
    """为执行图耗时ms；仅处理编排、状态投影或 trace，不承载业务判断。"""
    return (time.perf_counter() - started) * 1000


def require_plan(qa: ResumeQAState) -> QueryPlan:
    """为执行图require计划；仅处理编排、状态投影或 trace，不承载业务判断。"""
    if qa.plan is None:
        raise ValueError("graph state is missing plan")
    return qa.plan


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
