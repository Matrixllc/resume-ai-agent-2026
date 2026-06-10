"""Boundary and generic grounded answer renderers."""

from __future__ import annotations

from typing import Any

from .common import basis_lines, name


def render_boundary() -> str:
    """渲染boundary并返回。"""
    return "结论：这个问题不属于当前简历问答范围，或涉及不适合用于筛选、比较、推荐候选人的敏感边界。"


def render_open_grounded(context: dict[str, Any]) -> str:
    """渲染开放事实约束并返回。"""
    failures = {
        key.removesuffix(".failed"): value
        for key, value in (context.get("empty_flags") or {}).items()
        if str(key).endswith(".failed")
    }
    if failures:
        lines = ["这个问题我暂时不能完整回答。", "原因：" + "；".join(f"{tool}: {error}" for tool, error in failures.items()), "主要依据："]
        lines.extend(f"- {tool} 工具失败：{error}" for tool, error in failures.items())
        return "\n".join(lines)
    lines = ["结论：当前回答基于已执行工具返回的事实生成；未查到的部分会明确说明。", "", "已查到的信息："]
    count = context.get("count") or {}
    if "value" in count:
        lines.append(f"- 数量：{count.get('value')}")
    names = [name(item, "") for item in (context.get("candidates") or context.get("profiles") or [])]
    if names:
        lines.append("- 候选人：" + "、".join(candidate_name for candidate_name in names if candidate_name))
    if not (context.get("count") or names):
        lines.append("- 本轮没有足够的成功工具结果可展示。")
    lines.extend(["", "主要依据："])
    lines.extend(f"- {line}" for line in basis_lines(context, profile_source="tool_results"))
    return "\n".join(lines)
