"""Read-only tool result and candidate payload inspection helpers."""

from __future__ import annotations

from typing import Any, List

from resume_query_ai_qa.core.schemas import CandidateBrief, ToolResult


def normalize_string_list(value: Any) -> List[str]:
    """标准化字符串列表并返回。"""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def last_ok_data(tool_results: List[ToolResult], tool_name: str):
    """获取最近OK数据并返回。"""
    for result in reversed(tool_results):
        if result.ok and result.tool_name == tool_name:
            return result.data
    return None


def candidate_ids_from_data(data: Any) -> List[str]:
    """从数据提取候选人标识集合并返回。"""
    ids: List[str] = []
    if isinstance(data, CandidateBrief):
        return [data.resume_identity] if data.resume_identity else []
    if hasattr(data, "resume_identity"):
        value = str(getattr(data, "resume_identity", "") or "").strip()
        return [value] if value else []
    if hasattr(data, "model_dump"):
        return candidate_ids_from_data(data.model_dump())
    if isinstance(data, dict):
        for key in ["resume_identity", "candidate_id"]:
            value = str(data.get(key, "") or "").strip()
            if value:
                ids.append(value)
        raw_ids = data.get("candidate_ids")
        if isinstance(raw_ids, list):
            ids.extend(str(item).strip() for item in raw_ids if str(item).strip())
        for value in data.values():
            if isinstance(value, (dict, list)) or hasattr(value, "model_dump"):
                ids.extend(candidate_ids_from_data(value))
    elif isinstance(data, list):
        for item in data:
            ids.extend(candidate_ids_from_data(item))
    return list(dict.fromkeys(ids))


def resolved_candidate_ids(tool_results: List[ToolResult]) -> set[str]:
    """从工具结果中提取已解析候选人标识并返回。"""
    ids: set[str] = set()
    for result in tool_results:
        if result.ok and result.tool_name == "resolve_candidate_reference":
            ids.update(candidate_ids_from_data(result.data))
            if isinstance(result.data, dict):
                ids.update(str(item).strip() for item in result.data.get("candidate_ids", []) if str(item).strip())
    return ids


def profile_candidate_ids(tool_results: List[ToolResult]) -> set[str]:
    """获取候选人画像候选人标识集合并返回。"""
    ids: set[str] = set()
    for result in tool_results:
        if result.ok and result.tool_name in {"get_candidate_profile_intro", "get_candidate_profiles_intro", "get_candidate_brief"}:
            ids.update(candidate_ids_from_data(result.data))
    return ids


def ranked_candidate_ids(tool_results: List[ToolResult]) -> set[str]:
    """获取ranked候选人标识集合并返回。"""
    ids: set[str] = set()
    for result in tool_results:
        if result.ok and result.tool_name == "rank_candidates":
            ids.update(candidate_ids_from_data(result.data))
    return ids


def last_candidate_list_before_count(tool_results: List[ToolResult]) -> List[CandidateBrief] | None:
    """获取最近候选人列表before数量并返回。"""
    latest: List[CandidateBrief] | None = None
    for result in tool_results:
        if result.ok and result.tool_name in {"filter_candidates", "list_all_candidates", "hybrid_search_candidates"} and isinstance(result.data, list):
            latest = result.data
        if result.ok and result.tool_name == "count_candidates":
            return latest
    return latest


def names_from_last_candidate_list(tool_results: List[ToolResult]) -> List[str]:
    """从最近候选人列表提取名称集合并返回。"""
    latest: List[CandidateBrief] | None = None
    for result in tool_results:
        if result.ok and result.tool_name in {"filter_candidates", "list_all_candidates", "hybrid_search_candidates"} and isinstance(result.data, list):
            latest = result.data
    if latest is None:
        return []
    return [candidate_name(item) for item in latest if candidate_name(item)]


def candidate_name(value: Any) -> str:
    """获取候选人名称并返回。"""
    if isinstance(value, CandidateBrief):
        return value.name
    if hasattr(value, "name"):
        return str(getattr(value, "name", "") or "")
    if hasattr(value, "model_dump"):
        return candidate_name(value.model_dump())
    if isinstance(value, dict):
        return str(value.get("name") or (value.get("brief") or {}).get("name") or "")
    return ""


def candidate_names_from_results(tool_results: List[ToolResult]) -> set[str]:
    """从结果集合提取候选人名称集合并返回。"""
    names: set[str] = set()
    for result in tool_results:
        if not result.ok:
            continue
        names.update(extract_candidate_names(result.data))
    return {name for name in names if name}


def extract_candidate_names(value: Any) -> set[str]:
    """提取候选人名称集合并返回。"""
    names: set[str] = set()
    if isinstance(value, CandidateBrief):
        names.add(value.name)
    elif hasattr(value, "name"):
        name = getattr(value, "name", "")
        if name:
            names.add(str(name))
    elif hasattr(value, "model_dump"):
        names.update(extract_candidate_names(value.model_dump()))
    elif isinstance(value, dict):
        if value.get("name"):
            names.add(str(value["name"]))
        if value.get("candidate_name"):
            names.add(str(value["candidate_name"]))
        for item in value.values():
            names.update(extract_candidate_names(item))
    elif isinstance(value, list):
        for item in value:
            names.update(extract_candidate_names(item))
    return names
