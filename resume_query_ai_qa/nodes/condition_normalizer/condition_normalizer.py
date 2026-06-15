"""Normalize router conditions before execution policy and planning.

Read this file after README.md and CONDITION_FLOW.md. This node only converts
raw RouterOutput.conditions into stable RouterOutput.normalized_conditions.

It does not change intent, scenario_decisions, tool policy, or answer content.
Those decisions belong to router, execution_policy, planner/compiler, and
aggregator.

中文阅读提示：
这个节点只做 raw conditions -> normalized_conditions。router 已经判断了
intent/scenario/context；这里负责把 domain/skill/concept/major/scope/
candidate_name 标准化成后续节点可稳定消费的条件。
"""

from __future__ import annotations

from resume_query_ai_qa.core.rules.condition_rules import (
    extract_conditions,
    mark_preference_targets,
    normalize_conditions,
)
from resume_query_ai_qa.core.rules.candidate_mentions import COLLECTION_QUANTIFIER_TERMS
from resume_query_ai_qa.nodes.router.signals import candidate_reference_conditions
from resume_query_ai_qa.core.schemas import NormalizedCondition, QueryCondition, RouterOutput


CONTEXT_COLLECTION_REF_TYPES = {"ranking_top", "ranking_top_k", "candidate_pool", "comparison_pair"}


def normalize_router_output(router_output: RouterOutput, question: str) -> RouterOutput:
    """Complete raw conditions and attach normalized conditions.

    Inputs:
    - router_output: output from router, with raw conditions and context_policy.
    - question: original user question, used for condition fallback and
      preference-target marking.

    Output:
    - a copied RouterOutput with updated conditions and normalized_conditions.

    中文：
    主入口。补 raw conditions，合并显式候选人名，归一化条件，标记偏好目标，
    并删除被误抽成 candidate_name 的上下文指代词。
    """
    if router_output.intent == "out_of_scope":
        return router_output.model_copy(update={"conditions": [], "normalized_conditions": []})
    conditions = list(router_output.conditions or [])
    if not conditions:
        conditions = extract_conditions(question)
    conditions = _merge_candidate_reference_conditions(conditions, question)
    normalized = mark_preference_targets(normalize_conditions(conditions), question)
    conditions = _drop_context_reference_candidate_names(conditions, router_output)
    normalized = _drop_context_reference_candidate_names(normalized, router_output)
    conditions = _drop_collection_quantifier_candidate_names(conditions)
    normalized = _drop_collection_quantifier_candidate_names(normalized)
    return router_output.model_copy(
        update={
            "conditions": conditions,
            "normalized_conditions": normalized,
        }
    )


def _drop_collection_quantifier_candidate_names(
    conditions: list[QueryCondition] | list[NormalizedCondition],
) -> list[QueryCondition] | list[NormalizedCondition]:
    """Drop per-person/list words that were mistaken as candidate names."""
    return [
        condition
        for condition in conditions
        if condition.type != "candidate_name" or not _is_collection_quantifier_candidate(condition)
    ]


def _is_collection_quantifier_candidate(condition: QueryCondition | NormalizedCondition) -> bool:
    """Return true when a candidate_name value is only a collection quantifier."""
    values = {
        str(getattr(condition, "raw_value", "") or "").strip(),
        str(getattr(condition, "normalized_value", "") or "").strip(),
        str(getattr(condition, "evidence", "") or "").strip(),
    }
    values = {value for value in values if value}
    if any(_contains_known_candidate_name(value) for value in values):
        return False
    quantifiers = {_normalize_candidate_quantifier(term) for term in COLLECTION_QUANTIFIER_TERMS}
    return any(_normalize_candidate_quantifier(value) in quantifiers for value in values)


def _merge_candidate_reference_conditions(conditions: list[QueryCondition], question: str) -> list[QueryCondition]:
    """Merge explicit candidate names into raw candidate_name conditions.

    中文：
    候选人姓名不走 taxonomy。这里把当前问题里显式出现的候选人补成
    candidate_name，避免 router/LLM 漏填。
    """
    existing = {(item.type, item.raw_value) for item in conditions}
    additions = [item for item in candidate_reference_conditions(question) if (item.type, item.raw_value) not in existing]
    return [*conditions, *additions]


def _drop_context_reference_candidate_names(
    conditions: list[QueryCondition] | list[NormalizedCondition],
    router_output: RouterOutput,
) -> list[QueryCondition] | list[NormalizedCondition]:
    """Drop context reference words that were mistaken as candidate names.

    中文：
    “第一名/这些人/这两个人”应由 context_policy 解析，不应该作为真实
    candidate_name condition 继续传给后续节点。
    """
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
    """Return true when a candidate_name condition is only a context reference.

    中文：
    如果条件里包含真实候选人姓名，就保留；如果只是上下文词加少量语气词，
    就认为它不是候选人名。
    """
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
    """Return true for context terms plus a few filler/connector characters.

    中文：
    例如“第一名”“第一名的”“这些人里”，都不是候选人姓名。
    """
    for term in context_terms:
        if term and term in value and len(value.replace(term, "")) <= 4:
            return True
    return False


def _contains_known_candidate_name(value: str) -> bool:
    """Return true when text contains a known candidate name from data access.

    中文：
    通过数据层候选人名单判断是否真有候选人姓名，防止误删真实 candidate_name。
    """
    from resume_query_ai_qa.core.data_access import list_known_candidate_names

    return any(name and name in value for name in list_known_candidate_names())


def _normalize_candidate_quantifier(value: str) -> str:
    """Normalize a collection quantifier candidate-name fragment."""
    return value.strip(" ，,。；;:：?？的")
