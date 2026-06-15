"""Executor argument reference binding.

这个文件负责什么：
  把 ToolCallSpec.arguments 里的 `$ref` / `$foo.bar[]` 引用解析成真实工具参数。

应该从哪个函数读起：
  先读 iter_tool_calls() 理解执行顺序，再读 bind_argument_refs() 和 resolve_refs()。

不会负责什么：
  不调用工具，不校验 plan 合同，不决定工具是否允许执行。
"""

from __future__ import annotations

from typing import Any, Iterable, List

from resume_query_ai_qa.core.schemas import QueryPlan, ToolCallSpec


def iter_tool_calls(plan: QueryPlan) -> Iterable[ToolCallSpec]:
    """按 compiler 生成的顺序展开普通 plan 或 compound sub_tasks 中的工具调用。"""
    if plan.intent == "compound":
        for sub_task in plan.sub_tasks:
            yield from sub_task.tool_calls
        return
    yield from plan.tool_calls


def plan_with_calls(plan: QueryPlan, calls: List[ToolCallSpec]) -> QueryPlan:
    """把更新后的工具调用放回原 plan 形状，保留普通/compound 结构。"""
    if plan.intent != "compound":
        return plan.model_copy(update={"tool_calls": calls})
    next_index = 0
    sub_tasks = []
    for sub_task in plan.sub_tasks:
        count = len(sub_task.tool_calls)
        sub_tasks.append(sub_task.model_copy(update={"tool_calls": calls[next_index: next_index + count]}))
        next_index += count
    return plan.model_copy(update={"sub_tasks": sub_tasks})


def bind_argument_refs(call: ToolCallSpec, tool_context: dict[str, Any]) -> ToolCallSpec:
    """解析单个工具调用参数里的引用；失败时写入 binding error 供 retry.py 包装。"""
    try:
        arguments = resolve_refs(call.arguments, tool_context)
    except ValueError as error:
        return call.model_copy(update={"arguments": {"__argument_binding_error__": str(error)}})
    return call.model_copy(update={"arguments": arguments})


def resolve_refs(value: Any, tool_context: dict[str, Any]) -> Any:
    """递归解析字符串 `$ref`、结构化 `$ref`、list 和 dict 中的工具结果引用。"""
    if isinstance(value, str) and value.startswith("$"):
        return _resolve_ref(value, tool_context)
    if isinstance(value, list):
        return [resolve_refs(item, tool_context) for item in value]
    if isinstance(value, dict):
        if "$ref" in value:
            return _resolve_structured_ref(value, tool_context)
        return {key: resolve_refs(item, tool_context) for key, item in value.items()}
    return value


def _resolve_structured_ref(raw: dict[str, Any], tool_context: dict[str, Any]) -> Any:
    """解析 `{\"$ref\": root, \"path\": [...], \"map\": true}` 这种结构化引用。"""
    root = str(raw.get("$ref", "") or "").strip()
    if not root:
        raise ValueError("empty structured argument reference root")
    if root not in tool_context:
        raise ValueError(f"unknown argument reference root: {root}")
    value: Any = tool_context[root]
    parts = raw.get("path", [])
    if not isinstance(parts, list):
        raise ValueError(f"structured argument reference path must be a list: {root}")
    if bool(raw.get("map", False)):
        for index, part in enumerate(parts):
            part_text = str(part)
            if index == 0:
                value = [_read_path_part(item, part_text) for item in _ensure_list(value, root)]
            else:
                value = _read_path_part(value, part_text)
        return value
    for part in parts:
        value = _read_path_part(value, str(part))
    return value


def _resolve_ref(raw: str, tool_context: dict[str, Any]) -> Any:
    """解析 `$candidate_pool.resume_identity[]` 这种字符串路径引用。"""
    path = raw[1:].strip()
    if not path:
        raise ValueError("empty argument reference")
    parts = path.split(".")
    root = parts[0]
    if root not in tool_context:
        raise ValueError(f"unknown argument reference root: {root}")
    value: Any = tool_context[root]
    for part in parts[1:]:
        if part.endswith("[]"):
            value = [_read_path_part(item, part[:-2]) for item in _ensure_list(value, raw)]
        else:
            value = _read_path_part(value, part)
    return value


def _read_path_part(value: Any, part: str) -> Any:
    """从 dict / pydantic model / object / list 中读取引用路径的一段。"""
    if not part:
        return value
    if isinstance(value, list) and part.isdigit():
        index = int(part)
        if index >= len(value):
            raise ValueError(f"list index out of range in argument reference: {part}")
        return value[index]
    if isinstance(value, list):
        return [_read_path_part(item, part) for item in value]
    if isinstance(value, dict):
        if part not in value:
            raise ValueError(f"missing key in argument reference: {part}")
        return value[part]
    if hasattr(value, "model_dump"):
        return _read_path_part(value.model_dump(), part)
    if hasattr(value, part):
        return getattr(value, part)
    raise ValueError(f"cannot read {part!r} from argument reference value")


def _ensure_list(value: Any, raw: str) -> list:
    """确保当前引用值是列表；`[]` 和 map 语义都依赖列表输入。"""
    if not isinstance(value, list):
        raise ValueError(f"argument reference requires a list: {raw}")
    return value
