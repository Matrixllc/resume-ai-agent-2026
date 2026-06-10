"""Interview question generation renderer."""

from __future__ import annotations

from typing import Any

from .common import basis_lines, name, short_focus, target_label


def render_question_generation(query_frame: dict[str, Any], context: dict[str, Any]) -> str:
    """渲染问题generation并返回。"""
    evidence = context.get("evidence") or []
    profiles = context.get("profiles") or []
    count = int((query_frame.get("slots") or {}).get("question_count") or 5)
    count = max(1, min(count, 10))
    target = target_label(query_frame)
    note = "可以基于候选人的简历证据生成以下面试问题。" if evidence or profiles else f"未查到明确{target}证据，以下问题针对性不足。"
    lines = [f"结论：{note}", "", "面试问题："]
    seeds = evidence or profiles
    if seeds:
        for index in range(count):
            item = seeds[index % len(seeds)]
            subject = name(item, str(item.get("candidate_name") or "候选人")) if isinstance(item, dict) else "候选人"
            focus = short_focus(item)
            lines.append(f"{index + 1}. 请{subject}说明{focus}中的本人职责、关键决策和最终结果。")
    else:
        lines.append("1. 当前工具结果不足，暂时不能生成有依据的面试问题。")
    lines.extend(
        [
            "",
            "追问方向：",
            "- 项目目标、候选人本人职责和交付结果",
            "- 方法选择及替代方案",
            "- 业务理解、指标设计和效果评估",
            "- 风险、失败案例和复盘改进",
            "",
            "主要依据：",
        ]
    )
    lines.extend(f"- {line}" for line in basis_lines(context, profile_source="get_candidate_profile_intro"))
    return "\n".join(lines)
