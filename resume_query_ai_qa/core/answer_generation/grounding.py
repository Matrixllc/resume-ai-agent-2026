"""Grounding authority helpers for Aggregator."""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.schemas import AnswerClaim, EvidenceRef


def build_grounded_claims(context: dict[str, Any]) -> list[AnswerClaim]:
    """构建事实约束声明集合并返回。"""
    claims: list[AnswerClaim] = []
    count = context.get("count") or {}
    if "value" in count:
        claims.append(AnswerClaim(text=str(count.get("value")), claim_type="count", supported_by=["count_candidates"], value=count.get("value")))
    for candidate in context.get("candidates") or []:
        name = str(candidate.get("name") or "").strip()
        if name:
            claims.append(AnswerClaim(text=name, claim_type="name", supported_by=[candidate.get("source") or "tool_result"], subject=name))
    ranking = context.get("ranking") or []
    limit = _ranking_output_limit(context)
    for item in (ranking[:limit] if limit else ranking):
        name = str(item.get("name") or item.get("resume_identity") or "").strip()
        if name:
            claims.append(AnswerClaim(text=name, claim_type="ranking", supported_by=["rank_candidates"], subject=name, value={"rank": item.get("rank"), "score": item.get("total_score")}))
    for profile in context.get("profiles") or []:
        name = str(profile.get("name") or profile.get("resume_identity") or "").strip()
        if name:
            source = str(profile.get("source_tool") or "get_candidate_profile_intro")
            claims.append(AnswerClaim(text=name, claim_type="profile", supported_by=[source], subject=name))
    for item in context.get("evidence") or []:
        subject = str(item.get("candidate_name") or item.get("name") or item.get("resume_identity") or "").strip()
        evidence_id = str(item.get("evidence_id") or "").strip()
        text = str(item.get("summary") or item.get("text") or item.get("project_title") or "evidence").strip()
        claims.append(
            AnswerClaim(
                text=text,
                claim_type="evidence",
                supported_by=[str(item.get("source_tool") or "search_candidate_evidence")],
                subject=subject,
                evidence_ids=[evidence_id] if evidence_id else [],
            )
        )
    if "evidence.empty" in (context.get("empty_flags") or {}):
        claims.append(
            AnswerClaim(
                text="本轮证据检索未返回匹配证据",
                claim_type="evidence",
                supported_by=["search_candidate_evidence"],
            )
        )
    for subject in sorted(comparison_subjects_from_context(context)):
        claims.append(AnswerClaim(text=subject, claim_type="comparison", supported_by=["build_comparison_pack"], subject=subject))
    return claims


def build_used_evidence_refs(context: dict[str, Any]) -> list[EvidenceRef]:
    """从聚合上下文提取最终引用的证据，跳过格式异常的单条证据。"""
    refs: list[EvidenceRef] = []
    seen_ids: set[str] = set()
    for item in context.get("evidence") or []:
        try:
            ref = EvidenceRef.model_validate(item)
        except Exception:
            # 单条证据结构坏了不能进入答案引用，也不能阻断其他证据渲染。
            continue
        evidence_id = str(ref.evidence_id or "").strip()
        if evidence_id and evidence_id in seen_ids:
            continue
        if evidence_id:
            seen_ids.add(evidence_id)
        refs.append(ref)
        if len(refs) >= 5:
            break
    return refs[:5]


def allowed_candidate_names(context: dict[str, Any]) -> set[str]:
    """获取允许项候选人名称集合并返回。"""
    names: set[str] = set()
    for section in ("candidates", "profiles", "ranking"):
        for item in context.get(section) or []:
            name = str(item.get("name") or "").strip()
            if name:
                names.add(name)
    return names


def allowed_evidence_ids(context: dict[str, Any]) -> set[str]:
    """获取允许项证据标识集合并返回。"""
    return {str(item.get("evidence_id")) for item in context.get("evidence") or [] if str(item.get("evidence_id") or "").strip()}


def ranking_sequence_from_context(context: dict[str, Any]) -> list[tuple[int, str]]:
    """从上下文提取排序sequence并返回。"""
    output = []
    ranking = context.get("ranking") or []
    limit = _ranking_output_limit(context)
    for item in (ranking[:limit] if limit else ranking):
        name = str(item.get("name") or item.get("resume_identity") or "").strip()
        rank = int(item.get("rank") or 0)
        if name and rank:
            output.append((rank, name))
    return sorted(output)


def comparison_subjects_from_context(context: dict[str, Any]) -> set[str]:
    """从上下文提取比较主体集合并返回。"""
    data = context.get("comparison") or {}
    names: set[str] = set()
    for value in data.values() if isinstance(data, dict) else []:
        _collect_names(value, names)
    return names


def _collect_names(value: Any, names: set[str]) -> None:
    """收集名称集合并返回。"""
    if isinstance(value, dict):
        name = str(value.get("name") or "").strip()
        if name:
            names.add(name)
        for item in value.values():
            _collect_names(item, names)
    elif isinstance(value, list):
        for item in value:
            _collect_names(item, names)


def _ranking_output_limit(context: dict[str, Any]) -> int | None:
    """Read current-turn ranking display limit from answer task slots."""
    slots = ((context.get("task") or {}).get("slots") or {})
    try:
        limit = int(slots.get("ranking_output_limit") or 0)
    except (TypeError, ValueError):
        return None
    return limit if limit > 0 else None
