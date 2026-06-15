"""Router text signal detection.

Read this file after rules.py. It is the scout layer: it inspects question text,
conditions, candidate mentions, and router_rules.yaml terms to produce
RouterSignals.

This module does not generate RouterOutput and does not decide final intent.
rules.py is the decision layer that turns these signals into draft intents.

中文阅读提示：
这个文件是“侦察层”。它只回答：文本里有没有候选人、是否像两人对比、
是否像排序、是否引用上下文、是否含敏感面试词。它不产 RouterOutput，
也不决定最终 intent；rules.py 才把这些信号变成草稿 intent。
"""

from __future__ import annotations

import re
from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.rules.candidate_mentions import extract_candidate_mentions
from resume_query_ai_qa.core.rules.context_resolver import context_reference_rules, resolve_context_policy
from resume_query_ai_qa.core.schemas import ContextPolicy, QueryCondition
from resume_query_ai_qa.nodes.router.rule_types import RouterSignals


def detect_router_signals(text: str, conditions: list[QueryCondition], config: ResumeQAConfig) -> RouterSignals:
    """Detect all signals needed by rule fallback and guard stages.

    中文：
    信号检测总入口。输出 RouterSignals，供 rules.py 的 handler 和 guard.py 的硬规则复用。
    """
    context_policy = resolve_context_policy(text, config.router_rules)
    resolution = dict(config.router_rules.get("context_resolution", {}) or {})
    explicit_override_types = {str(item) for item in list(resolution.get("explicit_candidates_override_ref_types", []) or [])}
    candidate_reference = looks_like_candidate_reference(text)
    if (
        candidate_reference
        and context_policy.uses_context
        and context_policy.context_ref_type in explicit_override_types
        and explicit_candidate_match_count(text) >= 2
    ):
        context_policy = ContextPolicy(reason="当前问题已显式给出多个候选人；本句复数指代绑定到显式候选人，不依赖上一轮上下文。")
    has_domain_scope = any(condition.type in {"domain", "major", "skill", "concept", "job_intent"} for condition in conditions)
    has_collection_request = contains_any(text, terms(config, "signals", "collection_request_terms"))
    has_per_person_request = contains_any(text, terms(config, "signals", "per_person_terms"))
    has_project_request = contains_any(text, terms(config, "signals", "project_terms"))
    return RouterSignals(
        pair_compare=looks_like_pair_compare(text, config),
        candidate_reference=candidate_reference,
        context_policy=context_policy,
        context_single_reference=context_policy.context_ref_type in {str(item) for item in list(resolution.get("single_candidate_ref_types", []) or [])},
        context_pair_reference=context_policy.context_ref_type in {str(item) for item in list(resolution.get("pair_ref_types", []) or [])},
        context_pool_reference=context_policy.context_ref_type in {str(item) for item in list(resolution.get("pool_ref_types", []) or [])},
        discovery=contains_any(text, terms(config, "signals", "discovery_terms")),
        project_listing=has_project_request,
        evidence_locator=contains_any(text, terms(config, "intent_rules", "evidence_question", "trigger_any")),
        domain_scope=has_domain_scope,
        collection_request=has_collection_request,
        per_person_request=has_per_person_request,
        scoped_project_evidence_request=bool(
            has_domain_scope and has_collection_request and has_per_person_request and has_project_request
        ),
        single_candidate_fit=looks_like_single_candidate_fit_question(text, config),
        context_pool_priority=context_policy.context_ref_type == "candidate_pool"
        and looks_like_context_pool_priority_question(text, config),
        interview_question=contains_any(text, terms(config, "intent_rules", "interview_question_generation", "trigger_any")),
        sensitive_interview=contains_sensitive_interview_terms(text, config),
    )


def looks_like_pair_compare(text: str, config: ResumeQAConfig | None = None) -> bool:
    """Return true when text asks for exactly-two-candidate comparison.

    中文：
    判断是否像“两个人之间的对比”。如果显式候选人数量达到多人排序阈值，
    就不当成 pair compare。
    """
    cfg = config or load_config()
    ranking_rules = dict(cfg.router_rules.get("ranking_intent_rules", {}) or {})
    min_count = int(ranking_rules.get("force_ranking_over_compare_for_min_candidates", 3) or 3)
    if explicit_candidate_match_count(text) >= min_count:
        return False
    if contains_any(text, terms(cfg, "pair_compare", "explicit_terms")):
        return True
    if contains_any(text, terms(cfg, "pair_compare", "generic_compare_terms")) and not contains_any(text, terms(cfg, "pair_compare", "compare_word_exclude_terms")):
        return True
    has_pair_connector = contains_any(text, terms(cfg, "pair_compare", "connectors"))
    if has_pair_connector and contains_any(text, terms(cfg, "pair_compare", "compare_terms")):
        return not contains_any(text, terms(cfg, "pair_compare", "ranking_exclude_terms"))
    return False


def looks_like_candidate_reference(text: str) -> bool:
    """Return true when text contains an explicit known candidate mention.

    中文：
    判断文本里是否直接出现已知候选人名字。
    """
    return bool(candidate_mentions(text))


def looks_like_ranking_request(text: str, config: ResumeQAConfig) -> bool:
    """Return true when text asks for ranking/recommendation.

    中文：
    判断是否在问排序、推荐、最强、第一名等候选人集合优先级问题。
    """
    return matches_current_turn_output(text, config, "candidate_ranking") or contains_any(
        text,
        terms(config, "intent_rules", "candidate_ranking", "trigger_any")
        + terms(config, "compound_rules", "ranking_terms"),
    )


