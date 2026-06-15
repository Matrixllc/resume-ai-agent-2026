"""Graph adapters for tool execution and execution validation.

这个文件负责什么：
  executor、execution_validator、execution_repair 的 graph state 读写、retry 计数
  和 trace 记录。

应该从哪个函数读起：
  executor_node() -> execution_validator_node() -> execution_repair_node()。

不会负责什么：
  不实现工具业务逻辑、不判断最终答案质量；这里只编排 ToolResult[] 的产生、
  校验和可修复执行后 fallback。
"""

from __future__ import annotations

import time
from typing import Any

from resume_query_ai_qa.nodes.execution_repair import repair_execution_plan
from resume_query_ai_qa.nodes.execution_validator import validate_execution
from resume_query_ai_qa.nodes.executor import execute_plan_with_context

from .state import _GraphState
from .trace_logging import log_decision, plan_summary, record_plan, record_tool_results
from .utils import current_session_context, elapsed_ms, iter_plan_calls, require_plan


def executor_node(state: _GraphState) -> dict[str, Any]:
    """执行已经通过 plan_validator 的 QueryPlan，并把 ToolResult[] 写回 qa。"""
    started = time.perf_counter()
    qa = state["qa"]
    plan = require_plan(qa)
    tool_results = execute_plan_with_context(plan, current_session_context(state), state["config"])
    record_tool_results(qa, plan, tool_results)
    log_decision(
        qa,
        node="executor",
        engine="tools",
        output={"tool_calls": [call.model_dump() for call in iter_plan_calls(plan)], "tool_results_summary": qa.trace.tool_results_summary},
        duration_ms=elapsed_ms(started),
    )
    return {"qa": qa}


def execution_validator_node(state: _GraphState) -> dict[str, Any]:
    """只读校验 ToolResult[]，写回 current_execution_* 字段供 routes 使用。"""
    started = time.perf_counter()
    qa = state["qa"]
    plan = require_plan(qa)
    validation = validate_execution(
        plan=plan,
        tool_results=qa.tool_results,
        config=state["config"],
        router_output=state.get("router_output"),
        session_context=current_session_context(state),
    )
    qa.execution_errors = validation.errors
    qa.trace.execution_validation_errors = []
    if validation.errors:
        qa.trace.execution_validation_errors.extend(validation.errors)
    log_decision(qa, node="execution_validator", engine="validator", output={"ok": validation.ok, "errors": validation.errors, "warnings": validation.warnings, "error_details": [item.model_dump() for item in validation.error_details]}, duration_ms=elapsed_ms(started))
    return {"qa": qa, "execution_validation_ok": validation.ok, "current_execution_errors": validation.errors, "current_execution_issues": validation.error_details}


def execution_repair_node(state: _GraphState) -> dict[str, Any]:
    """修复受控执行后问题；修复后的计划必须回 plan_validator 复检。"""
    started = time.perf_counter()
    qa = state["qa"]
    repairs = int(state.get("execution_repairs", 0)) + 1
    qa.retry_count.planner += 1
    current_errors = state.get("current_execution_errors", [])
    plan, decision = repair_execution_plan(
        qa.question,
        require_plan(qa),
        state["router_output"],
        current_errors,
        qa.tool_results,
        session_context=current_session_context(state),
        config=state["config"],
        validation_issues=state.get("current_execution_issues", []),
    )
    record_plan(qa, plan)
    log_decision(
        qa,
        node="execution_repair",
        engine="rule",
        output={"repairs": repairs, "repair_action": decision["action"], "error_category": decision["category"], "repair_reason": decision["reason"], "previous_errors": current_errors, **plan_summary(plan)},
        duration_ms=elapsed_ms(started),
    )
    return {"qa": qa, "execution_repairs": repairs}
