"""Candidate comparison renderer."""

from __future__ import annotations

from typing import Any

from .common import basis_lines, comparison_briefs, comparison_subjects, name, profile_parts


def render_comparison(context: dict[str, Any]) -> str:
    """渲染比较并返回。"""
    subjects = comparison_subjects(context.get("comparison") or {})
    joined = " vs ".join(subjects) if subjects else "已解析的候选人"
    lines = [
        "结论：没有明确 JD、岗位或评价维度时，不能判断绝对谁更好；当前只做事实对比。",
        f"对比对象：{joined}",
        "对比：",
    ]
    for item in comparison_briefs(context.get("comparison") or {}):
        candidate_name = name(item, "候选人")
        parts = profile_parts(item)
        lines.append(f"- {candidate_name}：" + ("；".join(parts) if parts else "comparison_pack 中结构化摘要有限。"))
    lines.extend(["主要依据："])
    basis = basis_lines(context, profile_source="build_comparison_pack")
    lines.extend(f"- {line}" for line in basis)
    return "\n".join(lines)
