"""Router hard-rule guard stage.

Read this file after signals.py. It corrects unstable LLM/rule drafts with
deterministic boundaries: safety, context references, pair comparison, ranking,
evidence, compound tasks, and configured intent convergence.

This module does not build the original draft and does not finalize authoritative
fields; finalizer.py still recomputes the final RouterOutput contract.
"""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.rules.condition_rules import extract_conditions
from resume_query_ai_qa.core.rules.context_resolver import resolve_context_policy
from resume_query_ai_qa.core.schemas import ContextPolicy, RouterOutput

from . import rules
from .finalizer import with_risk_flag


def apply_router_guards(output: RouterOutput, question: str, config: ResumeQAConfig) -> RouterOutput:
    """Stage 3: apply deterministic guard corrections to a RouterOutput draft.

    Reads YAML: router_rules.yaml safety/context/compound/ranking/convergence
    sections.
    Updates RouterOutput: intent, is_compound, sub_intent_candidates,
    context_policy, requires_jd/requires_evidence hints, risk_flags.
    Does not: generate normalized_conditions or final allowed_tool_names.
    """
    guarded = apply_safety_guard(output, question, config)
    guarded = apply_intent_override_guards(guarded, question, config)
    guarded = apply_compound_guard(guarded, question, config)
    guarded = apply_context_guard(guarded, question, config)
    return apply_intent_convergence_guard(guarded, question, config)


def apply_safety_guard(output: RouterOutput, question: str, config: ResumeQAConfig) -> RouterOutput:
    """Sensitive interview terms -> out_of_scope draft with audit flags."""
    try:
        if looks_like_sensitive_interview(question, output, config):
            return out_of_scope_with_guard_flags(output, question, config, "sensitive_interview_guard_applied")
        return output
    except Exception as error:
        return with_risk_flag(output, f"router_rule_guard_failed:{type(error).__name__}: {str(error)[:120]}")


def apply_context_guard(output: RouterOutput, question: str, config: ResumeQAConfig) -> RouterOutput:
    """Context terms like '这些人/第一名/这两个人' -> context_policy."""
    try:
        policy = context_policy_from_config(question, config)
        if not policy.uses_context:
            return output
        current_turn_refs = current_turn_output_ref_types(output, config)
        if policy.context_ref_type in current_turn_refs:
            inherited_policy = resolve_context_policy(question, config.router_rules, excluded_ref_types=current_turn_refs)
            return output.model_copy(update={"context_policy": inherited_policy})
        if policy.context_ref_type in {"candidate_pool", "comparison_pair"} and rules.explicit_candidate_match_count(question) >= 2:
            return output
        if output.context_policy.uses_context and output.context_policy.context_ref_type == policy.context_ref_type:
            return output
        return copy_with_guard_flags(output, "context_reference_guard_applied", context_policy=policy)
    except Exception as error:
        return with_risk_flag(output, f"router_context_guard_failed:{type(error).__name__}: {str(error)[:120]}")


def apply_intent_override_guards(output: RouterOutput, question: str, config: ResumeQAConfig) -> RouterOutput:
    """Apply pair/ranking/evidence intent overrides that are safer than draft intent."""
    for guard in (apply_ranking_guard, apply_pair_compare_guard, apply_evidence_guard):
        guarded = guard(output, question, config)
        if guarded is not output:
            return guarded
    return output


def apply_pair_compare_guard(output: RouterOutput, question: str, config: ResumeQAConfig) -> RouterOutput:
    """Pair compare terms with two candidates -> candidate_compare_pair."""
    if output.context_policy.uses_context and output.context_policy.context_ref_type == "comparison_pair" and matches_comparison_pair_followup(question, config):
        return copy_with_guard_flags(
            output,
            "pair_compare_guard_applied",
            "llm_router_contract_overridden_by_rule_guard",
            intent="candidate_compare_pair",
            is_compound=False,
            sub_intent_candidates=["candidate_compare_pair"],
            requires_evidence=True,
        )
    if rules.looks_like_pair_compare(question, config) and has_two_candidates(question):
        return copy_with_guard_flags(
            output,
            "pair_compare_guard_applied",
            "llm_router_contract_overridden_by_rule_guard",
            intent="candidate_compare_pair",
            is_compound=False,
            sub_intent_candidates=["candidate_compare_pair"],
            requires_evidence=True,
        )
    return output


def apply_ranking_guard(output: RouterOutput, question: str, config: ResumeQAConfig) -> RouterOutput:
    """Configured candidate-set ranking signals -> candidate_ranking."""
    if looks_like_configured_candidate_set_ranking(output, question, config):
        return copy_with_guard_flags(
            output,
            "ranking_intent_guard_applied",
            "llm_router_contract_overridden_by_rule_guard",
            intent="candidate_ranking",
            is_compound=False,
            sub_intent_candidates=["candidate_ranking"],
            requires_jd=True,
            requires_evidence=True,
        )
    return output


