"""Router text signal detection.

Read this file after rules.py. It is the scout layer: it inspects question text,
conditions, candidate mentions, and router_rules.yaml terms to produce
RouterSignals.

This module does not generate RouterOutput and does not decide final intent.
rules.py is the decision layer that turns these signals into draft intents.
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
    """Detect all signals needed by rule fallback and guard stages."""
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
    return RouterSignals(
        pair_compare=looks_like_pair_compare(text, config),
        candidate_reference=candidate_reference,
        context_policy=context_policy,
        context_single_reference=context_policy.context_ref_type in {str(item) for item in list(resolution.get("single_candidate_ref_types", []) or [])},
        context_pair_reference=context_policy.context_ref_type in {str(item) for item in list(resolution.get("pair_ref_types", []) or [])},
        context_pool_reference=context_policy.context_ref_type in {str(item) for item in list(resolution.get("pool_ref_types", []) or [])},
        discovery=contains_any(text, terms(config, "signals", "discovery_terms")),
        project_listing=contains_any(text, terms(config, "signals", "project_terms")),
        evidence_locator=contains_any(text, terms(config, "intent_rules", "evidence_question", "trigger_any")),
        single_candidate_fit=looks_like_single_candidate_fit_question(text, config),
        context_pool_priority=context_policy.context_ref_type == "candidate_pool"
        and looks_like_context_pool_priority_question(text, config),
        interview_question=contains_any(text, terms(config, "intent_rules", "interview_question_generation", "trigger_any")),
        sensitive_interview=contains_sensitive_interview_terms(text, config),
    )


def looks_like_pair_compare(text: str, config: ResumeQAConfig | None = None) -> bool:
    """Return true when text asks for exactly-two-candidate comparison."""
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
    """Return true when text contains an explicit known candidate mention."""
    return bool(candidate_mentions(text))


def looks_like_ranking_request(text: str, config: ResumeQAConfig) -> bool:
    """Return true when text asks for ranking/recommendation."""
    return matches_current_turn_output(text, config, "candidate_ranking") or contains_any(
        text,
        terms(config, "intent_rules", "candidate_ranking", "trigger_any")
        + terms(config, "compound_rules", "ranking_terms"),
    )


def looks_like_single_candidate_fit_question(text: str, config: ResumeQAConfig) -> bool:
    """Return true when one explicit candidate is being assessed for fit."""
    if not looks_like_candidate_reference(text):
        return False
    fit_terms = terms(config, "signals", "fit_terms")
    target_terms = "|".join(re.escape(item) for item in terms(config, "signals", "fit_target_terms"))
    relation_terms = "|".join(re.escape(item) for item in terms(config, "signals", "fit_relation_terms"))
    return contains_any(text, fit_terms) or bool(target_terms and relation_terms and re.search(rf"({relation_terms}).{{0,8}}({target_terms})", text))


def looks_like_context_pool_priority_question(text: str, config: ResumeQAConfig) -> bool:
    """Return true when a context candidate pool is being prioritized/ranked."""
    if not contains_any(text, terms(config, "signals", "question_subject_terms")):
        return False
    return contains_any(text, terms(config, "signals", "context_pool_priority_terms"))


def is_resume_domain_question(
    text: str,
    conditions: list[QueryCondition],
    signals: RouterSignals,
    config: ResumeQAConfig,
) -> bool:
    """Return true when the question belongs to resume/candidate search domain."""
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
    """Convert explicit candidate mentions into candidate_name conditions."""
    return [
        QueryCondition(type="candidate_name", raw_value=mention, evidence=mention, reason="extracted candidate mention")
        for mention in candidate_mentions(text)
    ]


def candidate_mentions(text: str) -> list[str]:
    """Return explicit candidate mentions detected in text."""
    value = str(text or "").strip()
    if not value:
        return []
    mentions = extract_candidate_mentions(value)
    mentions.extend(name for name in known_candidate_names() if name in value)
    return dedupe_strings(mentions)


def explicit_candidate_match_count(text: str) -> int:
    """Return how many known candidate names appear explicitly in text."""
    return sum(1 for name in known_candidate_names() if name in text)


def contains_sensitive_interview_terms(text: str, config: ResumeQAConfig) -> bool:
    """Return true when text contains configured sensitive interview terms."""
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
    """Read a list of terms from router_rules.yaml by path."""
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
    """Return true for phrases that refer to current-turn outputs, e.g. '第一名'."""
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
    """Read known candidate names through core data access, not tool layer."""
    from resume_query_ai_qa.core.data_access import list_known_candidate_names

    return list_known_candidate_names()


def dedupe_strings(values: list[str]) -> list[str]:
    """Dedupe strings while preserving order."""
    return list(dict.fromkeys(values))
