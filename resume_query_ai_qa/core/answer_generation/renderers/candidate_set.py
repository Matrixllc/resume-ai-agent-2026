"""Candidate count and collection renderers."""

from __future__ import annotations

from typing import Any

from .common import evidence_by_candidate, evidence_summary, name, source_tools, target_label


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


def render_scoped_list_evidence(query_frame: dict[str, Any], context: dict[str, Any]) -> str:
    """Render scoped candidate lists with per-candidate project evidence."""
    candidates = context.get("candidates") or []
    target = scoped_target_label(query_frame)
    names = [name(item, f"候选人{index}") for index, item in enumerate(candidates, start=1)]
    if not candidates:
        return "结论：本轮没有查到匹配候选人。\n\n主要依据：\n- filter_candidates 未返回候选人。"

    lines = [f"结论：{target}候选人共 {len(candidates)} 位：{'、'.join(names)}。", "", "项目经历："]
    grouped = evidence_by_candidate(context)
    basis: list[str] = []
    for index, candidate in enumerate(candidates, start=1):
        candidate_id = str(candidate.get("resume_identity") or "")
        candidate_name = name(candidate, f"候选人{index}")
        refs = grouped.get(candidate_id) or grouped.get(candidate_name) or []
        lines.extend(["", f"{index}. {candidate_name}"])
        if refs:
            lines.append("项目经历：" + "；".join(evidence_summary(item) for item in refs[:3]))
            basis.append(f"{candidate_name}：" + evidence_summary(refs[0]))
        else:
            lines.append("项目经历：未查到明确项目证据")
            basis.append(f"{candidate_name}：未查到明确项目证据")
    lines.extend(["", "主要依据："])
    lines.extend(f"- {item}" for item in basis[:5])
    lines.append(f"- 回答基于已执行工具结果：{source_tools(context)}。")
    return "\n".join(lines)


def scoped_target_label(query_frame: dict[str, Any]) -> str:
    """Return the candidate scope label without project-experience scope words."""
    slots = query_frame.get("slots") or {}
    values = [
        str(item).strip()
        for item in list(slots.get("target_conditions") or [])
        if str(item).strip() and str(item).strip() not in {"项目经验", "项目经历", "项目"}
    ]
    if values:
        return "、".join(values)
    return target_label(query_frame)
