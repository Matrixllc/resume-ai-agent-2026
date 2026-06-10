"""Executor node entrypoints for deterministic tool calls.

Executor receives a QueryPlan that already passed plan validation. It binds
argument references, calls read-only tools, and returns ToolResult objects.
It does not validate result sufficiency, repair plans, summarize, or create
new tool calls.
"""

from __future__ import annotations

from typing import Any, List

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.schemas import QueryPlan, ToolCallSpec, ToolResult

from .binding import bind_argument_refs, iter_tool_calls, plan_with_calls
from .retry import execute_tool_call_with_retry


def execute_plan(plan: QueryPlan, config: ResumeQAConfig | None = None) -> List[ToolResult]:
    """按计划顺序执行全部工具调用。"""
    cfg = config or load_config()
    results: List[ToolResult] = []
    tool_context: dict[str, Any] = {}
    for call in iter_tool_calls(plan):
        executable_call = bind_argument_refs(call, tool_context)
        result = execute_tool_call(executable_call, config=cfg)
        results.append(result)
        if result.ok and call.output_key:
            tool_context[call.output_key] = result.data
    return results


def execute_plan_with_context(
    plan: QueryPlan,
    session_context: dict | None = None,
    config: ResumeQAConfig | None = None,
) -> List[ToolResult]:
    """执行计划，并把会话上下文绑定到引用解析调用。"""
    bound_calls = []
    for call in iter_tool_calls(plan):
        if call.name == "resolve_candidate_reference" and "session_context" not in call.arguments:
            call = call.model_copy(
                update={"arguments": {**call.arguments, "session_context": session_context or {}}}
            )
        bound_calls.append(call)
    bound_plan = plan_with_calls(plan, bound_calls)
    return execute_plan(bound_plan, config=config)


def execute_tool_call(call: ToolCallSpec, config: ResumeQAConfig | None = None) -> ToolResult:
    """执行单个工具调用，并对运行时异常进行有限重试。"""
    cfg = config or load_config()
    return execute_tool_call_with_retry(call, cfg)