def apply_evidence_guard(output: RouterOutput, question: str, config: ResumeQAConfig) -> RouterOutput:
    """Evidence trigger terms add evidence_question to the draft sub-intents."""
    if contains_config_terms(question, config, "compound_rules", "evidence_terms"):
        sub_intents = list(output.sub_intent_candidates or ([output.intent] if output.intent != "compound" else []))
        if "evidence_question" not in sub_intents:
            sub_intents.append("evidence_question")
            return copy_with_guard_flags(
                output,
                "evidence_guard_applied",
                intent="compound" if len(sub_intents) > 1 else "evidence_question",
                is_compound=len(sub_intents) > 1,
                sub_intent_candidates=rules.dedupe_rule_intents(sub_intents),
                requires_evidence=True,
            )
    return output


def apply_compound_guard(output: RouterOutput, question: str, config: ResumeQAConfig) -> RouterOutput:
    """Compound trigger terms -> candidate_count/list/ranking/evidence sub-intents."""
    detected = detect_compound_sub_intents(question, config)
    if len(detected) <= 1:
        return output
    current = set(output.sub_intent_candidates or ([output.intent] if output.intent != "compound" else []))
    if set(detected).issubset(current) and output.intent == "compound":
        return output
    sub_intents = rules.dedupe_rule_intents([*(output.sub_intent_candidates or []), *detected])
    return copy_with_guard_flags(
        output,
        "compound_guard_applied",
        "llm_router_contract_overridden_by_rule_guard",
        intent="compound",
        is_compound=True,
        sub_intent_candidates=sub_intents,
    )


def apply_intent_convergence_guard(output: RouterOutput, question: str, config: ResumeQAConfig) -> RouterOutput:
    """Configured follow-up/single-fit rules converge vague draft intents."""
    if output.intent == "candidate_ranking" and looks_like_configured_candidate_set_ranking(output, question, config):
        return output
    convergence = dict(config.router_rules.get("intent_convergence", {}) or {})
    ref_type = str(output.context_policy.context_ref_type or "none")
    if output.intent == "follow_up":
        for rule in list(convergence.get("follow_up", []) or []):
            payload = dict(rule or {})
            if ref_type not in {str(item) for item in list(payload.get("context_types", []) or [])}:
                continue
            if not matches_signal_groups(question, config, payload.get("signal_groups", [])):
                continue
            intent = str(payload.get("intent") or "").strip()
            if intent:
                return copy_with_guard_flags(
                    output,
                    "intent_convergence_guard_applied",
                    "llm_router_contract_overridden_by_rule_guard",
                    intent=intent,
                    is_compound=False,
                    sub_intent_candidates=[intent],
                )

    fit_rule = dict(convergence.get("single_candidate_fit", {}) or {})
    has_single_scope = ref_type in {str(item) for item in list(fit_rule.get("context_types", []) or [])} or (
        rules.looks_like_candidate_reference(question) and not rules.looks_like_pair_compare(question, config)
    )
    if has_single_scope and matches_signal_groups(question, config, fit_rule.get("signal_groups", [])):
        sub_intents = [str(item) for item in list(fit_rule.get("sub_intents", []) or []) if str(item).strip()]
        if sub_intents:
            return copy_with_guard_flags(
                output,
                "intent_convergence_guard_applied",
                "llm_router_contract_overridden_by_rule_guard",
                intent="compound",
                is_compound=True,
                sub_intent_candidates=sub_intents,
                requires_evidence=True,
                requires_jd=False,
            )
    return output


def detect_compound_sub_intents(question: str, config: ResumeQAConfig) -> list[str]:
    """Map compound_rules terms to concrete sub-intents."""
    items: list[str] = []
    if contains_config_terms(question, config, "compound_rules", "count_terms"):
        items.append("candidate_count")
    if not rules.looks_like_pair_compare(question, config) and contains_config_terms(question, config, "compound_rules", "list_terms"):
        items.append("candidate_list")
    if contains_config_terms(question, config, "compound_rules", "ranking_terms"):
        items.append("candidate_ranking")
    if contains_config_terms(question, config, "compound_rules", "evidence_terms"):
        items.append("evidence_question")
    return rules.dedupe_rule_intents(items)


def context_policy_from_config(
    question: str,
    config: ResumeQAConfig,
    *,
    excluded_ref_types: set[str] | None = None,
) -> ContextPolicy:
    """Resolve configured context reference terms into a ContextPolicy."""
    return resolve_context_policy(question, config.router_rules, excluded_ref_types=excluded_ref_types)


