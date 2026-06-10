"""LLM RouterOutput draft construction.

Read this file after node.py when the pipeline uses LLM mode. It asks the LLM
for a complete RouterOutput draft, fixes payload shape, validates schema and
scenario contracts, then returns a draft for guard/finalizer stages.

This module does not apply hard guards, complete missing conditions, or compute
final authoritative fields such as allowed_tool_names.

中文阅读提示：
这个文件只负责 LLM draft 路径。LLM 应该产出完整 RouterOutput 草稿；
本文件会修正 JSON 形状、校验 schema 和 scenario 合同。它不做硬规则纠偏，
也不决定最终 allowed_tool_names / requires_jd / requires_evidence，这些交给
guard.py 和 finalizer.py。
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.llm import invoke_structured
from resume_query_ai_qa.core.llm.prompts import build_router_prompt
from resume_query_ai_qa.core.schemas import RouterOutput

from . import rules
from .finalizer import finalize_router_output, with_risk_flag


def build_llm_router_draft(question: str, config: ResumeQAConfig) -> RouterOutput:
    """Build a RouterOutput draft from the LLM or fall back to rule draft.

    Reads YAML: intents.yaml and scenarios.yaml through the prompt; router
    schema constraints through RouterOutput.
    Updates RouterOutput: all draft fields supplied by the LLM, except
    normalized_conditions/allowed_tool_names are reset for later stages.
    Does not: apply guards, complete conditions, or finalize derived fields.

    中文：
    LLM draft 的总入口。顺序是调用 LLM -> 转 dict -> 规整字段形状 ->
    校验 RouterOutput schema/scenario。任何一步失败都回退到规则 draft。
    """
    if not question:
        return rules.build_out_of_scope_draft(question, config)
    try:
        raw_payload = run_llm_router(question, config)
        coerced_payload = coerce_router_payload(raw_payload)
        normalized_payload = normalize_router_payload_shape(coerced_payload, config)
        return validate_router_payload_schema(normalized_payload, question, config)
    except Exception as error:
        return with_risk_flag(rules.build_rule_router_draft(question, config), build_llm_fallback_flag(error))


def run_llm_router(question: str, config: ResumeQAConfig) -> RouterOutput | dict[str, Any]:
    """Call the structured LLM router and return its raw payload.

    中文：
    真正调用结构化 LLM。prompt 里带 intents.yaml 和 scenarios.yaml 的可选项，
    让 LLM 按 RouterOutput schema 返回草稿。
    """
    prompt = build_router_prompt(
        question=question,
        intents=config.intents.get("intents", {}) or {},
        scenarios=config.scenario_catalog_for_router(),
    )
    return invoke_structured(RouterOutput, prompt, config=config)


def coerce_router_payload(payload: RouterOutput | dict[str, Any]) -> dict[str, Any]:
    """Coerce RouterOutput or dict payload into the dict shape validators expect.

    中文：
    把 LLM 返回值统一变成 dict，方便后续字段修形和 Pydantic 校验。
    """
    return payload.model_dump() if isinstance(payload, RouterOutput) else dict(payload or {})


def normalize_router_payload_shape(payload: dict[str, Any], config: ResumeQAConfig) -> dict[str, Any]:
    """Normalize LLM JSON shape without making business routing decisions.

    中文：
    这里只修“形状”，不重新理解问题。比如 intent 写成多个 token 时转成
    compound；conditions 不是 list 就置空；normalized_conditions 和
    allowed_tool_names 先清空，等后续节点/阶段权威生成。
    """
    output = dict(payload or {})
    valid_intents = set((config.intents.get("intents", {}) or {}).keys())
    raw_intent = output.get("intent", "")
    intent_tokens = extract_valid_intent_tokens(raw_intent, valid_intents)
    intent_tokens.extend(extract_valid_intent_tokens(output.get("sub_intent_candidates", []), valid_intents))
    intent_tokens = rules.dedupe_rule_intents([item for item in intent_tokens if item != "compound"])
    if len(intent_tokens) > 1:
        output["intent"] = "compound"
        output["is_compound"] = True
        output["sub_intent_candidates"] = intent_tokens
    elif intent_tokens:
        output["intent"] = intent_tokens[0]
        output["is_compound"] = False
        output["sub_intent_candidates"] = intent_tokens
    elif output.get("intent") not in valid_intents:
        output["intent"] = "candidate_filter"
        output["is_compound"] = False
        output["sub_intent_candidates"] = ["candidate_filter"]

    output["conditions"] = output.get("conditions") if isinstance(output.get("conditions"), list) else []
    output["normalized_conditions"] = []
    policy = output.get("context_policy") if isinstance(output.get("context_policy"), dict) else {}
    output["context_policy"] = {
        "uses_context": bool(policy.get("uses_context", False)),
        "context_ref_type": str(policy.get("context_ref_type", "none") or "none"),
        "evidence": policy.get("evidence", []) if isinstance(policy.get("evidence", []), list) else [],
        "reason": str(policy.get("reason", "")),
    }
    output.setdefault("sub_intent_evidence", [])
    if not isinstance(output["sub_intent_evidence"], list):
        output["sub_intent_evidence"] = []
    output["requires_jd"] = bool(output.get("requires_jd", False))
    output["requires_evidence"] = bool(output.get("requires_evidence", False))
    output["scenario_decisions"] = output.get("scenario_decisions") if isinstance(output.get("scenario_decisions"), dict) else {}
    output["allowed_tool_names"] = []
    output["risk_flags"] = output.get("risk_flags") if isinstance(output.get("risk_flags"), list) else []
    return output


def validate_router_payload_schema(payload: dict[str, Any], question: str, config: ResumeQAConfig) -> RouterOutput:
    """Validate RouterOutput schema and return rule fallback draft on contract failure.

    中文：
    校验 LLM 草稿是否真能成为 RouterOutput，以及 intent/scenario 是否在 YAML
    允许范围内。不合法就走规则 fallback，并写 risk_flag 记录原因。
    """
    try:
        output = RouterOutput.model_validate(payload)
    except (ValidationError, ValueError, TypeError) as error:
        fallback = finalize_router_output(rules.build_rule_router_draft(question, config), question, config)
        return with_risk_flag(fallback, f"router_schema_validation_failed:{type(error).__name__}: {str(error)[:120]}")
    valid_intents = set((config.intents.get("intents", {}) or {}).keys())
    if output.intent not in valid_intents:
        fallback = finalize_router_output(rules.build_rule_router_draft(question, config), question, config)
        return with_risk_flag(fallback, f"router_schema_validation_failed:invalid intent {output.intent}")
    scenario_error = validate_scenario_contract(output, config)
    if scenario_error:
        fallback = finalize_router_output(rules.build_rule_router_draft(question, config), question, config)
        return with_risk_flag(fallback, f"router_schema_validation_failed:{scenario_error}")
    return output


def validate_scenario_contract(output: RouterOutput, config: ResumeQAConfig) -> str:
    """Return a scenario contract error string, or empty when the draft is valid.

    中文：
    检查每个 intent 是否都有 scenario_decision，且 scenario 必须是该 intent
    在 scenarios.yaml 里允许的场景。
    """
    intents = output.sub_intent_candidates if output.intent == "compound" else [output.intent]
    for intent in intents:
        decision = output.scenario_decisions.get(str(intent))
        if decision is None:
            return f"missing scenario for intent {intent}"
        if decision.scenario not in config.allowed_scenarios_for_intent(str(intent)):
            return f"invalid scenario {decision.scenario} for intent {intent}"
    return ""


def build_llm_fallback_flag(error: Exception) -> str:
    """Build the audit flag attached when LLM routing falls back to rules.

    中文：
    生成审计标记，说明为什么 LLM 路径失败并回退到规则路径。
    """
    message = str(error).strip().replace("\n", " ")
    if len(message) > 180:
        message = message[:180] + "..."
    reason = f"{type(error).__name__}: {message}" if message else type(error).__name__
    return f"llm_router_fallback:{reason}"


def extract_valid_intent_tokens(value: Any, valid_intents: set[str]) -> list[str]:
    """Extract valid intent tokens from a string/list value supplied by the LLM.

    中文：
    从 LLM 可能混乱的 intent 字符串/list 中，只保留 YAML 定义过的合法 intent。
    """
    if isinstance(value, list):
        raw_values = [str(item).strip() for item in value]
    else:
        raw_values = [token.strip() for token in re.split(r"[,，/|;；\s]+", str(value or "")) if token.strip()]
    return [item for item in raw_values if item in valid_intents]
