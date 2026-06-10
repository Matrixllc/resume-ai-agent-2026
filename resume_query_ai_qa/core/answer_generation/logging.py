"""Aggregator trace metadata helpers."""

from __future__ import annotations

from typing import Any


def aggregator_decision_meta(
    query_frame: dict[str, Any],
    layout_name: str,
    layout_match_reason: str,
    context: dict[str, Any],
    *,
    llm_mode: str,
    fallback_reason: str = "",
    drift_rejection_reason: str = "",
) -> dict[str, Any]:
    """获取aggregator决策元信息并返回。"""
    return {
        "task_type": query_frame.get("task_type", ""),
        "freedom_level": query_frame.get("freedom_level", ""),
        "slots": query_frame.get("slots") or {},
        "task_match_reason": query_frame.get("match_reason", ""),
        "answer_layout": layout_name,
        "answer_layout_source": "answer_layouts.yaml",
        "layout_match_reason": layout_match_reason,
        "context_summary": context_summary_for_log(context),
        "llm_mode": llm_mode,
        "fallback_reason": fallback_reason,
        "drift_rejection_reason": drift_rejection_reason,
        "insufficient_info_reasons": context.get("insufficient_info_reasons") or [],
    }


def context_summary_for_log(context: dict[str, Any]) -> dict[str, Any]:
    """根据日志生成上下文摘要并返回。"""
    return {
        "candidate_count": len(context.get("candidates") or []),
        "profile_count": len(context.get("profiles") or []),
        "project_count": len(context.get("projects") or []),
        "evidence_count": len(context.get("evidence") or []),
        "ranking_count": len(context.get("ranking") or []),
        "comparison_subjects": sorted(_comparison_subjects(context.get("comparison") or {})),
        "empty_flags": context.get("empty_flags") or {},
    }


def task_summary_for_log(query_frame: dict[str, Any]) -> dict[str, Any]:
    """根据日志生成任务摘要并返回。"""
    return {
        "task_type": query_frame.get("task_type", ""),
        "freedom_level": query_frame.get("freedom_level", ""),
        "slots": query_frame.get("slots") or {},
        "match_reason": query_frame.get("match_reason", ""),
    }


def fallback_summary_for_log(reason: str, context: dict[str, Any]) -> dict[str, Any]:
    """根据日志生成兜底摘要并返回。"""
    return {"fallback_reason": reason, "context_summary": context_summary_for_log(context)}


def _comparison_subjects(value) -> set[str]:
    """获取比较主体集合并返回。"""
    names: set[str] = set()
    if isinstance(value, dict):
        name = str(value.get("name") or "").strip()
        if name:
            names.add(name)
        for item in value.values():
            names |= _comparison_subjects(item)
    elif isinstance(value, list):
        for item in value:
            names |= _comparison_subjects(item)
    return names
