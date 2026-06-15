"""YAML-driven QueryFrame classification for Aggregator.

这个文件负责什么：
  根据 QueryPlan、ToolResult、scenario 和 aggregator_tasks.yaml 判断回答任务类型。

应该从哪个函数读起：
  build_query_frame() -> classify_task_type() -> extract_slots()。

不会负责什么：
  不选 answer layout，不生成答案文本，不读取工具之外的事实。
"""

from __future__ import annotations

import re
from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.rules.execution_policy_rules import scenario_for_intent
from resume_query_ai_qa.core.inspection.plan_inspection import plan_intent_calls
from resume_query_ai_qa.core.schemas import ExecutionDecision, QueryPlan, RouterOutput, ToolResult


def build_query_frame(
    question: str,
    plan: QueryPlan,
    tool_results: list[ToolResult],
    config: ResumeQAConfig,
    *,
    execution_decision: ExecutionDecision | None = None,
    router_output: RouterOutput | None = None,
) -> dict[str, Any]:
    """构建 aggregator 的 QueryFrame，作为 layout 选择和 LLM payload 的任务描述。"""
    intents = _plan_intents(plan)
    scenarios = _scenarios_for_intents(intents, execution_decision, router_output)
    ok_tools = _successful_tools(tool_results)
    task = classify_task_type(question, intents, scenarios, ok_tools, config)
    slots = extract_slots(question, router_output=router_output, tool_results=tool_results, task_type=task["task_type"])
    return {
        "question": question,
        "intents": intents,
        "scenarios": scenarios,
        "successful_tools": sorted(ok_tools),
        **task,
        "slots": slots,
    }


def classify_task_type(
    question: str,
    intents: list[str],
    scenarios: dict[str, str],
    ok_tools: set[str],
    config: ResumeQAConfig,
) -> dict[str, Any]:
    """按 aggregator_tasks.yaml 的优先级规则匹配 task_type。"""
    rules = config.aggregator_task_rules()
    ordered = sorted(
        ((name, dict(rule or {})) for name, rule in rules.items() if isinstance(rule, dict)),
        key=lambda item: int(item[1].get("priority", 0) or 0),
        reverse=True,
    )
    for name, rule in ordered:
        if name == "open_grounded_answer":
            continue
        reason = _match_task_rule(question, intents, scenarios, ok_tools, rule)
        if reason:
            return {
                "task_type": name,
                "freedom_level": resolve_freedom_level(rule),
                "default_layout": str(rule.get("default_layout") or "default"),
                "matched_rule": name,
                "match_reason": reason,
            }
    fallback = dict(rules.get("open_grounded_answer", {}) or {})
    return {
        "task_type": "open_grounded_answer",
        "freedom_level": resolve_freedom_level(fallback) or "open_limited",
        "default_layout": str(fallback.get("default_layout") or "default"),
        "matched_rule": "open_grounded_answer",
        "match_reason": "fallback_no_task_rule_matched",
    }


def extract_slots(
    question: str,
    *,
    router_output: RouterOutput | None = None,
    tool_results: list[ToolResult] | None = None,
    task_type: str = "",
) -> dict[str, Any]:
    """提取槽位集合并返回。"""
    slots: dict[str, Any] = {}
    conditions = list((router_output.normalized_conditions if router_output else []) or [])
    displays = _display_conditions(conditions)
    if displays:
        slots["target_conditions"] = displays
        slots["fact_check_target"] = "、".join(displays)
    count = _question_count(question)
    if count:
        slots["question_count"] = count
        if task_type == "candidate_decision_answer":
            slots["ranking_output_limit"] = count
    candidate_names = _candidate_names_from_results(tool_results or [])
    if candidate_names:
        slots["candidate_count"] = len(candidate_names)
        slots["candidate_names"] = candidate_names
    if task_type == "candidate_comparison_answer":
        slots.setdefault("candidate_count", 2)
    return slots


