"""Read-only QueryPlan and argument reference inspection helpers."""

from __future__ import annotations

from typing import Any, Iterable, List

from resume_query_ai_qa.core.schemas import QueryPlan, ToolCallSpec


def plan_intent_calls(plan: QueryPlan) -> List[tuple[str, List[ToolCallSpec]]]:
    """获取计划意图调用集合并返回。"""
    if plan.intent == "compound":
        return [(sub_task.intent, sub_task.tool_calls) for sub_task in plan.sub_tasks]
    return [(plan.intent, plan.tool_calls)]


def plan_tool_calls(plan: QueryPlan) -> List[ToolCallSpec]:
    """获取计划工具调用集合并返回。"""
    return [call for _intent, calls in plan_intent_calls(plan) for call in calls]


def argument_refs(value: Any) -> List[str]:
    """获取参数引用集合并返回。"""
    refs: List[str] = []
    if isinstance(value, str) and is_argument_ref(value):
        refs.append(value[1:])
    elif isinstance(value, dict):
        if is_structured_argument_ref(value):
            root = str(value.get("$ref", "") or "").strip()
            path = value.get("path", [])
            if isinstance(path, list) and path:
                refs.append(".".join([root, *[str(item) for item in path]]))
            else:
                refs.append(root)
            return refs
        for item in value.values():
            refs.extend(argument_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.extend(argument_refs(item))
    return refs


def is_argument_ref(value: Any) -> bool:
    """判断参数引用是否成立并返回布尔值。"""
    return isinstance(value, str) and value.startswith("$") and len(value) > 1


def is_structured_argument_ref(value: Any) -> bool:
    """判断结构化参数引用是否成立并返回布尔值。"""
    return isinstance(value, dict) and isinstance(value.get("$ref"), str) and bool(value.get("$ref", "").strip())


def argument_ref_root(value: Any) -> str:
    """获取参数引用根引用并返回。"""
    if isinstance(value, str) and is_argument_ref(value):
        return value[1:].split(".", 1)[0]
    if is_structured_argument_ref(value):
        return str(value.get("$ref", "") or "").strip()
    return ""


def candidate_ids_from_calls(calls: Iterable[ToolCallSpec]) -> List[str]:
    """从调用集合提取候选人标识集合并返回。"""
    for call in calls:
        raw = call.arguments.get("candidate_ids")
        if isinstance(raw, list):
            return [str(item) for item in raw if str(item).strip()]
    return []


def candidate_ids_argument_from_calls(calls: Iterable[ToolCallSpec]):
    """从调用集合提取候选人标识集合参数并返回。"""
    for call in calls:
        if call.name == "build_comparison_pack":
            return call.arguments.get("candidate_ids")
    return None
