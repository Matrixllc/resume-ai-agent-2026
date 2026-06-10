"""Formatting helpers shared by deterministic answer renderers.

This module should stay free of routing or business-policy decisions. Layout
choice belongs to ``answer_layouts.yaml`` plus ``layout.py``; these helpers only
turn already-approved tool facts into readable text fragments.
"""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.schemas import AggregatedAnswer


def with_layout_warning(answer: str, layout_name: str) -> AggregatedAnswer:
    """为答案追加布局警告并返回更新后的答案。"""
    return AggregatedAnswer(answer=answer.strip(), warnings=[f"answer_layout:{layout_name}", "answer_layout_source:answer_layouts.yaml"])


def target_label(query_frame: dict[str, Any]) -> str:
    """获取targetlabel并返回。"""
    slots = query_frame.get("slots") or {}
    value = str(slots.get("fact_check_target") or "").strip()
    if value:
        return value
    values = [str(item).strip() for item in list(slots.get("target_conditions") or []) if str(item).strip()]
    return "、".join(values) if values else "相关经历/目标条件"


def profile_parts(profile: dict[str, Any]) -> list[str]:
    """获取候选人画像parts并返回。"""
    parts: list[str] = []
    if profile.get("job_intent"):
        parts.append(f"求职意向：{profile.get('job_intent')}")
    if profile.get("domains"):
        parts.append("领域标签：" + "、".join(str(item) for item in profile.get("domains", [])[:5]))
    if profile.get("skills"):
        parts.append("技能标签：" + "、".join(str(item) for item in profile.get("skills", [])[:8]))
    if profile.get("work"):
        parts.append(f"工作经历 {len(profile.get('work') or [])} 段")
    if profile.get("projects"):
        titles = [str(item.get("title") or item.get("project_title") or "") for item in profile.get("projects", []) if isinstance(item, dict)]
        parts.append("项目 " + ("、".join(title for title in titles[:3] if title) or f"{len(profile.get('projects') or [])} 个"))
    return parts


def basis_lines(context: dict[str, Any], *, profile_source: str) -> list[str]:
    """获取basislines并返回。"""
    evidence = context.get("evidence") or []
    if evidence:
        return [evidence_summary(item) for item in evidence[:3]]
    reasons = context.get("insufficient_info_reasons") or []
    if reasons:
        return [str(item) for item in reasons[:3]]
    return [f"回答基于已执行工具结果：{source_tools(context) or profile_source}。"]


def insufficient_lines(context: dict[str, Any]) -> list[str]:
    """获取信息不足lines并返回。"""
    reasons = context.get("insufficient_info_reasons") or []
    if reasons:
        return [str(item) for item in reasons[:3]]
    return ["本轮未返回可支持该事实的 evidence；不能根据标签或背景推断。"]


def decision_reason(ranking: list[dict[str, Any]]) -> str:
    """获取决策原因并返回。"""
    if not ranking:
        return "缺少排序结果，不能生成推荐理由。"
    top = ranking[0]
    strengths = [str(item) for item in list(top.get("strengths") or []) if str(item).strip()]
    risks = [str(item) for item in list(top.get("risks") or []) if str(item).strip()]
    parts = []
    if strengths:
        parts.append("亮点：" + "；".join(strengths[:3]))
    if risks:
        parts.append("风险：" + "；".join(risks[:2]))
    return "；".join(parts) if parts else "排序顺序来自 rank_candidates，未额外改写排序。"


def evidence_summary(item: dict[str, Any]) -> str:
    """获取证据摘要并返回。"""
    subject = str(item.get("candidate_name") or item.get("name") or "").strip()
    title = str(item.get("project_title") or item.get("source_type") or "").strip()
    text = str(item.get("summary") or item.get("text") or "").strip()
    body = text or title or "工具返回证据"
    if len(body) > 90:
        body = body[:90] + "..."
    if subject and title:
        return f"{subject}在{title}中体现：{body}"
    if subject:
        return f"{subject}：{body}"
    return body


def evidence_by_candidate(context: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """按候选人整理证据并返回。"""
    output: dict[str, list[dict[str, Any]]] = {}
    for item in context.get("evidence") or []:
        for key in (str(item.get("resume_identity") or ""), str(item.get("candidate_name") or "")):
            if key:
                output.setdefault(key, []).append(item)
    return output


def comparison_briefs(value: Any) -> list[dict[str, Any]]:
    """获取比较briefs并返回。"""
    if isinstance(value, dict) and isinstance(value.get("briefs"), list):
        return [item for item in value.get("briefs", []) if isinstance(item, dict)]
    return []


def comparison_subjects(value: Any) -> list[str]:
    """获取比较主体集合并返回。"""
    names: list[str] = []
    for item in comparison_briefs(value):
        candidate_name = name(item, "")
        if candidate_name and candidate_name not in names:
            names.append(candidate_name)
    return names


def short_focus(item: dict[str, Any]) -> str:
    """获取shortfocus并返回。"""
    if not isinstance(item, dict):
        return "简历信息"
    return str(item.get("project_title") or item.get("summary") or item.get("text") or item.get("job_intent") or "简历信息")[:40]


def source_tools(context: dict[str, Any]) -> str:
    """获取来源工具集合并返回。"""
    sources = {str(item.get("source") or "") for item in context.get("candidates") or [] if isinstance(item, dict)}
    sources |= {str(item.get("source_tool") or "") for item in context.get("evidence") or [] if isinstance(item, dict)}
    if context.get("count"):
        sources.add(str((context.get("count") or {}).get("source") or "count_candidates"))
    if context.get("ranking"):
        sources.add("rank_candidates")
    if context.get("comparison"):
        sources.add("build_comparison_pack")
    return "、".join(sorted(source for source in sources if source))


def name(item: dict[str, Any], fallback: str) -> str:
    """获取名称并返回。"""
    return str(item.get("name") or item.get("candidate_name") or item.get("resume_identity") or fallback)


def dedupe(values: list[str]) -> list[str]:
    """去重结果并返回。"""
    output: list[str] = []
    for value in values:
        if value not in output:
            output.append(value)
    return output
