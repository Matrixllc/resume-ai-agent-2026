"""answer_layouts.yaml 和 aggregator_tasks.yaml 的答案规则校验。"""

from __future__ import annotations

from typing import Any

from .common import check_tool


def validate_answer_layouts(payload: dict[str, Any], tools: set[str], errors: list[str]) -> None:
    """校验答案 layout 引用的 required tool 都存在。"""
    for layout, raw in dict(payload.get("layouts", {}) or {}).items():
        requirements = dict(dict(raw or {}).get("required_tools", {}) or {})
        for field in ("all", "any"):
            for tool in list(requirements.get(field, []) or []):
                check_tool(f"answer_layouts.yaml: layouts.{layout}.required_tools", field, tool, tools, errors)


def validate_aggregator_tasks(payload: dict[str, Any], tools: set[str], errors: list[str]) -> None:
    """校验聚合任务的 source tools 和 fallback layout 声明完整。"""
    layouts = set(dict(payload.get("layout_selection", {}) or {}).keys())
    for task, raw in dict(payload.get("task_types", {}) or {}).items():
        entry = dict(raw or {})
        for tool in list(entry.get("source_tools", []) or []):
            check_tool(f"aggregator_tasks.yaml: task_types.{task}", "source_tools", tool, tools, errors)
        layout = str(entry.get("fallback_layout") or "").strip()
        if layout and layout not in layouts:
            errors.append(f"aggregator_tasks.yaml: task_types.{task}.fallback_layout references unknown layout `{layout}`")
