"""Rule fallback RouterOutput draft construction.

Read this file after node.py and llm.py. It is the deterministic fallback path:
raw conditions -> router signals -> ordered intent handlers -> RouterOutput
draft.

This module does not apply guards or final authoritative recomputation. It only
builds the draft that later stages can correct and finalize.
"""

from __future__ import annotations

from resume_query_ai_qa.core.rules.condition_rules import extract_conditions
from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.schemas import ContextPolicy, QueryCondition, RouterOutput, SubIntentEvidence
from resume_query_ai_qa.nodes.router.rule_types import IntentDraft, RouterSignals, RuleContext
from resume_query_ai_qa.nodes.router.signals import (
    candidate_mentions,
    candidate_reference_conditions,
    contains_sensitive_interview_terms,
    contains_any,
    detect_router_signals,
    explicit_candidate_match_count,
    is_resume_domain_question,
    looks_like_candidate_reference,
    looks_like_context_pool_priority_question,
    looks_like_pair_compare,
    looks_like_ranking_request,
    looks_like_single_candidate_fit_question,
    matched_terms,
    strings,
    terms,
)


def build_rule_router_draft(question: str, config: ResumeQAConfig | None = None) -> RouterOutput:
    """Build a deterministic RouterOutput draft from rules.

    Reads YAML: router_rules.yaml intent/signals/context rules, condition rules
    and shared taxonomy through extract_conditions.
    Updates RouterOutput: draft intent, sub_intents, evidence, conditions,
    context_policy, requires_jd/requires_evidence hints.
    Does not: apply guard overrides, normalize conditions, or finalize fields.
    """
    cfg = config or load_config()
    text = str(question or "").strip()
    conditions = extract_conditions(text)
    signals = detect_router_signals(text, conditions, cfg)
    if not is_resume_domain_question(text, conditions, signals, cfg):
        return build_out_of_scope_draft(text, cfg)
    if signals.interview_question and signals.sensitive_interview:
        return build_out_of_scope_draft(text, cfg)
    if signals.interview_question:
        return build_interview_router_draft(RuleContext(text=text, conditions=conditions, signals=signals, config=cfg))

    sub_intents, evidence_by_intent, requires_jd, requires_evidence = infer_rule_sub_intents(
        text,
        conditions,
        signals,
        cfg,
    )
    return build_rule_router_output(
        text,
        conditions,
        signals,
        sub_intents,
        evidence_by_intent,
        requires_jd=requires_jd,
        requires_evidence=requires_evidence,
        config=cfg,
    )


def build_out_of_scope_draft(text: str, config: ResumeQAConfig) -> RouterOutput:
    """Build the out_of_scope draft used by safety and empty-question paths."""
    return RouterOutput(
        intent="out_of_scope",
        is_compound=False,
        sub_intent_candidates=["out_of_scope"],
        sub_intent_evidence=[
            SubIntentEvidence(
                intent="out_of_scope",
                evidence=[text],
                reason=intent_reason("out_of_scope", [text], config),
            )
        ],
        conditions=[],
        context_policy=ContextPolicy(),
        requires_jd=False,
        requires_evidence=False,
        allowed_tool_names=config.allowed_tools_for_intent("out_of_scope"),
        risk_flags=[],
    )


def build_interview_router_draft(ctx: RuleContext) -> RouterOutput:
    """Build the interview-question draft when interview trigger terms match."""
    conditions = list(ctx.conditions)
    if ctx.signals.candidate_reference:
        conditions = [*conditions, *candidate_reference_conditions(ctx.text)]
    intent = "interview_question_generation"
    evidence = matched_terms(ctx.text, terms(ctx.config, "intent_rules", "interview_question_generation", "trigger_any")) or [ctx.text]
    return RouterOutput(
        intent=intent,
        is_compound=False,
        sub_intent_candidates=[intent],
        sub_intent_evidence=[SubIntentEvidence(intent=intent, evidence=evidence, reason=intent_reason(intent, evidence, ctx.config))],
        conditions=dedupe_rule_conditions(conditions),
        context_policy=ctx.signals.context_policy,
        requires_jd=False,
        requires_evidence=True,
        allowed_tool_names=ctx.config.allowed_tools_for_intent(intent),
        risk_flags=[],
    )


