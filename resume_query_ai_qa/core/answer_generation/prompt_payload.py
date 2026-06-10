"""Prompt payload compaction for Aggregator LLM calls."""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.schemas import ToolResult


def build_prompt_payload(question: str, query_frame: dict[str, Any], rule_draft: dict[str, Any], context: dict[str, Any], tool_results: list[ToolResult]) -> dict[str, Any]:
    """构建提示词载荷并返回。"""
    return {
        "question": question,
        "query_frame": query_frame,
        "rule_draft": rule_draft,
        "grounded_context": compact_context_for_prompt(context),
        "selected_evidence": select_evidence_for_prompt(context),
        "tool_results_summary": [compact_tool_result_summary(result) for result in tool_results],
    }


def compact_context_for_prompt(context: dict[str, Any]) -> dict[str, Any]:
    """精简答案上下文并返回提示词载荷。"""
    return {
        "task": context.get("task"),
        "count": context.get("count"),
        "candidates": (context.get("candidates") or [])[:20],
        "profiles": (context.get("profiles") or [])[:10],
        "projects": (context.get("projects") or [])[:20],
        "ranking": (context.get("ranking") or [])[:20],
        "comparison": context.get("comparison") or {},
        "empty_flags": context.get("empty_flags") or {},
        "insufficient_info_reasons": context.get("insufficient_info_reasons") or [],
    }


def select_evidence_for_prompt(context: dict[str, Any]) -> list[dict[str, Any]]:
    """根据提示词生成select证据并返回。"""
    return (context.get("evidence") or [])[:8]


def compact_tool_result_summary(result: ToolResult) -> dict[str, Any]:
    """精简工具结果摘要并返回。"""
    data = result.data
    if hasattr(data, "model_dump"):
        data = data.model_dump()
    return {
        "tool_name": result.tool_name,
        "ok": result.ok,
        "error": result.error,
        "shape": type(data).__name__,
        "count": len(data) if isinstance(data, (list, dict)) else None,
    }
