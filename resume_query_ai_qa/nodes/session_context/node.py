"""Session context support helpers for terminal graph nodes."""

from __future__ import annotations

from resume_query_ai_qa.core.data_access import list_known_candidate_names


def candidate_options(limit: int = 8) -> list[str]:
    """返回适合在澄清提示中展示的候选人标签。"""
    return list_known_candidate_names()[:limit]