def infer_rule_sub_intents(
    text: str,
    conditions: list[QueryCondition],
    signals: RouterSignals,
    config: ResumeQAConfig,
) -> tuple[list[str], dict[str, list[str]], bool, bool]:
    """Infer sub-intents by running rule handlers in a stable order."""
    draft = IntentDraft()
    ctx = RuleContext(text=text, conditions=conditions, signals=signals, config=config)
    for handler in RULE_INTENT_HANDLERS:
        handler(draft, ctx)
    return dedupe_rule_intents(draft.sub_intents), draft.evidence_by_intent, draft.requires_jd, draft.requires_evidence


def build_rule_router_output(
    text: str,
    conditions: list[QueryCondition],
    signals: RouterSignals,
    sub_intents: list[str],
    evidence_by_intent: dict[str, list[str]],
    *,
    requires_jd: bool,
    requires_evidence: bool,
    config: ResumeQAConfig,
) -> RouterOutput:
    """Assemble the rule RouterOutput draft from inferred sub-intents."""
    if signals.candidate_reference:
        conditions = [*conditions, *candidate_reference_conditions(text)]
    if len(sub_intents) > 1:
        intent = "compound"
        is_compound = True
    else:
        intent = sub_intents[0] if sub_intents else "candidate_filter"
        is_compound = False
        sub_intents = sub_intents or [intent]
    return RouterOutput(
        intent=intent,  # type: ignore[arg-type]
        is_compound=is_compound,
        sub_intent_candidates=sub_intents,  # type: ignore[list-item]
        sub_intent_evidence=[
            SubIntentEvidence(
                intent=sub_intent,  # type: ignore[arg-type]
                evidence=evidence_by_intent.get(sub_intent, []) or [text],
                reason=intent_reason(sub_intent, evidence_by_intent.get(sub_intent, []), config),
            )
            for sub_intent in sub_intents
        ],
        conditions=dedupe_rule_conditions(conditions),
        context_policy=signals.context_policy,
        requires_jd=requires_jd,
        requires_evidence=requires_evidence,
        allowed_tool_names=config.allowed_tools_for_intent(intent),
        risk_flags=[],
    )


def dedupe_rule_intents(values: list[str]) -> list[str]:
    """Dedupe intent-like string lists while preserving order."""
    output: list[str] = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def dedupe_rule_conditions(values: list[QueryCondition]) -> list[QueryCondition]:
    """Dedupe raw QueryCondition values while preserving original priority."""
    output: list[QueryCondition] = []
    seen: set[str] = set()
    for value in sorted(values, key=lambda item: len(item.raw_value), reverse=True):
        raw = value.raw_value.lower()
        key = f"{value.type}:{raw}"
        if not raw or key in seen:
            continue
        if any(old.startswith(f"{value.type}:") and raw in old.split(":", 1)[1] for old in seen):
            continue
        seen.add(key)
        output.append(value)
    return sorted(output, key=lambda item: values.index(item) if item in values else 0)


def intent_reason(intent: str, evidence: list[str], config: ResumeQAConfig | None = None) -> str:
    """Return the configured human-readable reason for a rule intent."""
    cfg = config or load_config()
    reasons = cfg.router_rules.get("intent_reasons", {}) or {}
    if intent in reasons:
        return str(reasons[intent])
    fallback = reasons.get("fallback_with_evidence") if evidence else reasons.get("fallback")
    return str(fallback or "由整体语义触发该子意图。")


def condition_evidence(conditions: list[QueryCondition]) -> list[str]:
    """Return evidence strings from extracted conditions."""
    return [item.evidence or item.raw_value for item in conditions if item.evidence or item.raw_value]


def handle_count_intent(draft: IntentDraft, ctx: RuleContext) -> None:
    """count trigger terms -> candidate_count; major count also keeps filter intent."""
    if not contains_any(ctx.text, terms(ctx.config, "intent_rules", "candidate_count", "trigger_any")) or ctx.signals.context_pool_priority:
        return
    if any(condition.type == "major" for condition in ctx.conditions):
        draft.add("candidate_filter", condition_evidence(ctx.conditions))
    draft.add("candidate_count", matched_terms(ctx.text, terms(ctx.config, "intent_rules", "candidate_count", "trigger_any")))