def current_turn_output_ref_types(output: RouterOutput, config: ResumeQAConfig) -> set[str]:
    """Return context ref types generated by the current draft intent."""
    intents = set(output.sub_intent_candidates or [output.intent])
    resolution = dict(config.router_rules.get("context_resolution", {}) or {})
    return {
        ref_type
        for rule_raw in resolution.get("current_turn_outputs", []) or []
        for rule in [dict(rule_raw or {})]
        if str(rule.get("intent") or "") in intents
        for ref_type in rules.strings(rule.get("ref_types", []))
    }


def looks_like_configured_candidate_set_ranking(output: RouterOutput, question: str, config: ResumeQAConfig) -> bool:
    """Return true when configured signals force candidate_ranking."""
    ranking_rules = dict(config.router_rules.get("ranking_intent_rules", {}) or {})
    min_count = int(ranking_rules.get("multi_candidate_min_count", 3) or 3)
    explicit_count = rules.explicit_candidate_match_count(question)
    context_ref_types = {str(item) for item in list(ranking_rules.get("candidate_set_ref_types", []) or [])}
    context_set = output.context_policy.uses_context and output.context_policy.context_ref_type in context_ref_types
    has_ranking_signal = rules.looks_like_ranking_request(question, config) or matches_signal_groups(question, config, ranking_rules.get("fit_signal_groups", []))
    return bool(has_ranking_signal and (explicit_count >= min_count or context_set))


def matches_comparison_pair_followup(question: str, config: ResumeQAConfig) -> bool:
    """Return true when a comparison_pair context follow-up remains comparative."""
    return rules.contains_any(question, rules.terms(config, "pair_compare", "compare_terms"))


def matches_signal_groups(question: str, config: ResumeQAConfig, groups: Any) -> bool:
    """Return true when question matches any configured signal group."""
    return any(
        rules.contains_any(question, rules.terms(config, "signals", str(group)))
        for group in list(groups or [])
    )


def has_two_candidates(question: str) -> bool:
    """Return true when text explicitly references at least two candidates."""
    return rules.explicit_candidate_match_count(question) >= 2 or len(rules.candidate_mentions(question)) >= 2


def contains_config_terms(question: str, config: ResumeQAConfig, *path: str) -> bool:
    """Return true when question contains any terms from router_rules.yaml path."""
    return rules.contains_any(question, rules.terms(config, *path))


def looks_like_sensitive_interview(question: str, output: RouterOutput, config: ResumeQAConfig) -> bool:
    """Return true when an interview request includes sensitive attributes."""
    looks_like_interview = (
        output.intent == "interview_question_generation"
        or rules.contains_any(question, rules.terms(config, "intent_rules", "interview_question_generation", "trigger_any"))
        or ("问" in question and rules.looks_like_candidate_reference(question))
    )
    if not looks_like_interview:
        return False
    sensitive_terms: list[str] = []
    for values in (config.router_rules.get("sensitive_interview_terms", {}) or {}).values():
        sensitive_terms.extend(rules.strings(values))
    return rules.contains_any(question, sensitive_terms)


def should_force_out_of_scope(question: str, output: RouterOutput, config: ResumeQAConfig) -> bool:
    """Return true when general-knowledge wording should force out_of_scope."""
    if output.context_policy.uses_context or rules.looks_like_candidate_reference(question) or rules.looks_like_pair_compare(question, config):
        return False
    conditions = list(output.conditions or [])
    if not conditions:
        try:
            conditions = extract_conditions(question)
        except Exception:
            conditions = []
    search_signals = rules.terms(config, "out_of_scope", "resume_search_signals")
    domain_signals = rules.terms(config, "out_of_scope", "resume_domain_signals")
    knowledge_patterns = rules.terms(config, "out_of_scope", "general_knowledge_patterns")
    has_taxonomy_condition = any(getattr(item, "type", "") in {"domain", "skill", "concept", "major"} for item in conditions)
    if rules.contains_any(question, knowledge_patterns) and not rules.contains_any(question, search_signals):
        return True
    if has_taxonomy_condition and not rules.contains_any(question, [*search_signals, *domain_signals]):
        return True
    return False


def copy_with_guard_flags(output: RouterOutput, *flags: str, **updates: Any) -> RouterOutput:
    """Copy RouterOutput while appending deduped guard audit flags."""
    return output.model_copy(update={**updates, "risk_flags": rules.dedupe_rule_intents([*output.risk_flags, *flags])})


def out_of_scope_with_guard_flags(output: RouterOutput, question: str, config: ResumeQAConfig, flag: str) -> RouterOutput:
    """Build out_of_scope draft and preserve guard audit flags."""
    guarded = rules.build_out_of_scope_draft(question, config)
    return guarded.model_copy(update={"risk_flags": rules.dedupe_rule_intents([*output.risk_flags, flag, "llm_router_contract_overridden_by_rule_guard"])})
