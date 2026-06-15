"""Executor node entrypoints.

这个文件负责什么：
  接收已经通过 plan_validator 的 QueryPlan，按顺序调用只读工具，返回 ToolResult[]。

应该从哪个函数读起：
  graph 路径先读 execute_plan_with_context()，单测/底层路径可读 execute_plan()。

不会负责什么：
  不生成 ToolCallSpec，不修复 plan，不判断结果是否足够，不生成最终答案。
"""

from __future__ import annotations

from typing import Any, List

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.schemas import QueryPlan, ToolCallSpec, ToolResult

from .binding import bind_argument_refs, iter_tool_calls, plan_with_calls
from .retry import execute_tool_call_with_retry


def execute_plan(plan: QueryPlan, config: ResumeQAConfig | None = None) -> List[ToolResult]:
    """按 QueryPlan 顺序执行全部工具调用，并维护 `$ref` 可读取的 tool_context。"""
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
    """执行 graph 传入的计划，并为候选人上下文解析工具注入 session_context。"""
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
    """执行单个工具调用；实际 registry 查找、错误包装和 retry 在 retry.py。"""
    cfg = config or load_config()
    return execute_tool_call_with_retry(call, cfg)
