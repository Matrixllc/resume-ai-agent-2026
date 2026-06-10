"""Execution result requirement checks by intent."""

from __future__ import annotations

from typing import List

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.inspection.plan_inspection import plan_intent_calls as _intent_calls
from resume_query_ai_qa.core.schemas import QueryPlan, ToolResult


def is_allowed_business_limit_result(result: ToolResult, config: ResumeQAConfig | None = None) -> bool:
    """判断允许项业务限制结果是否成立并返回布尔值。"""
    cfg = config or load_config()
    for raw in dict(cfg.tool_policy.get("business_limits", {}) or {}).values():
        rule = dict(raw or {})
        code = str(rule.get("error_code") or "")
        if (
            result.tool_name == str(rule.get("tool") or "")
            and not result.ok
            and result.error == code
            and isinstance(result.data, dict)
            and result.data.get("error_code") == code
        ):
            return True
    return False


def validate_required_tool_results(plan: QueryPlan, tool_results: List[ToolResult], config: ResumeQAConfig | None = None) -> List[str]:
    """校验必需工具结果是否齐全并返回错误列表。"""
    cfg = config or load_config()
    errors: List[str] = []
    tool_names = {item.tool_name for item in tool_results if item.ok or is_allowed_business_limit_result(item, cfg)}
    intents = [intent for intent, _calls in _intent_calls(plan)]
    requirements = dict(cfg.tool_policy.get("intent_result_requirements", {}) or {})
    for intent in intents:
        rule = dict(requirements.get(intent, {}) or {})
        for tool in list(rule.get("all", []) or []):
            if str(tool) not in tool_names:
                errors.append(f"{intent} requires {tool} result")
        any_tools = {str(tool) for tool in list(rule.get("any", []) or [])}
        if any_tools and not any_tools & tool_names:
            errors.append(f"{intent} requires one of {sorted(any_tools)} results")
    return errors


__all__ = ["is_allowed_business_limit_result", "validate_required_tool_results"]
