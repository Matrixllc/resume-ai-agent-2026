"""Candidate profile, block, and simple fact renderers."""

from __future__ import annotations

from typing import Any

from .common import (
    basis_lines,
    dedupe,
    evidence_by_candidate,
    evidence_summary,
    insufficient_lines,
    name,
    profile_parts,
    target_label,
)


def render_profile_or_fact(query_frame: dict[str, Any], layout_name: str, context: dict[str, Any]) -> str:
    """渲染候选人画像OR事实并返回。"""
    if layout_name == "candidate_blocks":
        return render_candidate_blocks(query_frame, context)
    if layout_name == "simple_fact":
        return render_simple_fact(query_frame, context)
    if "evidence_question" in set(query_frame.get("intents") or []) and "evidence.empty" in (context.get("empty_flags") or {}):
        return render_simple_fact(query_frame, context)
    profiles = context.get("profiles") or []
    business_limit = context.get("business_limits") or {}
    if business_limit.get("error_code") == "profile_display_limit_exceeded":
        return render_profile_display_limit(business_limit)
    if not profiles:
        return render_simple_fact(query_frame, context)
    names = [name(item, "") for item in profiles]
    lines = ["结论：本轮展示候选人信息" + (f"：{'、'.join(candidate_name for candidate_name in names if candidate_name)}。" if names else "。"), "", "候选人信息："]
    for index, profile in enumerate(profiles, start=1):
        candidate_name = name(profile, f"候选人{index}")
        parts = profile_parts(profile)
        lines.append(f"{index}. 候选人：{candidate_name}" + (f"；{'；'.join(parts)}" if parts else "；已解析到候选人画像，但结构化摘要较少。"))
    lines.extend(["", "主要依据："])
    basis = basis_lines(context, profile_source="get_candidate_profile_intro")
    lines.extend(f"- {line}" for line in basis)
    return "\n".join(lines)


def render_candidate_blocks(query_frame: dict[str, Any], context: dict[str, Any]) -> str:
    """渲染候选人blocks并返回。"""
    profiles = context.get("profiles") or []
    target = target_label(query_frame)
    if not profiles:
        return render_simple_fact(query_frame, context)
    names = [name(item, "") for item in profiles]
    lines = [f"结论：本次识别到 {len(profiles)} 位候选人" + (f"：{'、'.join(candidate_name for candidate_name in names if candidate_name)}。" if names else "。") + "以下按人展示个人信息和经历核查。"]
    evidence_by_id = evidence_by_candidate(context)
    basis_items: list[str] = []
    for index, profile in enumerate(profiles, start=1):
        candidate_id = str(profile.get("resume_identity") or "")
        candidate_name = name(profile, f"候选人{index}")
        refs = evidence_by_id.get(candidate_id) or evidence_by_id.get(candidate_name) or []
        lines.extend(["", f"{index}. {candidate_name}", "个人信息：" + ("；".join(profile_parts(profile)) or "已解析到候选人画像，但结构化摘要较少。")])
        if refs:
            selected = refs[:2]
            lines.append("经历核查：" + "；".join(evidence_summary(item) for item in selected))
            basis_items.append(f"{candidate_name}：" + evidence_summary(selected[0]))
        else:
            lines.append(f"经历核查：未查到明确{target}证据，因此目前不能确认。")
            basis_items.append(f"{candidate_name}：本轮候选人画像来自 profile 工具，目标事实未获得 evidence 支撑。")
    lines.extend(["", "主要依据："])
    lines.extend(f"- {line}" for line in dedupe(basis_items)[:5])
    return "\n".join(lines)


def render_simple_fact(query_frame: dict[str, Any], context: dict[str, Any]) -> str:
    """渲染simple事实并返回。"""
    target = target_label(query_frame)
    evidence = context.get("evidence") or []
    if evidence:
        lines = [f"结论：本轮查到与{target}相关的证据。", "", "主要依据："]
        lines.extend(f"- {evidence_summary(item)}" for item in evidence[:5])
    else:
        lines = [f"结论：未查到明确{target}证据，因此目前不能确认。", "", "主要依据：", "未找到匹配的项目证据，因此目前不能确认该候选人具备问题中描述的经验。"]
        lines.extend(f"- {line}" for line in insufficient_lines(context))
    return "\n".join(lines)


def render_profile_display_limit(limit_info: dict[str, Any]) -> str:
    """渲染候选人画像展示限制并返回。"""
    limit = limit_info.get("limit") or 5
    requested = limit_info.get("requested_count") or 0
    names = [str(item) for item in (limit_info.get("candidate_names") or []) if str(item).strip()]
    lines = [
        f"结论：一次最多展示 {limit} 位候选人的个人信息，本次识别到 {requested} 位，请缩小范围后再查看个人信息。",
    ]
    if names:
        lines.extend(["", "本次识别到的候选人："])
        lines.extend(f"{index}. {candidate_name}" for index, candidate_name in enumerate(names, start=1))
    message = str(limit_info.get("user_message") or "").strip()
    lines.extend(["", "主要依据：", f"- get_candidate_profiles_intro 返回展示限制：{message or 'profile_display_limit_exceeded'}"])
    return "\n".join(lines)
