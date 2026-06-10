"""RouterOutput authoritative finalization.

Read this file after conditions.py. LLM/rule draft values are not authoritative:
this module recomputes the final RouterOutput contract from the draft, question,
and YAML config.

This module does not reinterpret natural language from scratch. It preserves
legal draft decisions when possible and fills/repairs derived fields.

中文阅读提示：
这个文件是 RouterOutput 的“权威收口层”。前面的 LLM/rule/guard 都只是草稿
或纠偏提示；最终 intent/is_compound/sub_intents/scenario/requires_* /
allowed_tool_names/risk_flags 都在这里统一整理。它不从零重新理解自然语言，
只基于草稿、问题文本和 YAML 配置做确定性收口。

阅读顺序：
1. finalize_router_output
2. Shape 收口：RouterOutput 自身结构要自洽
3. Contract 收口：scenario/tool 必须符合 YAML 合同
4. Derived Flags 收口：requires_* / risk_flags 等派生字段统一重算
5. Safety helpers：finalizer 失败时安全降级
"""

from __future__ import annotations

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.rules.execution_policy_rules import rule_scenario_decisions
from resume_query_ai_qa.core.schemas import ContextPolicy, RouterOutput, ScenarioDecision, SubIntentEvidence

from . import rules


def finalize_router_output(output: RouterOutput, question: str, config: ResumeQAConfig) -> RouterOutput:
    """Stage 5: recompute final RouterOutput fields in three readable groups.

    Reads YAML: intents.yaml for requires_jd/requires_evidence defaults,
    scenarios.yaml for scenario legality/fallback, tool_policy.yaml for
    allowed_tool_names, router_rules.yaml for evidence terms and risk flags.
    Updates RouterOutput: intent/is_compound/sub_intents/evidence/scenarios/
    conditions/requires flags/tool names/risk flags.
    Does not: create normalized_conditions or tool calls.

    中文：
    router 第 5 阶段。按三段式收口最终值：
    1. Shape = 结构收口，保证 RouterOutput 内部字段自洽。
    2. Contract = 配置合同收口，保证 scenario/tool 符合 YAML。
    3. Derived Flags = 派生字段收口，统一重算 requires_* 和 risk_flags。
    """
    shape = finalize_router_shape(output, question)
    contract = finalize_router_contract(output, shape, question, config)
    derived = finalize_router_derived_flags(output, shape, question, config)
    return output.model_copy(update={**shape, **contract, **derived})


def finalize_router_shape(output: RouterOutput, question: str) -> dict[str, object]:
    """Finalize RouterOutput structure fields.

    Shape means internal object consistency: intent, is_compound, sub-intents,
    evidence records, and raw conditions must agree with each other.

    中文：
    Shape = 结构收口。这里只修 RouterOutput 自身形状，不检查 scenario/tool 合同，
    也不计算 requires_* 派生字段。
    """
    intent, sub_intents = finalize_intent_and_sub_intents(output)
    return {
        "intent": intent,
        "is_compound": intent == "compound",
        "sub_intent_candidates": sub_intents,
        "sub_intent_evidence": finalize_sub_intent_evidence(output, sub_intents, question),
        "conditions": finalize_conditions(output, intent),
        "normalized_conditions": [],
    }


def finalize_intent_and_sub_intents(output: RouterOutput) -> tuple[str, list[str]]:
    """Return final intent and sub_intents shape from draft intent candidates.

    中文：
    根据 draft 的 sub_intent_candidates 决定最终 intent：多个就是 compound，
    一个就是单 intent，out_of_scope 单独收口。
    """
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
    """Preserve draft sub-intent evidence and fill missing evidence records.

    中文：
    保留草稿里的 sub_intent_evidence；缺失的子 intent 用原问题补一条证据记录。
    """
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


def finalize_conditions(output: RouterOutput, intent: str):
    """Clear out_of_scope conditions and dedupe all other raw conditions.

    中文：
    out_of_scope 清空条件；其他 intent 对 raw conditions 去重。
    """
    return [] if intent == "out_of_scope" else rules.dedupe_rule_conditions(list(output.conditions or []))


def final_sub_intents(output: RouterOutput) -> list[str]:
    """Return deduped draft sub-intents before final shape normalization.

    中文：
    从 draft 里拿 sub_intents 并去重，是 finalize_intent_and_sub_intents 的输入。
    """
    values = list(output.sub_intent_candidates or [])
    if not values and output.intent:
        values = [] if output.intent == "compound" else [output.intent]
    values = [str(item) for item in values if str(item).strip()]
    return rules.dedupe_rule_intents(values)


def finalize_router_contract(
    output: RouterOutput,
    shape: dict[str, object],
    question: str,
    config: ResumeQAConfig,
) -> dict[str, object]:
    """Finalize YAML contract fields.

    Contract means scenario/tool legality: scenarios must be allowed by
    scenarios.yaml, and tool names must come from tool_policy.yaml.

    中文：
    Contract = 配置合同收口。这里只处理 scenario_decisions 和 allowed_tool_names：
    合法 draft scenario 保留；缺失/非法 scenario 用 resolution_rules 补齐；
    单 intent 的工具白名单从 tool_policy.yaml 读取。
    """
    intent = str(shape["intent"])
    sub_intents = [str(item) for item in list(shape["sub_intent_candidates"])]
    scenario_decisions = finalize_scenario_decisions(output, sub_intents, question, config)
    return {
        "scenario_decisions": scenario_decisions,
        "allowed_tool_names": finalize_allowed_tool_names(intent, scenario_decisions, config),
    }


