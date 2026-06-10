"""RouterOutput authoritative finalization.

Read this file after conditions.py. LLM/rule draft values are not authoritative:
this module recomputes the final RouterOutput contract from the draft, question,
and YAML config.

This module does not reinterpret natural language from scratch. It preserves
legal draft decisions when possible and fills/repairs derived fields.
"""

from __future__ import annotations

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.rules.execution_policy_rules import rule_scenario_decisions
from resume_query_ai_qa.core.schemas import ContextPolicy, RouterOutput, ScenarioDecision, SubIntentEvidence

from . import rules


def finalize_router_output(output: RouterOutput, question: str, config: ResumeQAConfig) -> RouterOutput:
    """Stage 5: recompute final RouterOutput fields.

    Reads YAML: intents.yaml for requires_jd/requires_evidence defaults,
    scenarios.yaml for scenario legality/fallback, tool_policy.yaml for
    allowed_tool_names, router_rules.yaml for evidence terms and risk flags.
    Updates RouterOutput: intent/is_compound/sub_intents/evidence/scenarios/
    conditions/requires flags/tool names/risk flags.
    Does not: create normalized_conditions or tool calls.
    """
    intent, sub_intents = finalize_intent_and_sub_intents(output)
    scenario_decisions = finalize_scenario_decisions(output, sub_intents, question, config)
    return output.model_copy(
        update={
            "intent": intent,
            "is_compound": intent == "compound",
            "sub_intent_candidates": sub_intents,
            "sub_intent_evidence": finalize_sub_intent_evidence(output, sub_intents, question),
            "scenario_decisions": scenario_decisions,
            "conditions": finalize_conditions(output, intent),
            "normalized_conditions": [],
            "requires_jd": finalize_requires_jd(intent, sub_intents, config),
            "requires_evidence": finalize_requires_evidence(intent, sub_intents, question, config),
            "allowed_tool_names": finalize_allowed_tool_names(intent, scenario_decisions, config),
            "risk_flags": finalize_risk_flags(output.risk_flags, config),
        }
    )


def finalize_intent_and_sub_intents(output: RouterOutput) -> tuple[str, list[str]]:
    """Return final intent and sub_intents shape from draft intent candidates."""
    sub_intents = final_sub_intents(output)
    intent = "compound" if len(sub_intents) > 1 else (sub_intents[0] if sub_intents else output.intent)
    if intent == "compound":
        sub_intents = [item for item in sub_intents if item not in {"compound", "out_of_scope"}]
    elif intent == "out_of_scope":
        sub_intents = ["out_of_scope"]
    else:
        sub_intents = [intent]
    return intent, sub_intents


def finalize_sub_intent_evidence(output: RouterOutput, sub_intents: list[str], question: str) -> list[SubIntentEvidence]:
    """Preserve draft sub-intent evidence and fill missing evidence records."""
    by_intent = {item.intent: item for item in output.sub_intent_evidence or []}
    items: list[SubIntentEvidence] = []
    for intent in sub_intents:
        item = by_intent.get(intent)  # type: ignore[arg-type]
        if item and (item.evidence or item.reason):
            items.append(item)
            continue
        items.append(
            SubIntentEvidence(
                intent=intent,  # type: ignore[arg-type]
                evidence=[question.strip()] if question.strip() else [],
                reason=rules.intent_reason(intent, []),
            )
        )
    return items


def finalize_scenario_decisions(
    output: RouterOutput,
    sub_intents: list[str],
    question: str,
    config: ResumeQAConfig,
) -> dict[str, ScenarioDecision]:
    """Keep legal draft scenarios and fill missing/illegal ones from rule fallback."""
    fallback = rule_scenario_decisions(question, output.model_copy(update={"sub_intent_candidates": sub_intents}), config)
    decisions: dict[str, ScenarioDecision] = {}
    for intent in sub_intents:
        decision = output.scenario_decisions.get(intent)
        if decision and decision.scenario in config.allowed_scenarios_for_intent(intent):
            decisions[intent] = decision
        else:
            decisions[intent] = fallback[intent]
    return decisions


