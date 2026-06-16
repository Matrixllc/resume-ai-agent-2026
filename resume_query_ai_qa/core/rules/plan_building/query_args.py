"""Query and argument normalization for plan construction."""

from __future__ import annotations

import re
from typing import Any

from resume_query_ai_qa.core.config import load_config
from resume_query_ai_qa.core.rules.condition_rules import cleaned_retrieval_query, filter_arguments_from_conditions
from resume_query_ai_qa.core.rules.context_resolver import candidate_ids_for_context
from resume_query_ai_qa.core.rules.session_context import sanitize_session_context as sanitize_context_facts
from resume_query_ai_qa.core.schemas import RouterOutput


def tool_query(question: str, intent: str, router_output: RouterOutput) -> str:
    """获取工具查询并返回。"""
    fallback = strip_intent_scaffolding(question, intent)
    return cleaned_retrieval_query(router_output.normalized_conditions, fallback=fallback)


def filter_args(question: str, router_output: RouterOutput, session_context: dict | None = None) -> dict[str, Any]:
    """获取筛选args并返回。"""
    args = filter_arguments_from_conditions(router_output.normalized_conditions, question)
    return with_context_candidate_ids(args, router_output, session_context)


def preference_filter_args(question: str, router_output: RouterOutput, session_context: dict | None = None) -> dict[str, Any]:
    """把 preference_target 按当前 filter 场景降级为结构化筛选参数。"""
    args = filter_arguments_from_conditions(router_output.normalized_conditions, question, include_preference_targets=True)
    return with_context_candidate_ids(args, router_output, session_context)


def ranking_filter_args(question: str, router_output: RouterOutput, session_context: dict | None = None) -> dict[str, Any]:
    """获取排序候选池筛选参数，领域岗位可入池，技能/概念岗位仅作评分目标。"""
    args = filter_arguments_from_conditions(
        router_output.normalized_conditions,
        question,
        include_preference_domains=True,
    )
    return with_context_candidate_ids(args, router_output, session_context)


def preference_recall_query(question: str, router_output: RouterOutput) -> str:
    """为 open_recall 构建 query，优先使用 preference_target 条件。"""
    terms: list[str] = []
    for condition in router_output.normalized_conditions:
        matched_by = str(getattr(condition, "matched_by", "") or "")
        if not matched_by.startswith("preference_target:"):
            continue
        terms.extend(str(item) for item in (condition.retrieval_terms or []) if str(item).strip())
        value = str(getattr(condition, "normalized_value", "") or getattr(condition, "raw_value", "") or "").strip()
        if value:
            terms.append(value)
    if terms:
        return " ".join(dict.fromkeys(terms)).strip()
    return tool_query(question, "candidate_filter", router_output)


def ranking_target_text(question: str, router_output: RouterOutput) -> str:
    """Extract the job/role target text used for JD standards selection."""
    values: list[str] = []
    for condition in router_output.normalized_conditions:
        condition_type = str(getattr(condition, "type", "") or "")
        matched_by = str(getattr(condition, "matched_by", "") or "")
        if condition_type == "ranking_target":
            continue
        if condition_type in {"domain", "skill", "concept", "job_intent"} or matched_by.startswith("preference_target"):
            value = str(getattr(condition, "normalized_value", "") or getattr(condition, "raw_value", "") or "").strip()
            if value and value not in values:
                values.append(value)
    return " ".join(values)


def ranking_output_limit(question: str) -> int | None:
    """Extract an explicit ranking display limit from the current question."""
    text = str(question or "")
    match = re.search(r"(?:前|top|Top|TOP)\s*(\d+)\s*(?:名|位)?", text)
    if match:
        return int(match.group(1))
    zh = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    for key, value in zh.items():
        if f"前{key}名" in text or f"前{key}位" in text:
            return value
    return None


def evidence_scope_from_question(question: str) -> str:
    """从用户问题中推断 evidence scope。"""
    text = normalize_spaces(question)
    if re.search(r"(工作信息|工作经历|工作内容|工作经验|任职|公司内|职责)", text):
        return "work"
    if re.search(r"(项目信息|项目经历|项目经验|项目内容|项目过程|项目成果)", text):
        return "project"
    if re.search(r"(简历经历|技术经历|相关经历|经历)", text):
        return "both"
    return "both"


def with_context_candidate_ids(args: dict[str, Any], router_output: RouterOutput, session_context: dict | None) -> dict[str, Any]:
    """向筛选参数补充上下文候选人标识并返回。"""
    candidate_ids = candidate_ids_for_context(router_output.context_policy, session_context)
    return {**args, **({"candidate_ids": candidate_ids} if candidate_ids else {})}


def candidate_reference_text(question: str, router_output: RouterOutput) -> str:
    """获取候选人引用文本并返回。"""
    names = sorted({
        _clean_candidate_reference_value(condition.normalized_value or condition.raw_value)
        for condition in router_output.normalized_conditions
        if condition.type == "candidate_name"
    })
    return " ".join(str(name) for name in names if str(name).strip()) or strip_dialog_context(question)


def _clean_candidate_reference_value(value: str) -> str:
    """从候选引用文本中优先提取真实候选人姓名。"""
    from resume_query_ai_qa.core.data_access import list_known_candidate_names

    text = str(value or "").strip()
    names = [name for name in list_known_candidate_names() if name and name in text]
    return " ".join(sorted(names)) if names else text


def sanitize_session_context(value: dict | None) -> dict[str, Any]:
    """清理会话上下文并返回。"""
    return sanitize_context_facts(value)


def strip_dialog_context(question: str) -> str:
    """移除对话上下文并返回。"""
    return _strip_configured_terms(question, "dialog_scaffolding")


def strip_intent_scaffolding(question: str, intent: str) -> str:
    """移除意图引导词并返回。"""
    return _strip_configured_terms(question, "intent_scaffolding")


def _strip_configured_terms(question: str, key: str) -> str:
    """移除配置化词项集合并返回。"""
    cleaning = dict(load_config().condition_rules.get("cleaning", {}) or {})
    terms = [str(item) for item in list(cleaning.get(key, []) or []) if str(item)]
    if not terms:
        return normalize_spaces(question)
    pattern = "|".join(re.escape(item) for item in sorted(terms, key=len, reverse=True))
    return normalize_spaces(re.sub(pattern, " ", str(question or "")))


def normalize_spaces(value: str) -> str:
    """标准化空白并返回。"""
    return " ".join(str(value or "").split())
