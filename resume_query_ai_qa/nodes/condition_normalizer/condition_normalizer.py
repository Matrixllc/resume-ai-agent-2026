"""Normalize router conditions before execution policy and planning."""

from __future__ import annotations

from resume_query_ai_qa.core.rules.condition_rules import (
    extract_conditions,
    mark_preference_targets,
    normalize_conditions,
)
from resume_query_ai_qa.nodes.router.signals import candidate_reference_conditions
from resume_query_ai_qa.core.schemas import NormalizedCondition, QueryCondition, RouterOutput


CONTEXT_COLLECTION_REF_TYPES = {"ranking_top", "ranking_top_k", "candidate_pool", "comparison_pair"}


def normalize_router_output(router_output: RouterOutput, question: str) -> RouterOutput:
    """补齐缺失条件，并附加稳定的归一化形式。"""
    if router_output.intent == "out_of_scope":
        return router_output.model_copy(update={"conditions": [], "normalized_conditions": []})
    conditions = list(router_output.conditions or [])
    if not conditions:
        conditions = extract_conditions(question)
    conditions = _merge_candidate_reference_conditions(conditions, question)
    normalized = mark_preference_targets(normalize_conditions(conditions), question)
    conditions = _drop_context_reference_candidate_names(conditions, router_output)
    normalized = _drop_context_reference_candidate_names(normalized, router_output)
    return router_output.model_copy(
        update={
            "conditions": conditions,
            "normalized_conditions": normalized,
        }
    )


def _merge_candidate_reference_conditions(conditions: list[QueryCondition], question: str) -> list[QueryCondition]:
    """把显式候选人姓名补成候选人条件，避免 LLM 漏填 conditions。"""
    existing = {(item.type, item.raw_value) for item in conditions}
    additions = [item for item in candidate_reference_conditions(question) if (item.type, item.raw_value) not in existing]
    return [*conditions, *additions]


def _drop_context_reference_candidate_names(
    conditions: list[QueryCondition] | list[NormalizedCondition],
    router_output: RouterOutput,
) -> list[QueryCondition] | list[NormalizedCondition]:
    """移除把上下文指代词误抽成候选人的条件。"""
    policy = router_output.context_policy
    if not policy.uses_context or policy.context_ref_type not in CONTEXT_COLLECTION_REF_TYPES:
        return conditions
    context_terms = {str(item).strip() for item in policy.evidence if str(item).strip()}
    if not context_terms:
        return conditions
    return [
        condition
        for condition in conditions
        if condition.type != "candidate_name" or not _is_context_reference_candidate(condition, context_terms)
    ]


def _is_context_reference_candidate(condition: QueryCondition | NormalizedCondition, context_terms: set[str]) -> bool:
    """判断候选人条件是否只是“前三名/这些人”等上下文引用。"""
    values = {
        str(getattr(condition, "raw_value", "") or "").strip(),
        str(getattr(condition, "normalized_value", "") or "").strip(),
        str(getattr(condition, "evidence", "") or "").strip(),
    }
    values = {value for value in values if value}
    if any(_contains_known_candidate_name(value) for value in values):
        return False
    return any(_contains_context_term_only(value, context_terms) for value in values)


def _contains_context_term_only(value: str, context_terms: set[str]) -> bool:
    """上下文词加少量语气/连接词时，不视为真实候选人名。"""
    for term in context_terms:
        if term and term in value and len(value.replace(term, "")) <= 4:
            return True
    return False


def _contains_known_candidate_name(value: str) -> bool:
    """判断文本中是否含有真实候选人姓名。"""
    from resume_query_ai_qa.core.data_access import list_known_candidate_names

    return any(name and name in value for name in list_known_candidate_names())