def finalize_conditions(output: RouterOutput, intent: str):
    """Clear out_of_scope conditions and dedupe all other raw conditions."""
    return [] if intent == "out_of_scope" else rules.dedupe_rule_conditions(list(output.conditions or []))


def finalize_requires_jd(intent: str, sub_intents: list[str], config: ResumeQAConfig) -> bool:
    """Return final requires_jd from intent defaults."""
    return any(intent_default_bool(config, item, "requires_jd_criteria") for item in [intent, *sub_intents])


def finalize_requires_evidence(intent: str, sub_intents: list[str], question: str, config: ResumeQAConfig) -> bool:
    """Return final requires_evidence from evidence terms and intent defaults."""
    evidence_terms = rules.strings(((config.router_rules.get("compound_rules", {}) or {}).get("evidence_terms", []) or []))
    if rules.contains_any(question, evidence_terms):
        return True
    return any(intent_default_bool(config, item, "requires_evidence") for item in [intent, *sub_intents])


def finalize_allowed_tool_names(
    intent: str,
    scenario_decisions: dict[str, ScenarioDecision],
    config: ResumeQAConfig,
) -> list[str]:
    """Return tool names allowed for a single final intent.

    Compound and out_of_scope outputs keep this empty because downstream compiler
    resolves tools per sub-intent.
    """
    if intent in {"compound", "out_of_scope"}:
        return []
    scenario = scenario_decisions.get(intent)
    return config.allowed_tools_for_intent(intent, scenario.scenario if scenario else "")


def finalize_risk_flags(flags: list[str], config: ResumeQAConfig) -> list[str]:
    """Keep only configured router risk flag prefixes."""
    allowed = rules.strings(((config.router_rules.get("risk_flags", {}) or {}).get("allowed_prefixes", []) or []))
    if not allowed:
        return dedupe_risk_flags(flags)
    output: list[str] = []
    for value in dedupe_risk_flags(flags):
        if any(value == prefix or value.startswith(f"{prefix}:") for prefix in allowed):
            output.append(value)
    return output


def safe_out_of_scope(question: str, config: ResumeQAConfig, reason: str = "") -> RouterOutput:
    """Build a safe out_of_scope result when finalization itself fails."""
    output = RouterOutput(
        intent="out_of_scope",
        is_compound=False,
        sub_intent_candidates=["out_of_scope"],
        sub_intent_evidence=[
            SubIntentEvidence(
                intent="out_of_scope",
                evidence=[question],
                reason=rules.intent_reason("out_of_scope", [question], config),
            )
        ],
        scenario_decisions={
            "out_of_scope": ScenarioDecision(
                scenario="out_of_scope",
                confidence=1.0,
                evidence=[question] if question else [],
                reason=reason or "安全边界或非简历问答范围",
                source="rule_fallback",
            )
        },
        conditions=[],
        context_policy=ContextPolicy(),
        requires_jd=False,
        requires_evidence=False,
        allowed_tool_names=config.allowed_tools_for_intent("out_of_scope"),
        risk_flags=[],
    )
    flags = [f"router_finalizer_failed:{reason}"] if reason else []
    return output.model_copy(update={"risk_flags": flags})


def with_risk_flag(output: RouterOutput, flag: str) -> RouterOutput:
    """Append one router risk flag to a draft/result."""
    return output.model_copy(update={"risk_flags": dedupe_risk_flags([*output.risk_flags, flag])})


def intent_default_bool(config: ResumeQAConfig, intent: str, field: str) -> bool:
    """Read a boolean default from intents.yaml for one intent."""
    payload = ((config.intents.get("intents", {}) or {}).get(intent, {}) or {})
    return bool(payload.get(field, False))


def final_sub_intents(output: RouterOutput) -> list[str]:
    """Return deduped draft sub-intents before final shape normalization."""
    values = list(output.sub_intent_candidates or [])
    if not values and output.intent:
        values = [] if output.intent == "compound" else [output.intent]
    values = [str(item) for item in values if str(item).strip()]
    return rules.dedupe_rule_intents(values)


def dedupe_risk_flags(flags: list[str]) -> list[str]:
    """Dedupe risk flag strings while preserving order."""
    return rules.dedupe_rule_intents([value for raw in flags or [] if (value := str(raw or "").strip())])
