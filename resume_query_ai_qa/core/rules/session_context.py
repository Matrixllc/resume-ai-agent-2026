"""Session context scoping and sanitization rules."""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.schemas import RouterOutput


BASE_CONTEXT_KEYS = {
    "last_turn_id",
    "last_user_question",
    "last_intent",
    "last_conditions",
    "last_normalized_conditions",
    "last_answer_summary",
}

CONTEXT_KEYS_BY_REF_TYPE = {
    "last_candidate": {"last_candidate_id", "last_candidate_name"},
    "ranking_top": {"last_ranking_candidate_ids", "last_ranking_candidate_names"},
    "ranking_top_k": {"last_ranking_candidate_ids", "last_ranking_candidate_names"},
    "candidate_pool": {"last_candidate_pool_ids", "last_candidate_pool_names"},
    "comparison_pair": {"last_comparison_candidate_ids", "last_comparison_candidate_names"},
    "jd": {"last_jd_criteria", "last_conditions", "last_normalized_conditions"},
}

STORED_CONTEXT_KEYS = BASE_CONTEXT_KEYS | set().union(*CONTEXT_KEYS_BY_REF_TYPE.values())
PLAN_DSL_KEYS = {"$ref", "depends_on", "output_key", "tool_calls", "sub_tasks"}


def scoped_session_context(router_output: RouterOutput | None, session_context: dict | None) -> dict[str, Any]:
    """按本轮上下文策略裁剪会话上下文。"""
    if router_output is None or not router_output.context_policy.uses_context:
        return {}
    ref_type = str(router_output.context_policy.context_ref_type or "")
    keys = CONTEXT_KEYS_BY_REF_TYPE.get(ref_type, set())
    if not keys:
        return {}
    return sanitize_session_context(session_context, allowed_keys=keys)


def sanitize_session_context(value: dict | None, *, allowed_keys: set[str] | None = None) -> dict[str, Any]:
    """保留会话事实字段并移除 plan DSL 片段。"""
    source = dict(value or {})
    keys = allowed_keys if allowed_keys is not None else STORED_CONTEXT_KEYS
    cleaned: dict[str, Any] = {}
    for key in keys:
        if key not in source:
            continue
        value_cleaned = _clean_context_value(source.get(key))
        if value_cleaned in (None, "", [], {}):
            continue
        cleaned[key] = value_cleaned
    return cleaned


def _clean_context_value(value: Any) -> Any:
    """递归清理上下文字段值。"""
    if isinstance(value, dict):
        if PLAN_DSL_KEYS & set(value):
            return None
        cleaned = {
            str(key): cleaned_value
            for key, item in value.items()
            if (cleaned_value := _clean_context_value(item)) not in (None, "", [], {})
        }
        return cleaned or None
    if isinstance(value, list):
        cleaned_list = [cleaned for item in value if (cleaned := _clean_context_value(item)) not in (None, "", [], {})]
        return cleaned_list or None
    if isinstance(value, tuple):
        cleaned_list = [cleaned for item in value if (cleaned := _clean_context_value(item)) not in (None, "", [], {})]
        return cleaned_list or None
    return value
