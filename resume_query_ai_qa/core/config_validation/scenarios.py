"""intent、scenario 和 router 规则的交叉校验。"""

from __future__ import annotations

from typing import Any


def validate_scenarios(payload: dict[str, Any], intents: set[str], errors: list[str]) -> None:
    """校验 scenarios.yaml 中每个 scenario 声明了合法 intent。"""
    scenarios = dict(payload.get("scenarios", {}) or {})
    for scenario, entry_raw in scenarios.items():
        planner = str(dict(entry_raw or {}).get("planner", "") or "")
        if planner not in {"rule", "llm"}:
            errors.append(f"scenarios.yaml: scenario `{scenario}` must declare planner as rule or llm")
        allowed = list(dict(entry_raw or {}).get("allowed_intents", []) or [])
        if not allowed:
            errors.append(f"scenarios.yaml: scenario `{scenario}` must declare allowed_intents")
        for intent in allowed:
            if str(intent) not in intents:
                errors.append(f"scenarios.yaml: scenario `{scenario}` references unknown intent `{intent}`")
    allowed_keys = {"default", "open_recall", "with_candidate_reference", "with_filter_scope", "requires_evidence_without_scope"}
    resolution_rules = dict(payload.get("resolution_rules", {}) or {})
    routable_intents = {
        str(intent)
        for entry_raw in scenarios.values()
        for intent in list(dict(entry_raw or {}).get("allowed_intents", []) or [])
    }
    for intent in sorted(routable_intents - set(resolution_rules)):
        errors.append(f"scenarios.yaml: routable intent `{intent}` must declare a resolution rule")
    for intent, rule_raw in resolution_rules.items():
        if str(intent) not in intents:
            errors.append(f"scenarios.yaml: resolution_rules references unknown intent `{intent}`")
        rule = dict(rule_raw or {})
        if "default" not in rule:
            errors.append(f"scenarios.yaml: resolution rule `{intent}` must declare default")
        for key, scenario in rule.items():
            if str(key) not in allowed_keys:
                errors.append(f"scenarios.yaml: resolution rule `{intent}` has unsupported condition `{key}`")
            if str(scenario) not in scenarios:
                errors.append(f"scenarios.yaml: resolution rule `{intent}` references unknown scenario `{scenario}`")
            elif str(intent) not in {str(item) for item in list(dict(scenarios.get(str(scenario), {}) or {}).get("allowed_intents", []) or [])}:
                errors.append(f"scenarios.yaml: resolution rule `{intent}` uses scenario `{scenario}` that does not allow this intent")


def scenario_pairs(payload: dict[str, Any]) -> set[tuple[str, str]]:
    """生成 intent/scenario 合法组合，供 policy/template 交叉校验复用。"""
    return {
        (str(intent), str(scenario))
        for scenario, entry_raw in dict(payload.get("scenarios", {}) or {}).items()
        for intent in list(dict(entry_raw or {}).get("allowed_intents", []) or [])
    }


def validate_router_rules(payload: dict[str, Any], intents: set[str], errors: list[str]) -> None:
    """校验 router_rules.yaml 的上下文规则只引用合法 intent 和 signal group。"""
    references = dict(payload.get("context_references", {}) or {})
    signals = dict(payload.get("signals", {}) or {})
    resolution = dict(payload.get("context_resolution", {}) or {})
    for index, rule_raw in enumerate(resolution.get("current_turn_outputs", []) or []):
        prefix = f"router_rules.yaml: context_resolution.current_turn_outputs[{index}]"
        rule = dict(rule_raw or {})
        intent = str(rule.get("intent") or "").strip()
        if intent not in intents:
            errors.append(f"{prefix} references unknown intent `{intent}`")
        for ref_type in rule.get("ref_types", []) or []:
            if str(ref_type) not in references:
                errors.append(f"{prefix} references unknown context ref type `{ref_type}`")
        signal_group = str(rule.get("question_signal_group") or "").strip()
        if signal_group not in signals:
            errors.append(f"{prefix} references unknown signal group `{signal_group}`")
