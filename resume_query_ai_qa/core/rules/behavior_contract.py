"""Shared production contracts consumed by runtime nodes and benchmarks."""

from __future__ import annotations

from typing import Iterable

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.schemas import RouterOutput, ValidationIssue


def router_intents(router_output: RouterOutput) -> list[str]:
    """获取路由意图集合并返回。"""
    if router_output.intent == "compound":
        return [str(item) for item in router_output.sub_intent_candidates]
    return [str(router_output.intent)]


def tool_contract(config: ResumeQAConfig, intent: str, scenario: str = "") -> dict[str, list[str]]:
    """获取工具合同并返回。"""
    return {
        "preferred": config.preferred_tools_for_scenario(intent, scenario),
        "allowed": config.allowed_tools_for_intent(intent, scenario),
        "forbidden": config.forbidden_tools_for_scenario(intent, scenario),
    }


def produced_artifacts(config: ResumeQAConfig, tool_names: Iterable[str]) -> list[str]:
    """获取produced产物集合并返回。"""
    tools = dict(config.tool_policy.get("tools", {}) or {})
    artifacts: list[str] = []
    for name in tool_names:
        artifacts.extend(str(item) for item in list(dict(tools.get(str(name), {}) or {}).get("produces", []) or []))
    return list(dict.fromkeys(artifacts))


def validation_issue(message: str, phase: str) -> ValidationIssue:
    """获取校验issue并返回。"""
    text = str(message)
    lower = text.lower()
    for raw in list(load_config().validation.get("legacy_issue_classifiers", []) or []):
        rule = dict(raw or {})
        contains_all = [str(item).lower() for item in list(rule.get("contains_all", []) or [])]
        contains_any = [str(item).lower() for item in list(rule.get("contains_any", []) or [])]
        prefixes = [str(item).lower() for item in list(rule.get("prefixes", []) or [])]
        if contains_all and not all(item in lower for item in contains_all):
            continue
        if contains_any and not any(item in lower for item in contains_any):
            continue
        if prefixes and not any(lower.startswith(item) for item in prefixes):
            continue
        if not (contains_all or contains_any or prefixes):
            continue
        return ValidationIssue(
            category=str(rule.get("category") or phase),
            code=str(rule.get("code") or f"{phase}_contract"),
            message=text,
            repairable=bool(rule.get("repairable", True)),
        )
    return ValidationIssue(category=phase, code=f"{phase}_contract", message=text)


def validation_issues(messages: Iterable[str], phase: str) -> list[ValidationIssue]:
    """获取校验issues并返回。"""
    return [validation_issue(message, phase) for message in messages]


def validation_action(config: ResumeQAConfig, issues: Iterable[ValidationIssue], phase: str) -> dict[str, str]:
    """获取校验动作并返回。"""
    rules = dict(config.validation.get("issue_actions", {}) or {})
    defaults = dict(rules.get("defaults", {}) or {})
    by_code = dict(rules.get("codes", {}) or {})
    selected = list(issues)
    for action in ("clarify", "repair", "fail"):
        for issue in selected:
            payload = dict(by_code.get(issue.code, {}) or {})
            if str(payload.get("action") or "") == action:
                return {
                    "action": action,
                    "category": issue.category,
                    "reason": str(payload.get("reason") or issue.code),
                }
    default = dict(defaults.get(phase, {}) or {})
    return {
        "action": str(default.get("action") or ("repair" if phase == "plan" else "fail")),
        "category": str(default.get("category") or phase),
        "reason": str(default.get("reason") or f"{phase}_contract_error"),
    }


def allowed_aggregator_modes(config: ResumeQAConfig) -> list[str]:
    """获取允许项aggregatormodes并返回。"""
    configured = list(dict(config.aggregator_tasks.get("generation_contract", {}) or {}).get("allowed_modes", []) or [])
    return [str(item) for item in configured]
