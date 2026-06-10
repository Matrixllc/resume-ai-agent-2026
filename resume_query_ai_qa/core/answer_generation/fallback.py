"""Deterministic hard-standard fallback for Aggregator."""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.schemas import AggregatedAnswer

from .grounding import build_grounded_claims, build_used_evidence_refs


def render_fallback_answer(question: str, query_frame: dict[str, Any], layout_name: str, context: dict[str, Any]) -> AggregatedAnswer:
    """渲染兜底答案并返回。"""
    lines = [
        "结论：当前回答基于已执行工具返回的事实生成；未查到的部分会明确说明。",
        "",
        render_found_facts_section(context),
        "",
        render_main_basis_section(context),
        "",
        render_insufficient_info_section(context),
    ]
    return AggregatedAnswer(
        answer="\n".join(line for line in lines if line is not None).strip(),
        claims=build_fallback_claims(context),
        used_evidence_refs=build_used_evidence_refs(context),
        warnings=[f"answer_layout:{layout_name}", "answer_layout_source:answer_layouts.yaml", "aggregator_fallback:hard_standard"],
    )


def render_found_facts_section(context: dict[str, Any]) -> str:
    """渲染已发现事实事实集合章节并返回。"""
    lines = ["已查到的信息："]
    count = context.get("count") or {}
    if "value" in count:
        lines.append(f"- 数量：{count.get('value')}")
    candidates = context.get("candidates") or context.get("profiles") or []
    if candidates:
        names = [str(item.get("name") or item.get("resume_identity") or "") for item in candidates if isinstance(item, dict)]
        lines.append("- 候选人：" + "、".join(name for name in names if name))
    ranking = context.get("ranking") or []
    if ranking:
        limit = _ranking_output_limit(context) or 10
        lines.append("- 排名：" + "；".join(f"{item.get('rank')}. {item.get('name') or item.get('resume_identity')}" for item in ranking[:limit]))
    comparison = context.get("comparison") or {}
    if comparison:
        lines.append("- 对比对象：来自 build_comparison_pack。")
    if len(lines) == 1:
        lines.append("- 本轮没有足够的成功工具结果可展示。")
    return "\n".join(lines)


def render_main_basis_section(context: dict[str, Any]) -> str:
    """渲染主流程basis章节并返回。"""
    lines = ["主要依据："]
    evidence = context.get("evidence") or []
    for item in evidence[:3]:
        summary = item.get("summary") or item.get("text") or item.get("project_title") or item.get("source_type") or "工具返回证据"
        lines.append(f"- {summary}")
    if len(lines) == 1:
        tools = sorted({item.get("source") for item in context.get("candidates") or [] if item.get("source")})
        lines.append("- " + (f"候选人信息来自 {', '.join(tools)}。" if tools else "本轮依据来自已执行工具结果。"))
    return "\n".join(lines)


def render_insufficient_info_section(context: dict[str, Any]) -> str:
    """渲染信息不足info章节并返回。"""
    lines = ["证据不足说明："]
    reasons = context.get("insufficient_info_reasons") or []
    if reasons:
        lines.extend(f"- {reason}" for reason in reasons)
    else:
        lines.append("- 未发现额外证据不足标记；如答案未覆盖某项，表示当前工具结果未提供该事实。")
    return "\n".join(lines)


def build_fallback_claims(context: dict[str, Any]):
    """构建兜底声明集合并返回。"""
    return build_grounded_claims(context)


def _ranking_output_limit(context: dict[str, Any]) -> int | None:
    """Read current-turn ranking display limit from answer task slots."""
    slots = ((context.get("task") or {}).get("slots") or {})
    try:
        limit = int(slots.get("ranking_output_limit") or 0)
    except (TypeError, ValueError):
        return None
    return limit if limit > 0 else None
