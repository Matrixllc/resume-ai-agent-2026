"""Bounded runtime retry for executor tool calls."""

from __future__ import annotations

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.schemas import ToolCallSpec, ToolResult
from resume_query_ai_qa.tools import get_tool_registry


def execute_tool_call_with_retry(call: ToolCallSpec, config: ResumeQAConfig) -> ToolResult:
    """执行工具调用及受控重试并返回工具结果。"""
    binding_error = call.arguments.get("__argument_binding_error__")
    if binding_error:
        return ToolResult(tool_name=call.name, ok=False, error=f"argument binding failed: {binding_error}")

    registry = get_tool_registry()
    tool = registry.get(call.name)
    if tool is None:
        return ToolResult(tool_name=call.name, ok=False, error=f"unknown tool: {call.name}")

    max_attempts = max(config.retry_limit("executor_tool_call", 0), 0) + 1
    last_error = ""
    for _attempt in range(1, max_attempts + 1):
        try:
            data = tool(**call.arguments)
            if isinstance(data, dict) and data.get("__business_error__"):
                payload = data.get("__data__") if isinstance(data.get("__data__"), dict) else {}
                return ToolResult(
                    tool_name=call.name,
                    ok=False,
                    data=payload,
                    error=str(data.get("__error__") or payload.get("error_code") or "business_error"),
                    warnings=[str(payload.get("user_message", ""))] if payload.get("user_message") else [],
                )
            if isinstance(data, dict) and "__data__" in data:
                warnings = data.get("__warnings__", [])
                return ToolResult(
                    tool_name=call.name,
                    ok=True,
                    data=data.get("__data__"),
                    warnings=[str(item) for item in warnings if str(item).strip()] if isinstance(warnings, list) else [],
                )
            return ToolResult(tool_name=call.name, ok=True, data=data)
        except Exception as error:
            last_error = f"{type(error).__name__}: {error}"
    return ToolResult(tool_name=call.name, ok=False, error=last_error)
