"""Reference helpers for QueryPlan arguments."""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.schemas import QueryPlan, ToolCallSpec


def structured_arg_ref(root: str, path: list[str] | None = None, *, mapped: bool = False) -> dict[str, Any]:
    """获取结构化参数引用并返回。"""
    return {"$ref": root, "path": list(path or []), "map": mapped}


def replace_ref_root(call: ToolCallSpec, old: str, new: str) -> ToolCallSpec:
    """替换引用根引用并返回`ToolCallSpec`。"""
    def replace(value: Any) -> Any:
        """替换数据并返回处理结果。"""
        if isinstance(value, dict):
            if value.get("$ref") == old:
                return {**value, "$ref": new}
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, str) and value.startswith(f"${old}"):
            return f"${new}{value[len(old) + 1:]}"
        return value

    return call.model_copy(update={
        "arguments": replace(call.arguments),
        "depends_on": [new if item == old else item for item in call.depends_on],
    })


def with_structured_refs(plan: QueryPlan) -> QueryPlan:
    """将参数引用转换为结构化引用并返回。"""
    return plan.model_copy(
        update={
            "tool_calls": [call_with_structured_refs(call) for call in plan.tool_calls],
            "sub_tasks": [
                task.model_copy(update={"tool_calls": [call_with_structured_refs(call) for call in task.tool_calls]})
                for task in plan.sub_tasks
            ],
        }
    )


def call_with_structured_refs(call: ToolCallSpec) -> ToolCallSpec:
    """转换工具调用中的参数引用并返回新调用。"""
    return call.model_copy(update={"arguments": convert_argument_refs(call.arguments)})


def convert_argument_refs(value: Any) -> Any:
    """转换参数引用集合并返回。"""
    if isinstance(value, str) and value.startswith("$"):
        raw = value[1:]
        mapped = raw.endswith("[]")
        raw = raw[:-2] if mapped else raw
        parts = raw.split(".")
        return structured_arg_ref(parts[0], parts[1:], mapped=mapped)
    if isinstance(value, dict):
        return {key: convert_argument_refs(item) for key, item in value.items()}
    if isinstance(value, list):
        return [convert_argument_refs(item) for item in value]
    return value
