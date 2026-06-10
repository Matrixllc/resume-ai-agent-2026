"""condition_rules.yaml 和 validation.yaml 的规则结构校验。"""

from __future__ import annotations

from typing import Any


def validate_condition_rules(payload: dict[str, Any], errors: list[str]) -> None:
    """校验条件归一化规则具备可执行的类型和 filter 参数声明。"""
    condition_types = dict(payload.get("condition_types", {}) or {})
    if not condition_types:
        errors.append("condition_rules.yaml: condition_types must not be empty")
    for condition_type, raw in condition_types.items():
        entry = dict(raw or {})
        if bool(entry.get("retrievable")) and not str(entry.get("filter_argument") or "").strip():
            errors.append(f"condition_rules.yaml: condition_type `{condition_type}` retrievable entries must declare filter_argument")


def validate_validation_rules(payload: dict[str, Any], errors: list[str]) -> None:
    """校验 validator/repair 共用的 issue action 映射存在。"""
    actions = dict(payload.get("issue_actions", {}) or {})
    if not actions:
        errors.append("validation.yaml: issue_actions must not be empty")
    for code, raw in dict(actions.get("codes", {}) or {}).items():
        action = str(dict(raw or {}).get("action") or "").strip()
        if not action:
            errors.append(f"validation.yaml: issue_actions.codes.{code} must declare action")
    for category, raw in dict(actions.get("defaults", {}) or {}).items():
        action = str(dict(raw or {}).get("action") or "").strip()
        if not action:
            errors.append(f"validation.yaml: issue_actions.defaults.{category} must declare action")
