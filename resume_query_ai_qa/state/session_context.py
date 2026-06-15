"""Session context handoff rules for QA state.

这个文件负责什么：
  在 final 阶段从本轮 ResumeQAState 构建下一轮可用的 updated_session_context。

应该从哪个函数读起：
  build_updated_session_context()。

不会负责什么：
  不影响当前轮回答，不决定 route，不调用工具；只扫描已有 ToolResult 和 trace。
"""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.rules.session_context import sanitize_session_context
from resume_query_ai_qa.core.schemas import ResumeQAState


def build_updated_session_context(qa: ResumeQAState) -> dict[str, Any]:
    """从本轮最终状态构建下一轮 session_context，并交给 sanitize 做安全收口。

    输入来自 qa.trace、qa.answer 和成功的 qa.tool_results。输出字段用于下一轮解析
    “第一名/这些人/刚才那个人/JD 标准”等上下文引用。
    """
    context: dict[str, Any] = {}
    context["last_turn_id"] = qa.trace.trace_id
    context["last_user_question"] = qa.question[:300]
    if qa.intent:
        context["last_intent"] = qa.intent
    if qa.trace.router_output:
        context["last_conditions"] = [item.model_dump() for item in qa.trace.router_output.conditions][:20]
        context["last_normalized_conditions"] = [item.model_dump() for item in qa.trace.router_output.normalized_conditions][:20]
    if qa.answer and qa.answer.answer:
        context["last_answer_summary"] = qa.answer.answer[:200]
    for result in qa.tool_results:
        if not result.ok:
            continue
        if result.tool_name == "rank_candidates":
            ranked = result.data or []
            ids = [str(item.resume_identity) for item in ranked if getattr(item, "resume_identity", "")]
            if ids:
                context["last_ranking_candidate_ids"] = ids[:20]
                context["last_ranking_candidate_names"] = [str(getattr(item, "name", "") or "") for item in ranked[:20]]
                context["last_candidate_id"] = ids[0]
                context["last_candidate_name"] = str(getattr(ranked[0], "name", "") or "")
        elif result.tool_name == "build_comparison_pack" and isinstance(result.data, dict):
            ids = [str(item) for item in result.data.get("candidate_ids", []) if str(item).strip()]
            if ids:
                context["last_comparison_candidate_ids"] = ids[:2]
            briefs = result.data.get("briefs") or []
            if briefs:
                context["last_comparison_candidate_names"] = [str(item.get("name", "") or "") for item in briefs[:2] if isinstance(item, dict)]
            if briefs and isinstance(briefs[0], dict):
                context["last_candidate_id"] = str(briefs[0].get("resume_identity", "") or "")
                context["last_candidate_name"] = str(briefs[0].get("name", "") or "")
        elif result.tool_name == "get_candidate_profile_intro" and isinstance(result.data, dict):
            context["last_candidate_id"] = str(result.data.get("resume_identity", "") or "")
            context["last_candidate_name"] = str(result.data.get("name", "") or "")
        elif result.tool_name == "get_candidate_profiles_intro" and isinstance(result.data, dict):
            profiles = result.data.get("profiles") or []
            if profiles and isinstance(profiles[0], dict):
                context["last_candidate_id"] = str(profiles[0].get("resume_identity", "") or "")
                context["last_candidate_name"] = str(profiles[0].get("name", "") or "")
        elif result.tool_name in {"filter_candidates", "hybrid_search_candidates", "list_all_candidates"}:
            ids = _candidate_ids_from_tool_data(result.data)
            if ids:
                context["last_candidate_pool_ids"] = ids[:20]
                context["last_candidate_pool_names"] = _candidate_names_from_tool_data(result.data)[:20]
                context["last_candidate_id"] = ids[0]
        elif result.tool_name in {"load_default_jd_criteria", "load_general_resume_criteria", "extract_jd_criteria"}:
            if hasattr(result.data, "model_dump"):
                context["last_jd_criteria"] = result.data.model_dump()
            elif isinstance(result.data, dict):
                context["last_jd_criteria"] = result.data
    return sanitize_session_context(context)


def _candidate_ids_from_tool_data(data: Any) -> list[str]:
    """从候选人池工具结果中提取 resume_identity 列表。"""
    if not isinstance(data, list):
        return []
    ids: list[str] = []
    for item in data:
        if hasattr(item, "resume_identity"):
            value = str(getattr(item, "resume_identity", "") or "").strip()
        elif isinstance(item, dict):
            value = str(item.get("resume_identity", "") or "").strip()
        else:
            value = ""
        if value:
            ids.append(value)
    return ids


def _candidate_names_from_tool_data(data: Any) -> list[str]:
    """从候选人池工具结果中提取候选人姓名列表。"""
    if not isinstance(data, list):
        return []
    names: list[str] = []
    for item in data:
        if hasattr(item, "name"):
            value = str(getattr(item, "name", "") or "").strip()
        elif isinstance(item, dict):
            value = str(item.get("name", "") or "").strip()
        else:
            value = ""
        if value:
            names.append(value)
    return names
