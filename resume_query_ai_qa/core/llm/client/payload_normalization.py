"""Normalize common local-LLM JSON shape drift.

These helpers only repair transport/schema shape issues before Pydantic
validation. They must not infer business meaning, choose tools, or replace
router/compiler/validator rules.
"""

from __future__ import annotations

import re
from typing import Any, Type, TypeVar

from pydantic import BaseModel


SchemaT = TypeVar("SchemaT", bound=BaseModel)


def normalize_schema_payload(schema: Type[SchemaT], payload: dict[str, Any]) -> dict[str, Any]:
    """标准化schema载荷并返回。"""
    if schema.__name__ == "SemanticPlan":
        return _normalize_semantic_plan_payload(payload)
    if schema.__name__ != "RouterOutput":
        return payload
    valid_intents = {
        "candidate_count",
        "candidate_list",
        "candidate_filter",
        "candidate_profile_intro",
        "candidate_compare_pair",
        "candidate_ranking",
        "jd_scoring",
        "evidence_question",
        "interview_question_generation",
        "follow_up",
        "compound",
        "out_of_scope",
    }
    output = dict(payload)
    intent_tokens = _intent_tokens(output.get("intent", ""), valid_intents)
    existing_subs = output.get("sub_intent_candidates", [])
    if isinstance(existing_subs, str):
        existing_subs = _split_intent_tokens(existing_subs)
    if isinstance(existing_subs, list):
        intent_tokens.extend(str(item).strip() for item in existing_subs)
    intent_tokens = _dedupe([token for token in intent_tokens if token in valid_intents and token != "compound"])
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
    output["sub_intent_evidence"] = _normalize_sub_intent_evidence(
        output.get("sub_intent_candidates", []) or [],
        output.get("sub_intent_evidence", []),
    )
    conditions = output.get("conditions", [])
    output["conditions"] = conditions if isinstance(conditions, list) else []
    normalized_conditions = output.get("normalized_conditions", [])
    output["normalized_conditions"] = normalized_conditions if isinstance(normalized_conditions, list) else []
    output["context_policy"] = _normalize_context_policy(output.get("context_policy", {}))
    output.setdefault("requires_jd", False)
    output.setdefault("requires_evidence", False)
    output.setdefault("allowed_tool_names", [])
    output.setdefault("risk_flags", [])
    return output


def _normalize_semantic_plan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """标准化语义计划载荷并返回。"""
    output = dict(payload)
    output["normalized_conditions"] = _normalize_condition_items(output.get("normalized_conditions", []))
    steps = output.get("steps", [])
    normalized_steps = []
    if isinstance(steps, list):
        for item in steps:
            if not isinstance(item, dict):
                continue
            step = dict(item)
            step["conditions"] = _normalize_condition_items(step.get("conditions", []))
            normalized_steps.append(step)
    output["steps"] = normalized_steps
    return output


def _normalize_condition_items(items: Any) -> list[dict[str, Any]]:
    """标准化条件条目集合并返回。"""
    if not isinstance(items, list):
        return []
    output: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        condition = dict(item)
        for key in ("type", "raw_value", "normalized_value", "evidence", "matched_by"):
            value = condition.get(key, "")
            if isinstance(value, list):
                value = " ".join(str(part) for part in value if str(part).strip())
            condition[key] = str(value or "")
        terms = condition.get("retrieval_terms", [])
        if isinstance(terms, str):
            terms = [terms]
        condition["retrieval_terms"] = [str(term) for term in terms] if isinstance(terms, list) else []
        try:
            condition["confidence"] = float(condition.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            condition["confidence"] = 0.0
        output.append(condition)
    return output


def _intent_tokens(raw_intent: Any, valid_intents: set[str]) -> list[str]:
    """获取意图tokens并返回。"""
    if isinstance(raw_intent, list):
        return [str(item).strip() for item in raw_intent]
    raw = str(raw_intent or "").strip()
    if raw in valid_intents:
        return [raw]
    return _split_intent_tokens(raw)


def _split_intent_tokens(value: str) -> list[str]:
    """拆分意图tokens并返回。"""
    return [token.strip() for token in re.split(r"[,，/|;；\s]+", value) if token.strip()]


def _normalize_sub_intent_evidence(intents: list[str], evidence_items: Any) -> list[dict[str, Any]]:
    """标准化子意图证据并返回。"""
    if not isinstance(evidence_items, list):
        evidence_items = []
    normalized_evidence = []
    for intent in intents:
        matched = next((item for item in evidence_items if isinstance(item, dict) and item.get("intent") == intent), None)
        normalized_evidence.append(
            {
                "intent": intent,
                "evidence": list(matched.get("evidence", [])) if matched and isinstance(matched.get("evidence"), list) else [],
                "reason": str(matched.get("reason", "")) if matched else "",
            }
        )
    return normalized_evidence


def _normalize_context_policy(value: Any) -> dict[str, Any]:
    """标准化上下文策略并返回。"""
    context_policy = value if isinstance(value, dict) else {}
    return {
        "uses_context": bool(context_policy.get("uses_context", False)),
        "context_ref_type": str(context_policy.get("context_ref_type", "none") or "none"),
        "evidence": context_policy.get("evidence", []) if isinstance(context_policy.get("evidence", []), list) else [],
        "reason": str(context_policy.get("reason", "")),
    }


def _dedupe(values: list[str]) -> list[str]:
    """去重结果并返回。"""
    output: list[str] = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
