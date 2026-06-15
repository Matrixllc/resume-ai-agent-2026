"""Plan structure and tool protocol checks.

这个文件负责什么：
- 检查 QueryPlan 的基础结构、工具协议和场景合同。
- 校验 tool name、arguments、depends_on、$ref、allowed/forbidden tools。

应该从哪个函数读起：
- validate_plan_structure
- validate_tool_dependencies
- validate_tool_arguments
"""

from __future__ import annotations

import re
from inspect import Parameter, signature
from typing import List

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.rules.execution_policy_rules import scenario_for_intent
from resume_query_ai_qa.core.inspection.plan_inspection import (
    argument_refs as _argument_refs,
    plan_intent_calls as _intent_calls,
    plan_tool_calls as _plan_tool_calls,
)
from resume_query_ai_qa.core.schemas import QueryPlan, RouterOutput, ToolCallSpec
from resume_query_ai_qa.tools import get_tool_registry


def validate_plan_structure(
    plan: QueryPlan,
    config: ResumeQAConfig,
    *,
    router_output: RouterOutput | None = None,
) -> List[str]:
    """校验计划结构、工具白名单和参数协议。"""
    errors: List[str] = []

    if plan.intent == "compound":
        errors.extend(
            validate_tool_dependencies(
                [call for _intent, calls in _intent_calls(plan) for call in calls],
                allow_duplicate_output_keys=True,
            )
        )
    if plan.intent == "out_of_scope" and _plan_tool_calls(plan):
        errors.append("out_of_scope cannot use resume tools")

    if router_output is not None:
        errors.extend(validate_router_scenario_contract(router_output, config))

    for intent, calls in _intent_calls(plan):
        if intent == "out_of_scope" and calls:
            errors.append("out_of_scope cannot use resume tools")
            continue
        scenario = scenario_for_intent(router_output, intent)
        allowed = set(config.allowed_tools_for_intent(intent, scenario))
        forbidden = set(config.forbidden_tools_for_scenario(intent, scenario))
        if intent == "compound":
            continue
        if plan.intent != "compound":
            errors.extend(validate_tool_dependencies(calls))
        for call in calls:
            if call.name in forbidden:
                errors.append(f"{intent} cannot use tool {call.name} in scenario {scenario}")
                continue
            if call.name not in allowed and not _is_context_candidate_source_call_allowed(call, router_output):
                errors.append(f"{intent} cannot use tool {call.name}")
            else:
                errors.extend(validate_tool_arguments(call))
    return errors


def _is_context_candidate_source_call_allowed(call: ToolCallSpec, router_output: RouterOutput | None) -> bool:
    """允许上下文候选集合先落成 candidate_pool，再供画像/证据消费。"""
    if router_output is None or not router_output.context_policy.uses_context:
        return False
    if router_output.context_policy.context_ref_type not in {"ranking_top", "ranking_top_k", "candidate_pool", "comparison_pair"}:
        return False
    return call.name == "filter_candidates" and bool(call.arguments.get("candidate_ids"))


def validate_router_scenario_contract(router_output: RouterOutput, config: ResumeQAConfig) -> List[str]:
    """校验 RouterOutput.scenario_decisions 是否符合 scenarios.yaml。"""
    intents = router_output.sub_intent_candidates if router_output.intent == "compound" else [router_output.intent]
    errors: List[str] = []
    for intent in intents:
        decision = router_output.scenario_decisions.get(str(intent))
        if decision is None:
            errors.append(f"scenario contract: missing scenario for intent {intent}")
            continue
        if decision.scenario not in config.scenario_names():
            errors.append(f"scenario contract: unknown scenario {decision.scenario} for intent {intent}")
        elif decision.scenario not in config.allowed_scenarios_for_intent(str(intent)):
            errors.append(f"scenario contract: scenario {decision.scenario} is not allowed for intent {intent}")
    extra = set(router_output.scenario_decisions) - {str(intent) for intent in intents}
    if extra:
        errors.append(f"scenario contract: decisions contain unrelated intents {sorted(extra)}")
    return errors


def validate_tool_arguments(call: ToolCallSpec) -> List[str]:
    """用 tool registry 中的函数签名校验 ToolCallSpec.arguments。"""
    registry = get_tool_registry()
    tool = registry.get(call.name)
    if tool is None:
        return [f"unknown tool: {call.name}"]
    sig = signature(tool)
    params = sig.parameters
    has_var_kwargs = any(param.kind == Parameter.VAR_KEYWORD for param in params.values())
    accepted = {
        name
        for name, param in params.items()
        if param.kind in {Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY}
    }
    errors: List[str] = []
    if not has_var_kwargs:
        unknown = sorted(set(call.arguments) - accepted)
        if unknown:
            errors.append(f"{call.name} got unsupported arguments: {unknown}")
    for name, param in params.items():
        if param.default is Parameter.empty and param.kind in {Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY}:
            if name not in call.arguments:
                errors.append(f"{call.name} missing required argument: {name}")
    return errors


def validate_tool_dependencies(calls: List[ToolCallSpec], *, allow_duplicate_output_keys: bool = False) -> List[str]:
    """校验 output_key、depends_on 和参数 $ref 的顺序关系。"""
    errors: List[str] = []
    available: set[str] = set()
    for index, call in enumerate(calls, start=1):
        if call.output_key:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", call.output_key):
                errors.append(f"{call.name} has invalid output_key: {call.output_key!r}")
            if call.output_key in available and not allow_duplicate_output_keys:
                errors.append(f"{call.name} duplicates output_key: {call.output_key}")
        for dependency in call.depends_on:
            if dependency not in available:
                errors.append(f"{call.name} depends_on unknown or later output_key: {dependency}")
        refs = _argument_refs(call.arguments)
        for ref in refs:
            root = ref.split(".", 1)[0]
            if root not in available:
                errors.append(f"{call.name} argument references unknown or later output_key: ${ref}")
            if call.depends_on and root not in call.depends_on:
                errors.append(f"{call.name} argument reference ${ref} is missing from depends_on")
            if not call.depends_on:
                errors.append(f"{call.name} argument reference ${ref} requires depends_on")
        if call.output_key:
            available.add(call.output_key)
        elif refs and not call.output_key and index == 1:
            errors.append(f"{call.name} cannot reference previous output in the first step")
    return errors


__all__ = ["validate_plan_structure", "validate_router_scenario_contract", "validate_tool_arguments", "validate_tool_dependencies"]
