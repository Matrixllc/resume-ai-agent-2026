"""compiler_templates.yaml 的 workflow 和 binding 校验。"""

from __future__ import annotations

from typing import Any

from .common import check_tool


def validate_compiler_templates(
    payload: dict[str, Any],
    intents: set[str],
    scenarios: set[str],
    allowed_pairs: set[tuple[str, str]],
    tools: set[str],
    errors: list[str],
) -> None:
    """校验 workflow template 引用的 intent、scenario、tool 和 binding。"""
    for workflow, entry_raw in dict(payload.get("workflows", {}) or {}).items():
        entry = dict(entry_raw or {})
        match = dict(entry.get("match", {}) or {})
        referenced_intents = list(match.get("intents", []) or [])
        if match.get("intent"):
            referenced_intents.append(match["intent"])
        referenced_intents.extend(match.get("required_sub_intents", []) or [])
        for intent in referenced_intents:
            if str(intent) not in intents and str(intent) != "compound":
                errors.append(f"compiler_templates.yaml: workflow `{workflow}` references unknown intent `{intent}`")
        for scenario in match.get("scenarios", []) or []:
            if str(scenario) not in scenarios:
                errors.append(f"compiler_templates.yaml: workflow `{workflow}` references unknown scenario `{scenario}`")
            elif referenced_intents and not any((str(intent), str(scenario)) in allowed_pairs for intent in referenced_intents):
                errors.append(f"compiler_templates.yaml: workflow `{workflow}` uses scenario `{scenario}` for incompatible intents")
        _validate_workflow_calls(workflow, entry, intents, tools, errors)


def validate_template_bindings(workflow: str, value: Any, errors: list[str]) -> None:
    """递归校验 workflow arguments 中的 `$binding` 只使用支持项。"""
    allowed = {"filter_args", "ranking_criteria_tool", "ranking_criteria_arguments", "retrieval_query", "workflow_evidence_max_candidates"}
    if isinstance(value, dict):
        if set(value) == {"$binding"} and str(value["$binding"]) not in allowed:
            errors.append(f"compiler_templates.yaml: workflow `{workflow}` uses unknown binding `{value['$binding']}`")
        for item in value.values():
            validate_template_bindings(workflow, item, errors)
    elif isinstance(value, list):
        for item in value:
            validate_template_bindings(workflow, item, errors)


def _validate_workflow_calls(workflow: str, entry: dict[str, Any], intents: set[str], tools: set[str], errors: list[str]) -> None:
    """校验 workflow 顶层和 sub_task 内的工具调用声明。"""
    for call in entry.get("tool_calls", []) or []:
        check_tool(f"compiler_templates.yaml: workflow `{workflow}`", "tool_calls", dict(call or {}).get("tool", ""), tools, errors)
    for task_raw in entry.get("sub_tasks", []) or []:
        task = dict(task_raw or {})
        intent = str(task.get("intent") or "")
        if intent not in intents:
            errors.append(f"compiler_templates.yaml: workflow `{workflow}` sub-task references unknown intent `{intent}`")
        for call_raw in task.get("tool_calls", []) or []:
            call = dict(call_raw or {})
            tool = call.get("tool", "")
            if isinstance(tool, dict) and "$binding" in tool:
                if str(tool.get("$binding")) != "ranking_criteria_tool":
                    errors.append(f"compiler_templates.yaml: workflow `{workflow}` uses unsupported tool binding `{tool}`")
            else:
                check_tool(f"compiler_templates.yaml: workflow `{workflow}` sub-task `{intent}`", "tool_calls", tool, tools, errors)
            validate_template_bindings(workflow, call.get("arguments", {}), errors)