def finalize_scenario_decisions(
    output: RouterOutput,
    sub_intents: list[str],
    question: str,
    config: ResumeQAConfig,
) -> dict[str, ScenarioDecision]:
    """Keep legal draft scenarios and fill missing/illegal ones from rule fallback.

    中文：
    合法的 LLM/rule scenario 保留；缺失或非法的，用 execution_policy_rules 里的
    rule_scenario_decisions 按 YAML 规则补齐。
    """
    fallback = rule_scenario_decisions(question, output.model_copy(update={"sub_intent_candidates": sub_intents}), config)
    decisions: dict[str, ScenarioDecision] = {}
    for intent in sub_intents:
        decision = output.scenario_decisions.get(intent)
        if decision and decision.scenario in config.allowed_scenarios_for_intent(intent):
            decisions[intent] = decision
        else:
            decisions[intent] = fallback[intent]
    return decisions


def finalize_allowed_tool_names(
    intent: str,
    scenario_decisions: dict[str, ScenarioDecision],
    config: ResumeQAConfig,
) -> list[str]:
    """Return tool names allowed for a single final intent.

    Compound and out_of_scope outputs keep this empty because downstream compiler
    resolves tools per sub-intent.

    中文：
    单 intent 时从 tool_policy/scenario 取允许工具。compound 和 out_of_scope 保持空，
    因为后续 compiler 会按每个 sub_intent 再解析工具。
    """
    if intent in {"compound", "out_of_scope"}:
        return []
    scenario = scenario_decisions.get(intent)
    return config.allowed_tools_for_intent(intent, scenario.scenario if scenario else "")


def finalize_router_derived_flags(
    output: RouterOutput,
    shape: dict[str, object],
    question: str,
    config: ResumeQAConfig,
) -> dict[str, object]:
    """Finalize derived boolean flags and audit flags.

    Derived flags are not trusted from the draft because LLM/rule/guard may all
    touch them. This group recomputes them from final shape plus YAML defaults.

    中文：
    Derived Flags = 派生字段收口。这里只重算 requires_jd、requires_evidence、
    risk_flags，不再改变 intent/scenario/tool。
    """
    intent = str(shape["intent"])
    sub_intents = [str(item) for item in list(shape["sub_intent_candidates"])]
    return {
        "requires_jd": finalize_requires_jd(intent, sub_intents, config),
        "requires_evidence": finalize_requires_evidence(intent, sub_intents, question, config),
        "risk_flags": finalize_risk_flags(output.risk_flags, config),
    }


def finalize_requires_jd(intent: str, sub_intents: list[str], config: ResumeQAConfig) -> bool:
    """Return final requires_jd from intent defaults.

    中文：
    从 intents.yaml 的 requires_jd_criteria 默认值计算最终 requires_jd。
    """
    return any(intent_default_bool(config, item, "requires_jd_criteria") for item in [intent, *sub_intents])


def finalize_requires_evidence(intent: str, sub_intents: list[str], question: str, config: ResumeQAConfig) -> bool:
    """Return final requires_evidence from evidence terms and intent defaults.

    中文：
    如果问题命中证据词，直接需要证据；否则看 intents.yaml 的 requires_evidence 默认值。
    """
    evidence_terms = rules.strings(((config.router_rules.get("compound_rules", {}) or {}).get("evidence_terms", []) or []))
    if rules.contains_any(question, evidence_terms):
        return True
    return any(intent_default_bool(config, item, "requires_evidence") for item in [intent, *sub_intents])


def finalize_risk_flags(flags: list[str], config: ResumeQAConfig) -> list[str]:
    """Keep only configured router risk flag prefixes.

    中文：
    清理 risk_flags，只保留 router_rules.yaml 允许的前缀，避免乱标记继续传递。
    """
    allowed = rules.strings(((config.router_rules.get("risk_flags", {}) or {}).get("allowed_prefixes", []) or []))
    if not allowed:
        return dedupe_risk_flags(flags)
    output: list[str] = []
    for value in dedupe_risk_flags(flags):
        if any(value == prefix or value.startswith(f"{prefix}:") for prefix in allowed):
            output.append(value)
    return output


def intent_default_bool(config: ResumeQAConfig, intent: str, field: str) -> bool:
    """Read a boolean default from intents.yaml for one intent.

    中文：
    从 intents.yaml 某个 intent 下读取布尔默认值。
    """
    payload = ((config.intents.get("intents", {}) or {}).get(intent, {}) or {})
    return bool(payload.get(field, False))


def dedupe_risk_flags(flags: list[str]) -> list[str]:
    """Dedupe risk flag strings while preserving order.

    中文：
    risk flag 去重，保留原顺序。
    """
    return rules.dedupe_rule_intents([value for raw in flags or [] if (value := str(raw or "").strip())])


def safe_out_of_scope(question: str, config: ResumeQAConfig, reason: str = "") -> RouterOutput:
    """Build a safe out_of_scope result when finalization itself fails.

    中文：
    finalizer 自己失败时使用的安全兜底结果。
    """
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
    """Append one router risk flag to a draft/result.

    中文：
    给草稿或结果追加一个 risk_flag，并去重。
    """
    return output.model_copy(update={"risk_flags": dedupe_risk_flags([*output.risk_flags, flag])})
