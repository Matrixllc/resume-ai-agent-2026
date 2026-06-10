"""Decision, ranking, and fit-analysis renderers."""

from __future__ import annotations

from typing import Any

from .common import basis_lines, decision_reason, evidence_summary, name, profile_parts


def render_decision(layout_name: str, context: dict[str, Any]) -> str:
    """渲染决策并返回。"""
    if layout_name == "fit_analysis":
        return render_fit_analysis(context)
    count = (context.get("count") or {}).get("value")
    if count is None:
        count = ((context.get("task") or {}).get("slots") or {}).get("candidate_count")
    ranking = context.get("ranking") or []
    limit = _ranking_output_limit(context)
    visible_ranking = ranking[:limit] if limit else ranking
    if ranking:
        top = name(ranking[0], "第一名")
        suffix = f"；候选人共 {count} 位。" if count is not None else "。"
        lines = [f"结论：优先推荐 {top}{suffix}"]
    else:
        prefix = f"候选人共 {count} 位，" if count is not None else ""
        lines = [f"结论：{prefix}本轮没有可用排序结果，因此不能判断谁最强。"]
    lines.extend(["", f"候选人总数：{count if count is not None else '未返回明确数量'} 位。", "", "排序结果："])
    if visible_ranking:
        for item in visible_ranking:
            rank = item.get("rank") or "?"
            candidate_name = name(item, "候选人")
            score = item.get("total_score")
            lines.append(f"{rank}. {candidate_name}" + (f"，总分 {score}" if score is not None else ""))
            if item.get("strengths"):
                lines.append("   亮点：" + "；".join(str(value) for value in item.get("strengths", [])[:3]))
            if item.get("risks"):
                lines.append("   风险：" + "；".join(str(value) for value in item.get("risks", [])[:2]))
    else:
        lines.append("- 本轮没有 rank_candidates 排序结果。")
    lines.extend(["", "关键理由："])
    lines.append(decision_reason(ranking))
    lines.extend(["", "主要依据："])
    lines.extend(f"- {line}" for line in basis_lines(context, profile_source="rank_candidates"))
    return "\n".join(lines)


def _ranking_output_limit(context: dict[str, Any]) -> int | None:
    """Read current-turn ranking display limit from answer task slots."""
    slots = ((context.get("task") or {}).get("slots") or {})
    try:
        limit = int(slots.get("ranking_output_limit") or 0)
    except (TypeError, ValueError):
        return None
    return limit if limit > 0 else None


def render_fit_analysis(context: dict[str, Any]) -> str:
    """渲染适配analysis并返回。"""
    profiles = context.get("profiles") or []
    profile = profiles[0] if profiles else {}
    candidate_name = name(profile, "该候选人")
    evidence = context.get("evidence") or []
    lines = [
        f"结论：目前只能基于已查到的简历信息分析{candidate_name}与目标岗位的匹配度；没有证据的能力点不做事实确认。",
        "",
        "关键理由：",
    ]
    parts = profile_parts(profile) if profile else []
    lines.extend(f"- {part}" for part in (parts[:4] or ["本轮 profile/evidence 信息有限，适配判断需要继续核查。"]))
    lines.extend(["", "主要依据："])
    if evidence:
        lines.extend(f"- {evidence_summary(item)}" for item in evidence[:3])
    else:
        lines.append("- 未找到明确匹配该岗位方向的项目证据。")
    lines.extend(["", "缺失/风险：", "- 仍需结合更具体 JD、业务场景和项目深度面试确认。"])
    return "\n".join(lines)