def handle_list_or_profile_intent(draft: IntentDraft, ctx: RuleContext) -> None:
    """list terms -> candidate_list, or profile/evidence for single-candidate references."""
    if ctx.signals.pair_compare or not contains_any(ctx.text, terms(ctx.config, "intent_rules", "candidate_list", "trigger_any")):
        return
    if (
        (ctx.signals.candidate_reference or ctx.signals.context_single_reference)
        and contains_any(ctx.text, terms(ctx.config, "signals", "experience_terms"))
        and any(condition.type == "domain" for condition in ctx.conditions)
    ):
        draft.add("evidence_question", matched_terms(ctx.text, terms(ctx.config, "signals", "experience_terms")))
        draft.requires_evidence = True
    elif (ctx.signals.candidate_reference or ctx.signals.context_single_reference) and contains_any(ctx.text, _profile_or_project_terms(ctx.config)):
        draft.add("candidate_profile_intro", matched_terms(ctx.text, _profile_or_project_terms(ctx.config)))
        draft.requires_evidence = True
    else:
        draft.add("candidate_list", matched_terms(ctx.text, terms(ctx.config, "intent_rules", "candidate_list", "trigger_any")))


def handle_profile_terms_intent(draft: IntentDraft, ctx: RuleContext) -> None:
    """profile terms without open discovery -> candidate_profile_intro."""
    discovery_terms = terms(ctx.config, "signals", "discovery_terms") + terms(ctx.config, "signals", "open_recall_terms")
    is_discovery_without_reference = contains_any(ctx.text, discovery_terms) and not (
        ctx.signals.candidate_reference or ctx.signals.context_single_reference
    )
    if contains_any(ctx.text, terms(ctx.config, "signals", "profile_terms")) and not is_discovery_without_reference:
        draft.add("candidate_profile_intro", matched_terms(ctx.text, terms(ctx.config, "signals", "profile_terms")))
        draft.requires_evidence = True


def handle_single_candidate_project_profile_intent(draft: IntentDraft, ctx: RuleContext) -> None:
    """single candidate + project listing terms -> candidate_profile_intro."""
    if (
        ctx.signals.candidate_reference
        and ctx.signals.project_listing
        and not ctx.signals.evidence_locator
        and contains_any(ctx.text, terms(ctx.config, "signals", "single_candidate_profile_terms"))
    ):
        draft.add("candidate_profile_intro", matched_terms(ctx.text, terms(ctx.config, "signals", "single_candidate_profile_terms")))
        draft.requires_evidence = True


def handle_evidence_locator_intent(draft: IntentDraft, ctx: RuleContext) -> None:
    """evidence locator terms -> evidence_question and requires_evidence."""
    if ctx.signals.evidence_locator:
        draft.add("evidence_question", matched_terms(ctx.text, terms(ctx.config, "intent_rules", "evidence_question", "trigger_any")))
        draft.requires_evidence = True


def handle_context_pool_filter_intent(draft: IntentDraft, ctx: RuleContext) -> None:
    """context candidate pool + discovery/filter condition -> candidate_filter."""
    has_filter_condition = any(condition.type in {"domain", "skill", "keyword", "scope", "major"} for condition in ctx.conditions)
    if not (ctx.signals.context_pool_reference and ctx.signals.discovery and has_filter_condition):
        return
    draft.add(
        "candidate_filter",
        matched_terms(ctx.text, terms(ctx.config, "signals", "discovery_terms") + terms(ctx.config, "signals", "experience_terms")),
    )
    draft.requires_evidence = True
    if ctx.signals.project_listing:
        draft.add(
            "evidence_question",
            matched_terms(ctx.text, terms(ctx.config, "signals", "project_terms") + terms(ctx.config, "signals", "experience_terms")),
        )


