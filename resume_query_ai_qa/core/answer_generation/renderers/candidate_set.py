"""Candidate count and collection renderers."""

from __future__ import annotations

from typing import Any

from .common import name, source_tools


def render_candidate_set(query_frame: dict[str, Any], context: dict[str, Any]) -> str:
    """渲染候选人SET并返回。"""
    lines: list[str] = []
    count = context.get("count") or {}
    candidates = context.get("candidates") or []
    intents = set(query_frame.get("intents") or [])
    if "value" in count:
        lines.append(f"结论：候选人总数：{count.get('value')} 位。")
    elif candidates:
        if "candidate_filter" in intents and "candidate_list" not in intents:
            lines.append(f"匹配候选人：{len(candidates)} 位。")
        else:
            lines.append(f"结论：本轮查到 {len(candidates)} 位候选人。")
    else:
        lines.append("结论：本轮没有查到匹配候选人。")
    if candidates:
        if "value" not in count:
            lines.append("候选人列表：")
        for index, item in enumerate(candidates, start=1):
            candidate_name = name(item, f"候选人{index}")
            lines.append(f"{index}. {candidate_name}")
    lines.extend(["主要依据：", f"- 回答基于已执行工具结果：{source_tools(context)}。"])
    return "\n".join(lines)
