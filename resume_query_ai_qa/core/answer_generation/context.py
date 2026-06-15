"""Build grounded answer context from ToolResult facts.

这个文件负责什么：
  只从 ToolResult[] 收集答案事实，形成 LLM 和规则 renderer 共用的 grounded_context。

应该从哪个函数读起：
  build_answer_context()，再按 count/candidate/profile/evidence/ranking/comparison collector 阅读。

不会负责什么：
  不调用工具，不补事实，不判断答案是否合格。
"""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.schemas import QueryPlan, ToolResult


def build_answer_context(query_frame: dict[str, Any], plan: QueryPlan, tool_results: list[ToolResult]) -> dict[str, Any]:
    """从 ToolResult[] 构建 grounded_context；这是答案事实和 LLM payload 的主要来源。"""
    task = {key: query_frame.get(key) for key in ["task_type", "freedom_level", "slots", "intents", "scenarios"]}
    slots = dict(task.get("slots") or {})
    if plan.constraints.ranking_output_limit:
        slots["ranking_output_limit"] = plan.constraints.ranking_output_limit
    task["slots"] = slots
    return {
        "task": task,
        "count": collect_count_context(tool_results),
        "candidates": collect_candidate_context(tool_results),
        "profiles": collect_profile_context(tool_results),
        "projects": collect_project_context(tool_results),
        "evidence": collect_evidence_context(tool_results),
        "ranking": collect_ranking_context(tool_results),
        "comparison": collect_comparison_context(tool_results),
        "business_limits": collect_business_limit_context(tool_results),
        "empty_flags": collect_empty_flags(tool_results),
        "insufficient_info_reasons": collect_insufficient_info_reasons(tool_results),
    }


def collect_count_context(tool_results: list[ToolResult]) -> dict[str, Any]:
    """收集数量上下文并返回。"""
    for result in tool_results:
        if result.ok and result.tool_name == "count_candidates":
            return {"value": result.data, "source": result.tool_name}
    return {}


def collect_candidate_context(tool_results: list[ToolResult]) -> list[dict[str, Any]]:
    """收集候选人上下文并返回。"""
    output: list[dict[str, Any]] = []
    for result in tool_results:
        if not result.ok or result.tool_name not in {"filter_candidates", "list_all_candidates", "hybrid_search_candidates", "resolve_candidate_reference"}:
            continue
        _collect_candidate_items(result.data, output, result.tool_name)
    return _dedupe_candidates(output)[:50]


def collect_profile_context(tool_results: list[ToolResult]) -> list[dict[str, Any]]:
    """收集候选人画像上下文并返回。"""
    output: list[dict[str, Any]] = []
    for result in tool_results:
        if not result.ok or result.tool_name not in {"get_candidate_profile_intro", "get_candidate_profiles_intro"}:
            continue
        data = _dump(result.data)
        profiles = data.get("profiles") if isinstance(data, dict) else None
        items = profiles if isinstance(profiles, list) else [data]
        for item in items:
            if isinstance(item, dict):
                output.append({**_compact_profile(item), "source_tool": result.tool_name})
    return output[:20]


def collect_project_context(tool_results: list[ToolResult]) -> list[dict[str, Any]]:
    """收集项目上下文并返回。"""
    projects: list[dict[str, Any]] = []
    for profile in collect_profile_context(tool_results):
        for project in profile.get("projects", []) or []:
            if isinstance(project, dict):
                projects.append(project)
    return projects[:50]


def collect_evidence_context(tool_results: list[ToolResult]) -> list[dict[str, Any]]:
    """收集证据上下文并返回。"""
    output: list[dict[str, Any]] = []
    for result in tool_results:
        if not result.ok or result.tool_name not in {"search_candidate_evidence", "build_comparison_pack", "rank_candidates", "hybrid_search_candidates"}:
            continue
        _collect_evidence_items(result.data, output, result.tool_name)
    return output[:80]


def collect_ranking_context(tool_results: list[ToolResult]) -> list[dict[str, Any]]:
    """收集排序上下文并返回。"""
    for result in tool_results:
        if result.ok and result.tool_name == "rank_candidates":
            data = _dump(result.data)
            if isinstance(data, list):
                return [_compact_ranking_item(item, index) for index, item in enumerate(data, start=1)]
    return []


def collect_comparison_context(tool_results: list[ToolResult]) -> dict[str, Any]:
    """收集比较上下文并返回。"""
    for result in tool_results:
        if result.ok and result.tool_name == "build_comparison_pack":
            data = _dump(result.data)
            return data if isinstance(data, dict) else {"data": data}
    return {}