def handle_compare_or_ranking_intent(draft: IntentDraft, ctx: RuleContext) -> None:
    """pair comparison -> candidate_compare_pair; ranking signals -> candidate_ranking."""
    if ctx.signals.pair_compare or (ctx.signals.context_pair_reference and contains_any(ctx.text, terms(ctx.config, "pair_compare", "compare_terms"))):
        draft.add("candidate_compare_pair", matched_terms(ctx.text, terms(ctx.config, "intent_rules", "candidate_compare_pair", "trigger_any")))
        draft.requires_evidence = True
    elif (looks_like_ranking_request(ctx.text, ctx.config) or ctx.signals.context_pool_priority) and not ctx.signals.single_candidate_fit:
        draft.add("candidate_ranking", matched_terms(ctx.text, terms(ctx.config, "intent_rules", "candidate_ranking", "trigger_any")))
        draft.requires_jd = True
        draft.requires_evidence = True


def handle_single_candidate_fit_intent(draft: IntentDraft, ctx: RuleContext) -> None:
    """single-candidate fit question -> profile + evidence sub-intents."""
    if ctx.signals.single_candidate_fit and not ctx.signals.pair_compare:
        draft.add("candidate_profile_intro", matched_terms(ctx.text, terms(ctx.config, "signals", "fit_terms")))
        draft.add("evidence_question", matched_terms(ctx.text, terms(ctx.config, "signals", "single_candidate_evidence_terms")))
        draft.requires_evidence = True


def handle_candidate_domain_evidence_intent(draft: IntentDraft, ctx: RuleContext) -> None:
    """candidate reference + domain + yes/no experience terms -> evidence_question."""
    if (
        ctx.signals.candidate_reference
        and any(condition.type == "domain" for condition in ctx.conditions)
        and contains_any(ctx.text, terms(ctx.config, "signals", "yes_no_evidence_terms") + terms(ctx.config, "signals", "experience_terms"))
    ):
        draft.add(
            "evidence_question",
            matched_terms(ctx.text, terms(ctx.config, "signals", "yes_no_evidence_terms") + terms(ctx.config, "signals", "experience_terms")),
        )
        draft.requires_evidence = True


def handle_context_single_evidence_override(draft: IntentDraft, ctx: RuleContext) -> None:
    """context single reference + domain experience terms overrides profile into evidence."""
    if (
        ctx.signals.context_single_reference
        and any(condition.type == "domain" for condition in ctx.conditions)
        and "candidate_profile_intro" in draft.sub_intents
        and contains_any(ctx.text, terms(ctx.config, "signals", "experience_terms"))
    ):
        draft.sub_intents = ["evidence_question" if item == "candidate_profile_intro" else item for item in draft.sub_intents]
        draft.evidence_by_intent["evidence_question"] = draft.evidence_by_intent.pop("candidate_profile_intro", []) or matched_terms(
            ctx.text,
            terms(ctx.config, "signals", "experience_terms"),
        )
        draft.requires_evidence = True


def handle_condition_fallback_intent(draft: IntentDraft, ctx: RuleContext) -> None:
    """remaining extracted conditions with no intent -> candidate_filter fallback."""
    if draft.sub_intents or not ctx.conditions:
        return
    draft.add(
        "candidate_filter",
        [*condition_evidence(ctx.conditions), *matched_terms(ctx.text, terms(ctx.config, "signals", "open_recall_terms"))],
    )
    draft.requires_evidence = True


def _profile_or_project_terms(config: ResumeQAConfig) -> list[str]:
    """获取候选人画像OR项目词项集合并返回。"""
    return terms(config, "signals", "project_terms") + terms(config, "signals", "experience_terms") + terms(config, "signals", "profile_terms")


RULE_INTENT_HANDLERS = [
    handle_count_intent,
    handle_list_or_profile_intent,
    handle_profile_terms_intent,
    handle_single_candidate_project_profile_intent,
    handle_evidence_locator_intent,
    handle_context_pool_filter_intent,
    handle_compare_or_ranking_intent,
    handle_single_candidate_fit_intent,
    handle_candidate_domain_evidence_intent,
    handle_context_single_evidence_override,
    handle_condition_fallback_intent,
]
