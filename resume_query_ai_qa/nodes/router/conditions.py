"""Router question cleanup and raw condition completion.

Read this file after node.py. It owns only two router stages:
preprocess_router_question and complete_router_conditions.

This module only creates or completes QueryCondition items. It does not create
NormalizedCondition values; that belongs to the later condition_normalizer node.

中文阅读提示：
这个文件只做两件事：清理用户问题、补 raw QueryCondition。
它不会生成 normalized_conditions，也不会生成工具参数；NormalizedCondition 属于
后面的 condition_normalizer node。
"""

from __future__ import annotations

import re

from resume_query_ai_qa.core.rules.condition_rules import extract_conditions
from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.schemas import RouterOutput, SubIntentEvidence

from .finalizer import with_risk_flag
from . import rules


def preprocess_router_question(question: str, config: ResumeQAConfig) -> str:
    """Stage 1: lightly clean the user question before routing.

    Reads YAML: router_rules.yaml.preprocess.
    Updates RouterOutput: none.
    Does not: rewrite entities, infer intent, or extract tool arguments.

    中文：
    router 第 1 阶段。只做轻量清理：标点归一、去掉开头口头填充词、压缩空格。
    不改实体、不判断 intent、不抽工具参数。
    """
    text = str(question or "").strip()
    if not text:
        return ""
    if bool((config.router_rules.get("preprocess", {}) or {}).get("normalize_punctuation", True)):
        text = normalize_router_punctuation(text)
    for filler in rules.strings((config.router_rules.get("preprocess", {}) or {}).get("filler_terms", [])):
        text = re.sub(rf"^\s*{re.escape(filler)}[，,。.!！?\s]*", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def complete_router_conditions(output: RouterOutput, question: str, config: ResumeQAConfig | None = None) -> RouterOutput:
    """Stage 4: complete raw conditions missed by the draft stage.

    Reads YAML: condition_rules.yaml and shared_taxonomy through
    extract_conditions; candidate mentions through the router signal helpers.
    Updates RouterOutput: conditions, normalized_conditions=[], risk_flags.
    Does not: normalize conditions or build tool arguments.

    中文：
    router 第 4 阶段。把 draft 漏掉的 domain/skill/major/candidate_name 等
    raw condition 补回来。这里仍然保持 normalized_conditions=[]。
    """
    if output.intent == "out_of_scope":
        return output.model_copy(update={"conditions": [], "normalized_conditions": []})
    try:
        conditions = list(output.conditions or [])
        extracted = extract_conditions(question)
        if rules.looks_like_candidate_reference(question):
            conditions = [item for item in conditions if item.type != "candidate_name"]
            extracted = [item for item in extracted if item.type != "candidate_name"]
            extracted.extend(rules.candidate_reference_conditions(question))
        before = {(item.type, item.raw_value) for item in conditions}
        merged = rules.dedupe_rule_conditions([*conditions, *extracted])
        after = {(item.type, item.raw_value) for item in merged}
        flags = list(output.risk_flags or [])
        if after - before:
            flags.append("condition_completion_applied")
        return output.model_copy(update={"conditions": merged, "normalized_conditions": [], "risk_flags": rules.dedupe_rule_intents(flags)})
    except Exception as error:
        return with_risk_flag(output, f"condition_completion_failed:{type(error).__name__}: {str(error)[:120]}")


def normalize_router_punctuation(text: str) -> str:
    """Normalize punctuation that affects matching, without changing meaning.

    中文：
    只统一会影响规则匹配的中英文标点，不改变问题语义。
    """
    return (
        text.replace("？", "?")
        .replace("！", "!")
        .replace("，", ",")
        .replace("。", ".")
        .replace("；", ";")
        .replace("：", ":")
    )
