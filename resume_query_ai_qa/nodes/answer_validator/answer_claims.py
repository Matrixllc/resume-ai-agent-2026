"""Answer claim and evidence-reference checks.

这个文件负责什么：
  校验结构化 claims、evidence refs，以及 count/ranking 这类可从文本中稳定扫描的
  answer.answer 事实。

应该从哪个函数读起：
  validate_claim_support()，再按 answer.py 中的调用顺序继续读。

不会负责什么：
  不做完整自然语言事实抽取；LLM answer 文本里的每一句事实不会在这里逐句核验。
"""

from __future__ import annotations

import re
from typing import List

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.inspection.plan_inspection import plan_intent_calls as _intent_calls
from resume_query_ai_qa.core.inspection.result_inspection import (
    candidate_names_from_results as _candidate_names_from_results,
    last_ok_data as _last_ok_data,
    names_from_last_candidate_list as _names_from_last_candidate_list,
)
from resume_query_ai_qa.core.schemas import AggregatedAnswer, QueryPlan, ToolResult, ValidationIssue
from resume_query_ai_qa.core.rules.evidence_policy import available_evidence_ids
from .issues import issue


def validate_claim_support(answer: AggregatedAnswer, tool_results: List[ToolResult]) -> List[ValidationIssue]:
    """检查每个非 other claim 是否指向本轮成功执行过的工具。"""
    issues: List[ValidationIssue] = []
    successful_tool_names = {item.tool_name for item in tool_results if item.ok}
    for claim in answer.claims:
        if claim.claim_type != "other" and not claim.supported_by:
            issues.append(issue("claim_support", "missing_claim_support", f"claim lacks support: {claim.text}"))
        unknown_support = [support for support in claim.supported_by if support not in successful_tool_names]
        if unknown_support:
            issues.append(issue("claim_support", "unknown_tool_support", f"claim references unknown tool support: {unknown_support}"))
    return issues


def validate_answer_count(answer: AggregatedAnswer, tool_results: List[ToolResult], config: ResumeQAConfig) -> List[ValidationIssue]:
    """用 count_candidates 校验 count claim，并有限扫描 answer 文本中的数量表达。"""
    count = _last_ok_data(tool_results, "count_candidates")
    if count is None:
        return []
    expected = int(count)
    count_claims = [claim for claim in answer.claims if claim.claim_type == "count"]
    for claim in count_claims:
        if claim.value is not None:
            try:
                if int(claim.value) != expected:
                    return [issue("count", "count_claim_value_mismatch", f"count claim value {claim.value!r} does not match tool count {expected}")]
                continue
            except (TypeError, ValueError):
                return [issue("count", "count_claim_value_invalid", f"count claim value {claim.value!r} is not an integer")]
        numbers = [int(item) for item in re.findall(r"\d+", claim.text)]
        if numbers and expected not in numbers:
            return [issue("count", "count_claim_text_mismatch", f"count claim {claim.text!r} does not match tool count {expected}")]
    answer_numbers = [int(item) for item in re.findall(r"(?<![\d.])\d+(?![\d.])", answer.answer)]
    if answer_numbers and expected not in answer_numbers:
        terms = [str(item) for item in list(dict(config.validation.get("answer", {}) or {}).get("count_subject_terms", []) or [])]
        if any(token in answer.answer for token in terms):
            return [issue("count", "answer_count_text_mismatch", f"answer count does not include tool count {expected}")]
    return []


def validate_answer_names(answer: AggregatedAnswer, tool_results: List[ToolResult]) -> List[ValidationIssue]:
    """检查 name/profile claims 中的候选人是否来自本轮工具结果。"""
    candidate_names = _candidate_names_from_results(tool_results)
    if not candidate_names:
        return []
    claimed_names = [
        claim.subject or claim.text
        for claim in answer.claims
        if claim.claim_type in {"name", "profile"}
    ]
    unknown = [name for name in claimed_names if name and name not in candidate_names]
    if unknown:
        return [issue("name", "unknown_candidate_name", f"answer claims unknown candidate names: {unknown}")]
    return []


def validate_answer_ranking(
    answer: AggregatedAnswer,
    tool_results: List[ToolResult],
    config: ResumeQAConfig,
    plan: QueryPlan | None = None,
) -> List[ValidationIssue]:
    """用 rank_candidates 校验 ranking claims，并检查 answer 文本中的姓名顺序。"""
    ranked = _last_ok_data(tool_results, "rank_candidates")
    if not ranked:
        return []
    limit = _ranking_output_limit(plan)
    scoped_ranked = ranked[:limit] if limit else ranked
    names = [str(getattr(item, "name", "") or getattr(item, "resume_identity", "") or "") for item in scoped_ranked]
    all_names = [str(getattr(item, "name", "") or getattr(item, "resume_identity", "") or "") for item in ranked]
    ranking_claims = [claim for claim in answer.claims if claim.claim_type == "ranking"]
    if ranking_claims:
        claim_positions: List[int] = []
        for claim in ranking_claims:
            subject = claim.subject or claim.text
            if subject not in all_names:
                return [issue("ranking", "ranking_unknown_candidate", f"ranking claim references unknown candidate: {subject}")]
            if limit and subject not in names:
                return [issue("ranking", "ranking_unexpected_candidate", f"ranking claim is outside requested top {limit}: {subject}")]
            rank_value = None
            if isinstance(claim.value, dict):
                rank_value = claim.value.get("rank")
                score_value = claim.value.get("score")
                ranked_item = ranked[all_names.index(subject)]
                if score_value is not None and float(score_value) != float(ranked_item.total_score):
                    return [issue("ranking", "ranking_score_mismatch", f"ranking score for {subject} differs from rank_candidates result")]
            if rank_value is not None and int(rank_value) != all_names.index(subject) + 1:
                return [issue("ranking", "ranking_rank_mismatch", f"ranking rank for {subject} differs from rank_candidates result")]
            claim_positions.append(all_names.index(subject))
        if claim_positions != sorted(claim_positions):
            return [issue("ranking", "ranking_claim_order_mismatch", "ranking claim order differs from rank_candidates result")]
    ranking_text = _ranking_answer_segment(answer.answer, config)
    positions = [ranking_text.find(name) for name in names if name]
    if any(position < 0 for position in positions):
        return [issue("ranking", "ranking_answer_missing_candidate", "ranking answer does not include every ranked candidate")]
    if positions != sorted(positions):
        return [issue("ranking", "ranking_answer_order_mismatch", "ranking answer order differs from rank_candidates result")]
    return []


