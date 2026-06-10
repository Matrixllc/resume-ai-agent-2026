"""tool_policy.yaml 的工具、binding 和 result requirement 校验。"""

from __future__ import annotations

from typing import Any

from .common import check_tool


def validate_intent_tools(
    payload: dict[str, Any],
    intents: set[str],
    scenarios: set[str],
    allowed_pairs: set[tuple[str, str]],
    tools: set[str],
    errors: list[str],
) -> None:
    """校验 intent_tools 只引用合法 intent、scenario 和工具。"""
    for intent, entry_raw in dict(payload.get("intent_tools", {}) or {}).items():
        if intent not in intents:
            errors.append(f"tool_policy.yaml: intent_tools references unknown intent `{intent}`")
        entry = dict(entry_raw or {})
        validate_tool_fields(f"tool_policy.yaml: intent_tools.{intent}", entry, tools, errors)
        for scenario, scenario_raw in dict(entry.get("scenarios", {}) or {}).items():
            if scenario not in scenarios:
                errors.append(f"tool_policy.yaml: intent_tools.{intent}.scenarios references unknown scenario `{scenario}`")
            elif (str(intent), str(scenario)) not in allowed_pairs:
                errors.append(f"tool_policy.yaml: scenario `{scenario}` is not allowed for intent `{intent}` by scenarios.yaml")
            validate_tool_fields(f"tool_policy.yaml: intent_tools.{intent}.scenarios.{scenario}", dict(scenario_raw or {}), tools, errors)


def validate_tool_fields(prefix: str, entry: dict[str, Any], tools: set[str], errors: list[str]) -> None:
    """校验 allowed/preferred/forbidden 工具字段和 tool hints。"""
    for field in ("allowed_tools", "preferred_tools", "forbidden_tools"):
        for tool in entry.get(field, []) or []:
            check_tool(prefix, field, tool, tools, errors)
    for hint in entry.get("preferred_tool_hints", []) or []:
        tool = hint if isinstance(hint, str) else dict(hint or {}).get("name", "")
        check_tool(prefix, "preferred_tool_hints", tool, tools, errors)


def validate_tool_metadata(payload: dict[str, Any], intents: set[str], tools: set[str], errors: list[str]) -> None:
    """校验工具 metadata、fallback 和 intent result requirements。"""
    known_artifacts = {
        "candidate_collection",
        "candidate_count",
        "candidate_profile",
        "evidence_collection",
        "jd_criteria",
        "scored_candidates",
        "ranked_candidates",
        "generated_questions",
    }
    for name, raw in dict(payload.get("tools", {}) or {}).items():
        entry = dict(raw or {})
        produces = [str(item) for item in list(entry.get("produces", []) or []) if str(item).strip()]
        if not produces:
            errors.append(f"tool_policy.yaml: tool `{name}` must declare produces")
        for artifact in produces:
            if artifact not in known_artifacts:
                errors.append(f"tool_policy.yaml: tool `{name}` declares unknown artifact `{artifact}`")
        if "bind_primary_artifact" in entry and not isinstance(entry.get("bind_primary_artifact"), bool):
            errors.append(f"tool_policy.yaml: tool `{name}` bind_primary_artifact must be boolean")
        if not str(entry.get("default_output_key") or "").strip():
            errors.append(f"tool_policy.yaml: tool `{name}` must declare default_output_key")
        if not str(entry.get("binding_kind") or "").strip():
            errors.append(f"tool_policy.yaml: tool `{name}` must declare binding_kind")
        fallback = str(entry.get("fallback_tool") or "").strip()
        if fallback and fallback not in tools:
            errors.append(f"tool_policy.yaml: tool `{name}` references unknown fallback_tool `{fallback}`")
    for intent, raw in dict(payload.get("intent_result_requirements", {}) or {}).items():
        if intent not in intents:
            errors.append(f"tool_policy.yaml: intent_result_requirements references unknown intent `{intent}`")
        for field in ("all", "any"):
            for tool in list(dict(raw or {}).get(field, []) or []):
                check_tool(f"tool_policy.yaml: intent_result_requirements.{intent}", field, tool, tools, errors)
    for code, raw in dict(payload.get("business_limits", {}) or {}).items():
        check_tool(f"tool_policy.yaml: business_limits.{code}", "tool", dict(raw or {}).get("tool"), tools, errors)
