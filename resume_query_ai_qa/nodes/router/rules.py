"""Rule fallback RouterOutput draft construction.

Read this file after node.py and llm.py. It is the deterministic fallback path:
raw conditions -> router signals -> ordered intent handlers -> RouterOutput
draft.

This module does not apply guards or final authoritative recomputation. It only
builds the draft that later stages can correct and finalize.

中文阅读提示：
这个文件是“规则 fallback 草稿生成器”。它的顺序是：
conditions -> signals -> handlers -> sub_intents -> RouterOutput draft。
signals.py 只负责侦察；本文件才把信号变成候选 intent 草稿。这里不做最终权威
重算，最终字段以后交给 finalizer.py。
"""

from __future__ import annotations

from resume_query_ai_qa.core.rules.condition_rules import extract_conditions
from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.schemas import ContextPolicy, QueryCondition, RouterOutput, SubIntentEvidence
from resume_query_ai_qa.nodes.router.rule_types import IntentDraft, RouterSignals, RuleContext
from resume_query_ai_qa.nodes.router.signals import (
    candidate_mentions,
    candidate_reference_conditions,
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

_ROUTER_SIGNAL_FACADE = (
    candidate_mentions,
    explicit_candidate_match_count,
    looks_like_candidate_reference,
    looks_like_context_pool_priority_question,
    looks_like_pair_compare,
    looks_like_single_candidate_fit_question,
    strings,
)


def build_rule_router_draft(question: str, config: ResumeQAConfig | None = None) -> RouterOutput:
    """Build a deterministic RouterOutput draft from rules.

    Reads YAML: router_rules.yaml intent/signals/context rules, condition rules
    and shared taxonomy through extract_conditions.
    Updates RouterOutput: draft intent, sub_intents, evidence, conditions,
    context_policy, requires_jd/requires_evidence hints.
    Does not: apply guard overrides, normalize conditions, or finalize fields.

    中文：
    规则路径总入口。先抽条件，再检测信号；非简历领域或敏感面试问题直接
    out_of_scope；普通问题进入 handler 链路推断 sub_intents。
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
    """Build the out_of_scope draft used by safety and empty-question paths.

    中文：
    构造安全边界结果。空问题、非简历问题、敏感面试问题都会走这里。
    """
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
    """Build the interview-question draft when interview trigger terms match.

    中文：
    面试题生成专用草稿。若问题里带候选人引用，会把候选人补成
    candidate_name condition。
    """
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
    """Infer sub-intents by running rule handlers in a stable order.

    中文：
    这里是规则 intent 的核心执行顺序。每个 handler 看一类信号，命中后往
    IntentDraft 里追加 sub_intent/evidence/requires_* 提示。
    """
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
    """Assemble the rule RouterOutput draft from inferred sub-intents.

    中文：
    把 handler 产出的 sub_intents 组装成 RouterOutput 草稿。多个 sub_intent
    会变成 compound；一个 sub_intent 就作为主 intent。
    """
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
    """Dedupe intent-like string lists while preserving order.

    中文：
    对 intent/sub_intent/risk_flag 这类字符串列表去重，保留第一次出现顺序。
    """
    output: list[str] = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def dedupe_rule_conditions(values: list[QueryCondition]) -> list[QueryCondition]:
    """Dedupe raw QueryCondition values while preserving original priority.

    中文：
    对 raw QueryCondition 去重，并优先保留更长、更具体的条件值。
    """
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
    """Return the configured human-readable reason for a rule intent.

    中文：
    从 router_rules.yaml.intent_reasons 取说明文字，用于 sub_intent_evidence.reason。
    """
    cfg = config or load_config()
    reasons = cfg.router_rules.get("intent_reasons", {}) or {}
    if intent in reasons:
        return str(reasons[intent])
    fallback = reasons.get("fallback_with_evidence") if evidence else reasons.get("fallback")
    return str(fallback or "由整体语义触发该子意图。")


def condition_evidence(conditions: list[QueryCondition]) -> list[str]:
    """Return evidence strings from extracted conditions.

    中文：
    把抽出来的条件转成 evidence 字符串，供 intent 证据记录使用。
    """
    return [item.evidence or item.raw_value for item in conditions if item.evidence or item.raw_value]


def handle_count_intent(draft: IntentDraft, ctx: RuleContext) -> None:
    """count trigger terms -> candidate_count; major count also keeps filter intent.

    中文：
    命中“几个/多少”等 count 词时添加 candidate_count；如果是专业人数问题，
    额外保留 candidate_filter，便于后续先过滤再统计。
    """
    if not contains_any(ctx.text, terms(ctx.config, "intent_rules", "candidate_count", "trigger_any")) or ctx.signals.context_pool_priority:
        return
    if any(condition.type == "major" for condition in ctx.conditions):
        draft.add("candidate_filter", condition_evidence(ctx.conditions))
    draft.add("candidate_count", matched_terms(ctx.text, terms(ctx.config, "intent_rules", "candidate_count", "trigger_any")))


def handle_list_or_profile_intent(draft: IntentDraft, ctx: RuleContext) -> None:
    """list terms -> candidate_list, or profile/evidence for single-candidate references.

    中文：
    处理“都有谁/列一下/哪些人”。如果问题其实是在问单个候选人的项目或经历，
    会转成 profile/evidence，而不是候选人列表。
    """
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


def handle_scoped_collection_project_evidence_intent(draft: IntentDraft, ctx: RuleContext) -> None:
    """scoped candidate list + per-person project terms -> list + evidence."""
    if not ctx.signals.scoped_project_evidence_request or ctx.signals.candidate_reference:
        return
    draft.add("candidate_list", matched_terms(ctx.text, terms(ctx.config, "signals", "collection_request_terms")))
    draft.add(
        "evidence_question",
        matched_terms(ctx.text, terms(ctx.config, "signals", "per_person_terms") + terms(ctx.config, "signals", "project_terms")),
    )
    draft.requires_evidence = True


def handle_profile_terms_intent(draft: IntentDraft, ctx: RuleContext) -> None:
    """profile terms without open discovery -> candidate_profile_intro.

    中文：
    命中“介绍/背景/简历”等画像词时添加 candidate_profile_intro；但开放发现
    类问题不在这里抢 intent。
    """
    discovery_terms = terms(ctx.config, "signals", "discovery_terms") + terms(ctx.config, "signals", "open_recall_terms")
    is_discovery_without_reference = contains_any(ctx.text, discovery_terms) and not (
        ctx.signals.candidate_reference or ctx.signals.context_single_reference
    )
    if ctx.signals.scoped_project_evidence_request:
        return
    if contains_any(ctx.text, terms(ctx.config, "signals", "profile_terms")) and not is_discovery_without_reference:
        draft.add("candidate_profile_intro", matched_terms(ctx.text, terms(ctx.config, "signals", "profile_terms")))
        draft.requires_evidence = True


def handle_single_candidate_project_profile_intent(draft: IntentDraft, ctx: RuleContext) -> None:
    """single candidate + project listing terms -> candidate_profile_intro.

    中文：
    明确某个候选人 + 项目列表词，通常是问这个人的项目画像。
    """
    if (
        ctx.signals.candidate_reference
        and ctx.signals.project_listing
        and not ctx.signals.evidence_locator
        and contains_any(ctx.text, terms(ctx.config, "signals", "single_candidate_profile_terms"))
    ):
        draft.add("candidate_profile_intro", matched_terms(ctx.text, terms(ctx.config, "signals", "single_candidate_profile_terms")))
        draft.requires_evidence = True


def handle_evidence_locator_intent(draft: IntentDraft, ctx: RuleContext) -> None:
    """evidence locator terms -> evidence_question and requires_evidence.

    中文：
    命中“依据/证据/为什么/哪里体现”等词时添加 evidence_question，并提示需要证据。
    """
    if ctx.signals.evidence_locator:
        draft.add("evidence_question", matched_terms(ctx.text, terms(ctx.config, "intent_rules", "evidence_question", "trigger_any")))
        draft.requires_evidence = True


def handle_context_pool_filter_intent(draft: IntentDraft, ctx: RuleContext) -> None:
    """context candidate pool + discovery/filter condition -> candidate_filter.

    中文：
    针对“这些人里找金融相关的”这类上下文候选池过滤问题，添加 candidate_filter。
    如果还问项目/经历，会再补 evidence_question。
    """
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
    """pair comparison -> candidate_compare_pair; ranking signals -> candidate_ranking.

    中文：
    两人对比走 candidate_compare_pair；多人排序/推荐/最强走 candidate_ranking，
    并提示需要 JD 和证据。
    """
    if ctx.signals.pair_compare or (ctx.signals.context_pair_reference and contains_any(ctx.text, terms(ctx.config, "pair_compare", "compare_terms"))):
        draft.add("candidate_compare_pair", matched_terms(ctx.text, terms(ctx.config, "intent_rules", "candidate_compare_pair", "trigger_any")))
        draft.requires_evidence = True
    elif (looks_like_ranking_request(ctx.text, ctx.config) or ctx.signals.context_pool_priority) and not ctx.signals.single_candidate_fit:
        draft.add("candidate_ranking", matched_terms(ctx.text, terms(ctx.config, "intent_rules", "candidate_ranking", "trigger_any")))
        draft.requires_jd = True
        draft.requires_evidence = True


def handle_single_candidate_fit_intent(draft: IntentDraft, ctx: RuleContext) -> None:
    """single-candidate fit question -> profile + evidence sub-intents.

    中文：
    单个候选人是否适合某方向，通常需要“画像 + 证据”两个子任务。
    """
    if ctx.signals.single_candidate_fit and not ctx.signals.pair_compare:
        draft.add("candidate_profile_intro", matched_terms(ctx.text, terms(ctx.config, "signals", "fit_terms")))
        draft.add("evidence_question", matched_terms(ctx.text, terms(ctx.config, "signals", "single_candidate_evidence_terms")))
        draft.requires_evidence = True


def handle_candidate_domain_evidence_intent(draft: IntentDraft, ctx: RuleContext) -> None:
    """candidate reference + domain + yes/no experience terms -> evidence_question.

    中文：
    明确候选人 + 领域 + 是否有经验，转成 evidence_question，因为答案必须找简历依据。
    """
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
    """context single reference + domain experience terms overrides profile into evidence.

    中文：
    “第一名有金融经验吗”这类上下文单人问题，如果已误判为 profile，会覆盖成
    evidence_question。
    """
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
    """remaining extracted conditions with no intent -> candidate_filter fallback.

    中文：
    如果已经抽到 domain/skill/major 等条件，但没有任何明确 intent，就兜底为
    candidate_filter。
    """
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
    handle_scoped_collection_project_evidence_intent,
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