def validate_answer_evidence_refs(answer: AggregatedAnswer, tool_results: List[ToolResult]) -> List[ValidationIssue]:
    """检查 used_evidence_refs 和 claim.evidence_ids 是否来自本轮 evidence 工具结果。"""
    allowed_ids = available_evidence_ids(tool_results)
    claim_ids = [
        evidence_id
        for claim in answer.claims
        for evidence_id in claim.evidence_ids
        if evidence_id
    ]
    unknown = [
        ref.evidence_id
        for ref in answer.used_evidence_refs
        if ref.evidence_id and ref.evidence_id not in allowed_ids
    ]
    unknown.extend(evidence_id for evidence_id in claim_ids if evidence_id not in allowed_ids)
    if unknown:
        return [issue("evidence_id", "unknown_evidence_ref", f"answer uses unknown evidence refs: {unknown}")]
    return []


def validate_required_structured_claims(
    answer: AggregatedAnswer,
    tool_results: List[ToolResult],
    plan: QueryPlan | None,
) -> List[ValidationIssue]:
    """根据 plan/tool_results 检查 count/name/ranking/comparison 等必需 claims。"""
    issues: List[ValidationIssue] = []
    claim_types = {claim.claim_type for claim in answer.claims}
    if _last_ok_data(tool_results, "count_candidates") is not None and "count" not in claim_types:
        issues.append(issue("required_claim", "missing_count_claim", "answer is missing structured count claim"))
    if plan is not None and "candidate_list" in [intent for intent, _calls in _intent_calls(plan)]:
        expected_names = _names_from_last_candidate_list(tool_results)
        claimed_names = {
            claim.subject or claim.text
            for claim in answer.claims
            if claim.claim_type == "name"
        }
        missing = [name for name in expected_names if name not in claimed_names]
        if missing:
            issues.append(issue("required_claim", "missing_name_claim", f"answer is missing structured name claims: {missing}"))
    ranked = _last_ok_data(tool_results, "rank_candidates")
    if ranked:
        limit = _ranking_output_limit(plan)
        scoped_ranked = ranked[:limit] if limit else ranked
        ranked_names = [str(getattr(item, "name", "") or getattr(item, "resume_identity", "") or "") for item in scoped_ranked]
        claimed_ranked = [
            claim.subject or claim.text
            for claim in answer.claims
            if claim.claim_type == "ranking"
        ]
        missing = [name for name in ranked_names if name and name not in claimed_ranked]
        if missing:
            issues.append(issue("required_claim", "missing_ranking_claim", f"answer is missing structured ranking claims: {missing}"))
    comparison = _last_ok_data(tool_results, "build_comparison_pack")
    if isinstance(comparison, dict):
        briefs = comparison.get("briefs") or []
        expected = [
            str(item.get("name") or item.get("resume_identity") or "")
            for item in briefs
            if isinstance(item, dict)
        ]
        claimed = [
            claim.subject or claim.text
            for claim in answer.claims
            if claim.claim_type == "comparison"
        ]
        missing = [name for name in expected if name and name not in claimed]
        if missing:
            issues.append(issue("required_claim", "missing_comparison_claim", f"answer is missing structured comparison claims: {missing}"))
    return issues


def _ranking_output_limit(plan: QueryPlan | None) -> int | None:
    """Read requested TopK ranking limit from plan constraints."""
    if plan is None:
        return None
    try:
        limit = int(getattr(plan.constraints, "ranking_output_limit", None) or 0)
    except (TypeError, ValueError):
        return None
    return limit if limit > 0 else None


def _ranking_answer_segment(answer_text: str, config: ResumeQAConfig) -> str:
    """用 YAML markers 定位排序段；没有 marker 时返回全文。"""
    markers = [str(item) for item in list(dict(config.validation.get("answer", {}) or {}).get("ranking_segment_markers", []) or [])]
    starts = [answer_text.find(marker) for marker in markers if answer_text.find(marker) >= 0]
    if not starts:
        return answer_text
    return answer_text[min(starts):]


__all__ = [
    "validate_answer_count",
    "validate_answer_evidence_refs",
    "validate_answer_names",
    "validate_answer_ranking",
    "validate_claim_support",
    "validate_required_structured_claims",
]
