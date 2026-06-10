from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.inspection.result_inspection import normalize_string_list
from resume_query_ai_qa.core.schemas import ContextPolicy


def resolve_context_policy(
    text: str,
    router_rules: dict[str, Any] | None = None,
    *,
    excluded_ref_types: set[str] | None = None,
) -> ContextPolicy:
    """解析上下文策略并返回。"""
    question = str(text or "")
    references = context_reference_rules(router_rules)
    excluded = excluded_ref_types or set()
    for ref_type, payload_raw in references.items():
        if ref_type in excluded:
            continue
        payload = dict(payload_raw or {})
        terms = [str(item) for item in payload.get("terms", []) or [] if str(item).strip()]
        evidence = [term for term in terms if term.lower() in question.lower()]
        if evidence:
            return ContextPolicy(
                uses_context=True,
                context_ref_type=ref_type,  # type: ignore[arg-type]
                evidence=evidence,
                reason=str(payload.get("reason") or "当前问题依赖上一轮上下文。"),
            )
    return ContextPolicy(
        uses_context=False,
        context_ref_type="none",
        evidence=[],
        reason="当前问题没有明确上下文指代表达，不需要继承上一轮上下文。",
    )


def context_reference_rules(router_rules: dict[str, Any] | None = None) -> dict[str, Any]:
    """获取上下文指代规则，优先读取新规则配置并兼容旧配置。"""
    rules = dict(router_rules or {})
    configured = dict(rules.get("context_ref_rules", {}) or {})
    if configured:
        return configured
    return dict(rules.get("context_references", {}) or {})


def required_context_keys_for_ref_type(ref_type: str, router_rules: dict[str, Any] | None = None) -> list[str]:
    """读取某类上下文指代需要的 session key。"""
    payload = dict(context_reference_rules(router_rules).get(str(ref_type), {}) or {})
    return [str(item) for item in list(payload.get("required_keys", []) or []) if str(item).strip()]


def has_required_context(ref_type: str, session_context: dict[str, Any] | None, router_rules: dict[str, Any] | None = None) -> bool:
    """判断 session_context 是否满足配置化上下文依赖。"""
    context = session_context or {}
    required = required_context_keys_for_ref_type(ref_type, router_rules)
    if required:
        return all(_context_value_present(context.get(key)) for key in required)
    if ref_type == "candidate_pool":
        return bool(normalize_string_list(context.get("last_candidate_pool_ids")))
    if ref_type == "last_candidate":
        return bool(str(context.get("last_candidate_id", "") or "").strip())
    if ref_type in {"ranking_top", "ranking_top_k"}:
        return bool(normalize_string_list(context.get("last_ranking_candidate_ids")))
    if ref_type == "comparison_pair":
        return len(normalize_string_list(context.get("last_comparison_candidate_ids"))) >= 2
    if ref_type == "jd":
        return _context_value_present(context.get("last_jd_criteria"))
    return True


def candidate_ids_for_context(policy: ContextPolicy, session_context: dict[str, Any] | None) -> list[str]:
    """根据上下文生成候选人标识集合并返回。"""
    if not policy.uses_context:
        return []
    context = session_context or {}
    ref_type = policy.context_ref_type
    if ref_type == "candidate_pool":
        return normalize_string_list(context.get("last_candidate_pool_ids"))
    if ref_type == "last_candidate":
        focused = str(context.get("last_candidate_id", "") or "").strip()
        return [focused] if focused else []
    if ref_type == "ranking_top":
        return _slice_context_ids(ref_type, normalize_string_list(context.get("last_ranking_candidate_ids")))
    if ref_type == "ranking_top_k":
        return _slice_context_ids(ref_type, normalize_string_list(context.get("last_ranking_candidate_ids")))
    if ref_type == "comparison_pair":
        return normalize_string_list(context.get("last_comparison_candidate_ids"))
    if ref_type == "ambiguous":
        return _fallback_candidate_ids(context)
    return []


def jd_criteria_for_context(policy: ContextPolicy, session_context: dict[str, Any] | None) -> dict[str, Any]:
    """根据上下文生成JD评分标准并返回。"""
    if not policy.uses_context or policy.context_ref_type != "jd":
        return {}
    value = (session_context or {}).get("last_jd_criteria")
    return value if isinstance(value, dict) else {}


def _fallback_candidate_ids(context: dict[str, Any]) -> list[str]:
    """获取兜底候选人标识集合并返回。"""
    for key in ("last_candidate_pool_ids", "last_ranking_candidate_ids", "last_comparison_candidate_ids"):
        values = normalize_string_list(context.get(key))
        if values:
            return values
    focused = str(context.get("last_candidate_id", "") or "").strip()
    return [focused] if focused else []


def _slice_context_ids(ref_type: str, ids: list[str]) -> list[str]:
    """按配置化 candidate_slice 截取上下文候选集合。"""
    from resume_query_ai_qa.core.config import load_config

    payload = dict(context_reference_rules(load_config().router_rules).get(str(ref_type), {}) or {})
    raw_slice = list(payload.get("candidate_slice", []) or [])
    if len(raw_slice) != 2:
        return ids[:1] if ref_type == "ranking_top" else ids[:3]
    try:
        start = max(0, int(raw_slice[0]))
        end = max(start, int(raw_slice[1]))
    except (TypeError, ValueError):
        return ids[:1] if ref_type == "ranking_top" else ids[:3]
    return ids[start:end]


def _context_value_present(value: Any) -> bool:
    """判断上下文字段是否存在有效内容。"""
    if isinstance(value, list):
        return bool(normalize_string_list(value))
    if isinstance(value, dict):
        return bool(value)
    return bool(str(value or "").strip())