def _display_conditions(conditions) -> list[str]:
    """获取展示条件集合并返回。"""
    output: list[str] = []
    for item in conditions:
        if getattr(item, "type", "") == "candidate_name":
            continue
        value = str(getattr(item, "normalized_value", "") or getattr(item, "raw_value", "") or "").strip()
        if not value or len(value) > 30 or " " in value:
            continue
        if value not in output:
            output.append(value)
    return output


def resolve_freedom_level(rule: dict[str, Any]) -> str:
    """解析自由度级别并返回。"""
    return str(rule.get("freedom_level") or "").strip()


def _match_task_rule(
    question: str,
    intents: list[str],
    scenarios: dict[str, str],
    ok_tools: set[str],
    rule: dict[str, Any],
) -> str:
    """匹配结果任务规则并返回匹配结果。"""
    expected_intents = {str(item) for item in list(rule.get("intents_any", []) or []) if str(item).strip()}
    if expected_intents and not (expected_intents & set(intents)):
        return ""
    expected_scenarios = {str(item) for item in list(rule.get("scenarios_any", []) or []) if str(item).strip()}
    if expected_scenarios and not (expected_scenarios & set(scenarios.values())):
        return ""
    required = dict(rule.get("required_tools", {}) or {})
    all_tools = {str(item) for item in list(required.get("all", []) or []) if str(item).strip()}
    any_tools = {str(item) for item in list(required.get("any", []) or []) if str(item).strip()}
    if all_tools and not all_tools <= ok_tools:
        return ""
    if any_tools and not (any_tools & ok_tools):
        return ""
    terms = [str(item) for item in list(rule.get("trigger_terms_any", []) or []) if str(item).strip()]
    if terms and not any(term in question for term in terms):
        return ""
    parts = []
    if expected_intents:
        parts.append("intent")
    if expected_scenarios:
        parts.append("scenario")
    if all_tools or any_tools:
        parts.append("tools")
    if terms:
        parts.append("terms")
    return "matched_" + "_".join(parts or ["default"])


def _plan_intents(plan: QueryPlan) -> list[str]:
    """获取计划意图集合并返回。"""
    if plan.intent == "compound":
        return [intent for intent, _calls in plan_intent_calls(plan)]
    return [plan.intent]


def _scenarios_for_intents(
    intents: list[str],
    execution_decision: ExecutionDecision | None,
    router_output: RouterOutput | None,
) -> dict[str, str]:
    """根据意图集合生成场景集合并返回。"""
    scenarios = dict((execution_decision.scenarios if execution_decision else {}) or {})
    for intent in intents:
        scenarios.setdefault(intent, scenario_for_intent(router_output, intent))
    return scenarios


def _successful_tools(tool_results: list[ToolResult]) -> set[str]:
    """获取成功项工具集合并返回。"""
    return {result.tool_name for result in tool_results if result.ok}


def _question_count(question: str) -> int | None:
    """获取问题数量并返回。"""
    match = re.search(r"(\d+)\s*个", str(question or ""))
    if match:
        return int(match.group(1))
    top_match = re.search(r"(?:前|top|Top|TOP)\s*(\d+)\s*(?:名|位)?", str(question or ""))
    if top_match:
        return int(top_match.group(1))
    zh = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    for key, value in zh.items():
        if f"{key}个" in question or f"{key}位" in question or f"前{key}名" in question or f"前{key}位" in question:
            return value
    return None


def _candidate_names_from_results(tool_results: list[ToolResult]) -> list[str]:
    """从结果集合提取候选人名称集合并返回。"""
    names: list[str] = []
    for result in tool_results:
        if not result.ok:
            continue
        _collect_names(result.data, names)
    return names[:20]


def _collect_names(value: Any, names: list[str]) -> None:
    """收集名称集合并返回。"""
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, dict):
        name = str(value.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
        for item in value.values():
            _collect_names(item, names)
    elif isinstance(value, list):
        for item in value:
            _collect_names(item, names)