def looks_like_single_candidate_fit_question(text: str, config: ResumeQAConfig) -> bool:
    """Return true when one explicit candidate is being assessed for fit.

    中文：
    判断是否是“某个候选人适不适合某方向/岗位”的单人适配问题。
    """
    if not looks_like_candidate_reference(text):
        return False
    fit_terms = terms(config, "signals", "fit_terms")
    target_terms = "|".join(re.escape(item) for item in terms(config, "signals", "fit_target_terms"))
    relation_terms = "|".join(re.escape(item) for item in terms(config, "signals", "fit_relation_terms"))
    return contains_any(text, fit_terms) or bool(target_terms and relation_terms and re.search(rf"({relation_terms}).{{0,8}}({target_terms})", text))


def looks_like_context_pool_priority_question(text: str, config: ResumeQAConfig) -> bool:
    """Return true when a context candidate pool is being prioritized/ranked.

    中文：
    判断“这些人里谁更强/谁更适合”这种基于上一轮候选池的排序问题。
    """
    if not contains_any(text, terms(config, "signals", "question_subject_terms")):
        return False
    return contains_any(text, terms(config, "signals", "context_pool_priority_terms"))


def is_resume_domain_question(
    text: str,
    conditions: list[QueryCondition],
    signals: RouterSignals,
    config: ResumeQAConfig,
) -> bool:
    """Return true when the question belongs to resume/candidate search domain.

    中文：
    判断问题是否属于简历/候选人问答范围。非范围问题会被 rules.py 转为 out_of_scope。
    """
    if not text.strip():
        return False
    if signals.context_policy.uses_context or signals.candidate_reference or signals.pair_compare:
        return True
    if contains_any(text, terms(config, "resume_domain", "resume_terms")):
        return True
    if any(condition.type in {"domain", "skill", "concept", "keyword", "major", "job_intent"} for condition in conditions):
        return contains_any(text, terms(config, "resume_domain", "taxonomy_search_required_terms"))
    return contains_any(text, terms(config, "resume_domain", "count_terms")) and contains_any(
        text, terms(config, "resume_domain", "count_people_terms")
    )


def candidate_reference_conditions(text: str) -> list[QueryCondition]:
    """Convert explicit candidate mentions into candidate_name conditions.

    中文：
    把候选人名字转成 candidate_name 条件，方便后续条件归一化和工具参数绑定。
    """
    return [
        QueryCondition(type="candidate_name", raw_value=mention, evidence=mention, reason="extracted candidate mention")
        for mention in candidate_mentions(text)
    ]


def candidate_mentions(text: str) -> list[str]:
    """Return explicit candidate mentions detected in text.

    中文：
    返回文本中出现的候选人名字，来自候选人提取规则和已知候选人列表。
    """
    value = str(text or "").strip()
    if not value:
        return []
    mentions = extract_candidate_mentions(value)
    mentions.extend(name for name in known_candidate_names() if name in value)
    return dedupe_strings(mentions)


def explicit_candidate_match_count(text: str) -> int:
    """Return how many known candidate names appear explicitly in text.

    中文：
    统计文本里显式出现了几个已知候选人名字，用于区分两人对比和多人排序。
    """
    return sum(1 for name in known_candidate_names() if name in text)


def contains_sensitive_interview_terms(text: str, config: ResumeQAConfig) -> bool:
    """Return true when text contains configured sensitive interview terms.

    中文：
    检查是否包含年龄、性别等敏感面试维度；命中后会被 safety guard 拦截。
    """
    payload = config.router_rules.get("sensitive_interview_terms", {}) or {}
    sensitive_terms: list[str] = []
    for values in payload.values():
        sensitive_terms.extend(strings(values))
    return contains_any(text, sensitive_terms)


def contains_any(text: str, items: list[str]) -> bool:
    """Return true when any configured term appears in text."""
    lowered = text.lower()
    return any(item.lower() in lowered for item in items)


def matched_terms(text: str, items: list[str]) -> list[str]:
    """Return configured terms that appear in text."""
    lowered = text.lower()
    return [item for item in items if item.lower() in lowered]


def terms(config: ResumeQAConfig, *path: str) -> list[str]:
    """Read a list of terms from router_rules.yaml by path.

    中文：
    从 router_rules.yaml 的指定路径读取词表，是 signals/rules/guard 共用的词表入口。
    """
    value: Any = config.router_rules
    for key in path:
        if not isinstance(value, dict):
            return []
        value = value.get(key, {})
    return strings(value)


def strings(value: Any) -> list[str]:
    """Coerce YAML list values into non-empty strings."""
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def matches_current_turn_output(text: str, config: ResumeQAConfig, intent: str) -> bool:
    """Return true for phrases that refer to current-turn outputs, e.g. '第一名'.

    中文：
    判断“第一名/这些人”等词是不是在引用当前轮刚生成的结果。
    """
    references = context_reference_rules(config.router_rules)
    resolution = dict(config.router_rules.get("context_resolution", {}) or {})
    for rule_raw in resolution.get("current_turn_outputs", []) or []:
        rule = dict(rule_raw or {})
        if str(rule.get("intent") or "") != intent:
            continue
        reference_terms = [
            term
            for ref_type in strings(rule.get("ref_types", []))
            for term in strings(dict(references.get(ref_type, {}) or {}).get("terms", []))
        ]
        question_terms = terms(config, "signals", str(rule.get("question_signal_group") or ""))
        if contains_any(text, reference_terms) and contains_any(text, question_terms):
            return True
    return False


def known_candidate_names() -> list[str]:
    """Read known candidate names through core data access, not tool layer.

    中文：
    读取已知候选人名单。这里用 core data access，不调用 tools 层，避免 router 依赖工具执行。
    """
    from resume_query_ai_qa.core.data_access import list_known_candidate_names

    return list_known_candidate_names()


def dedupe_strings(values: list[str]) -> list[str]:
    """Dedupe strings while preserving order."""
    return list(dict.fromkeys(values))