def collect_business_limit_context(tool_results: list[ToolResult]) -> dict[str, Any]:
    """收集业务限制上下文并返回。"""
    for result in tool_results:
        if result.tool_name != "get_candidate_profiles_intro" or result.ok:
            continue
        data = _dump(result.data)
        if isinstance(data, dict) and data.get("error_code") == "profile_display_limit_exceeded":
            return {
                "error_code": data.get("error_code", ""),
                "limit": data.get("limit"),
                "requested_count": data.get("requested_count"),
                "candidate_names": data.get("candidate_names", []),
                "user_message": data.get("user_message", ""),
                "source": result.tool_name,
            }
    return {}


def collect_empty_flags(tool_results: list[ToolResult]) -> dict[str, str]:
    """收集空结果标记集合并返回。"""
    flags: dict[str, str] = {}
    for result in tool_results:
        if not result.ok:
            flags[f"{result.tool_name}.failed"] = result.error or "failed"
            continue
        data = _dump(result.data)
        if data in (None, [], {}):
            flags[f"{result.tool_name}.empty"] = "empty"
        if result.tool_name == "search_candidate_evidence" and _looks_empty_evidence(data):
            flags["evidence.empty"] = "empty"
    return flags


def collect_insufficient_info_reasons(tool_results: list[ToolResult]) -> list[str]:
    """收集信息不足info原因集合并返回。"""
    reasons: list[str] = []
    flags = collect_empty_flags(tool_results)
    if "evidence.empty" in flags:
        reasons.append("本轮 evidence 检索未返回明确证据，不能确认相关经历或项目。")
    for key, value in flags.items():
        if key.endswith(".failed"):
            reasons.append(f"{key.removesuffix('.failed')} 工具失败：{value}")
    return reasons


def _collect_candidate_items(value: Any, output: list[dict[str, Any]], source: str) -> None:
    """收集候选人条目集合并返回。"""
    value = _dump(value)
    if isinstance(value, dict):
        if "name" in value or "resume_identity" in value:
            output.append({"name": value.get("name", ""), "resume_identity": value.get("resume_identity", ""), "source": source})
        for item in value.values():
            _collect_candidate_items(item, output, source)
    elif isinstance(value, list):
        for item in value:
            _collect_candidate_items(item, output, source)


def _dedupe_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去重候选人集合并返回。"""
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = str(item.get("resume_identity") or item.get("name") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _collect_evidence_items(value: Any, output: list[dict[str, Any]], source: str) -> None:
    """收集证据条目集合并返回。"""
    value = _dump(value)
    if isinstance(value, dict):
        if {"evidence_id", "source_type", "project_title", "summary"} & set(value):
            output.append({**value, "source_tool": source})
        for item in value.values():
            _collect_evidence_items(item, output, source)
    elif isinstance(value, list):
        for item in value:
            _collect_evidence_items(item, output, source)


def _compact_profile(item: dict[str, Any]) -> dict[str, Any]:
    """精简候选人画像并返回。"""
    return {
        "name": item.get("name", ""),
        "resume_identity": item.get("resume_identity", ""),
        "domains": item.get("domains", []) or item.get("domain_tags", []),
        "skills": item.get("skills", []),
        "job_intent": item.get("job_intent", ""),
        "projects": item.get("projects", [])[:10] if isinstance(item.get("projects"), list) else [],
        "work": item.get("work", [])[:5] if isinstance(item.get("work"), list) else [],
    }


def _compact_ranking_item(item: Any, index: int) -> dict[str, Any]:
    """精简排序条目并返回。"""
    data = _dump(item)
    if not isinstance(data, dict):
        return {"rank": index, "value": data}
    return {
        "rank": index,
        "name": data.get("name", ""),
        "resume_identity": data.get("resume_identity", ""),
        "total_score": data.get("total_score"),
        "strengths": data.get("strengths", []),
        "risks": data.get("risks", []),
    }


def _looks_empty_evidence(data: Any) -> bool:
    """获取looks空结果证据并返回。"""
    if data in (None, [], {}):
        return True
    if isinstance(data, dict):
        return all(value in (None, [], {}) for value in data.values())
    return False


def _dump(value: Any) -> Any:
    """获取序列化结果并返回。"""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, list):
        return [_dump(item) for item in value]
    if isinstance(value, dict):
        return {key: _dump(item) for key, item in value.items()}
    return value
