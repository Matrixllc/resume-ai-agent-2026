"""Evidence selection and coverage helpers.

Evidence policy is deterministic. It only inspects tool outputs and the
YAML-driven requirements; it never asks an LLM to decide whether a claim is
supported.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.schemas import EvidenceRef, QueryPlan, ToolResult


def required_evidence_policy(plan: QueryPlan, config: ResumeQAConfig | None = None) -> dict[str, Any]:
    """返回计划中所有意图共同要求的最严格证据策略。"""
    cfg = config or load_config()
    policies = dict(cfg.evidence_policy.get("intents", {}) or {})
    requirements: dict[str, Any] = {
        "requires_evidence": False,
        "min_evidence_per_candidate": 0,
        "requires_scoring_table": False,
        "hide_contact_by_default": True,
        "intents": [],
    }
    for intent in _plan_intents(plan):
        policy = dict(policies.get(intent, {}) or {})
        requirements["intents"].append(intent)
        requirements["requires_evidence"] = bool(
            requirements["requires_evidence"] or policy.get("requires_evidence", False)
        )
        requirements["requires_scoring_table"] = bool(
            requirements["requires_scoring_table"] or policy.get("requires_scoring_table", False)
        )
        requirements["hide_contact_by_default"] = bool(
            requirements["hide_contact_by_default"] and policy.get("hide_contact_by_default", True)
        )
        requirements["min_evidence_per_candidate"] = max(
            int(requirements["min_evidence_per_candidate"] or 0),
            int(policy.get("min_evidence_per_candidate", 0) or 0),
        )
    return requirements


def collect_evidence_refs(tool_results: Iterable[ToolResult]) -> list[EvidenceRef]:
    """从嵌套工具输出中提取证据引用对象。"""
    refs: list[EvidenceRef] = []
    for result in tool_results:
        if result.ok:
            refs.extend(_extract_evidence_refs(result.data))
    return refs


def available_evidence_ids(tool_results: Iterable[ToolResult]) -> set[str]:
    """获取可用项证据标识集合并返回。"""
    return {ref.evidence_id for ref in collect_evidence_refs(tool_results) if ref.evidence_id}


def validate_evidence_coverage(
    *,
    plan: QueryPlan,
    tool_results: list[ToolResult],
    config: ResumeQAConfig | None = None,
) -> tuple[list[str], list[str]]:
    """校验 YAML 策略要求的最低证据覆盖率。"""
    requirements = required_evidence_policy(plan, config)
    if not requirements["requires_evidence"]:
        return [], []
    if _allows_evidence_optional_recall(plan, tool_results):
        return [], []

    refs = collect_evidence_refs(tool_results)
    warnings: list[str] = []
    errors: list[str] = []
    if not refs:
        if any(result.ok and result.tool_name == "search_candidate_evidence" for result in tool_results):
            warnings.append("evidence search returned no matching EvidenceRef")
            return errors, warnings
        errors.append("evidence-required intent has no EvidenceRef in tool results")
        return errors, warnings

    min_per_candidate = int(requirements["min_evidence_per_candidate"] or 0)
    if min_per_candidate > 0:
        counts: dict[str, int] = defaultdict(int)
        for ref in refs:
            if ref.resume_identity:
                counts[ref.resume_identity] += 1
        target_ids = candidate_ids_requiring_evidence(plan, tool_results)
        for candidate_id in target_ids:
            if counts.get(candidate_id, 0) < min_per_candidate:
                errors.append(
                    f"candidate {candidate_id} has {counts.get(candidate_id, 0)} evidence refs, "
                    f"requires {min_per_candidate}"
                )
    weak = [ref for ref in refs if ref.strength < 50]
    if weak:
        warnings.append(f"{len(weak)} weak evidence refs below strength 50")
    return errors, warnings


def candidate_ids_requiring_evidence(plan: QueryPlan, tool_results: list[ToolResult]) -> set[str]:
    """推断回答中需要证据覆盖的候选人。"""
    intents = set(_plan_intents(plan))
    target_ids: set[str] = set()
    if "candidate_compare_pair" in intents:
        for result in tool_results:
            if result.tool_name == "build_comparison_pack" and result.ok and isinstance(result.data, dict):
                target_ids.update(str(item) for item in result.data.get("candidate_ids", []) if str(item).strip())
    if "candidate_profile_intro" in intents:
        for result in tool_results:
            if result.tool_name == "get_candidate_profile_intro" and result.ok and isinstance(result.data, dict):
                candidate_id = str(result.data.get("resume_identity", "") or "").strip()
                if candidate_id:
                    target_ids.add(candidate_id)
    if "candidate_ranking" in intents or "jd_scoring" in intents:
        for result in tool_results:
            if result.tool_name == "rank_candidates" and result.ok:
                for item in result.data or []:
                    candidate_id = str(getattr(item, "resume_identity", "") or "").strip()
                    if candidate_id:
                        target_ids.add(candidate_id)
    if not target_ids:
        for ref in collect_evidence_refs(tool_results):
            if ref.resume_identity:
                target_ids.add(ref.resume_identity)
    return target_ids


def _plan_intents(plan: QueryPlan) -> list[str]:
    """获取计划意图集合并返回。"""
    if plan.intent == "compound":
        return [sub_task.intent for sub_task in plan.sub_tasks]
    return [plan.intent]


def _allows_evidence_optional_recall(plan: QueryPlan, tool_results: list[ToolResult]) -> bool:
    """判断证据可选召回是否成立并返回布尔值。"""
    intents = set(_plan_intents(plan))
    if "candidate_filter" not in intents and "candidate_list" not in intents:
        return False
    return any(result.ok and result.tool_name in {"filter_candidates", "hybrid_search_candidates"} for result in tool_results)


def _extract_evidence_refs(value: Any) -> list[EvidenceRef]:
    """提取证据引用集合并返回。"""
    if isinstance(value, EvidenceRef):
        return [value]
    if hasattr(value, "evidence_refs"):
        return _extract_evidence_refs(getattr(value, "evidence_refs"))
    if hasattr(value, "model_dump"):
        return _extract_evidence_refs(value.model_dump())
    if isinstance(value, dict):
        refs: list[EvidenceRef] = []
        if _looks_like_evidence_ref(value):
            try:
                refs.append(EvidenceRef.model_validate(value))
            except Exception:
                # 单条证据引用格式异常时跳过该条，继续提取同一结果里的其他证据。
                _ = value
        for nested in value.values():
            refs.extend(_extract_evidence_refs(nested))
        return refs
    if isinstance(value, list):
        refs: list[EvidenceRef] = []
        for item in value:
            refs.extend(_extract_evidence_refs(item))
        return refs
    return []


def _looks_like_evidence_ref(value: dict[str, Any]) -> bool:
    """判断证据引用是否成立并返回布尔值。"""
    return "source_type" in value and (
        "evidence_id" in value or "resume_identity" in value or "candidate_name" in value
    )
