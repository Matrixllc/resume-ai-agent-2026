"""Experimental LLM-backed QueryPlan repair.

This capability is intentionally disabled by default. The graph reaches it
only when validation.yaml enables plan_repair.llm_enabled.
"""

from __future__ import annotations

import inspect
from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.inspection.plan_artifacts import with_artifact_bindings
from resume_query_ai_qa.core.rules.execution_policy_rules import scenario_for_intent
from resume_query_ai_qa.core.llm import invoke_structured
from resume_query_ai_qa.core.llm.prompts import build_plan_repair_prompt
from resume_query_ai_qa.core.rules.plan_building import with_structured_refs
from resume_query_ai_qa.core.schemas import QueryPlan, RouterOutput
from resume_query_ai_qa.tools import get_tool_registry


def repair_llm_plan(
    question: str,
    router_output: RouterOutput,
    previous_plan: QueryPlan,
    validation_errors: list[str],
    config: ResumeQAConfig | None = None,
    *,
    session_context: dict | None = None,
) -> QueryPlan:
    """根据结构化校验问题执行修复llm计划修复，并保持原有安全边界和产物依赖。"""
    cfg = config or load_config()
    plan = invoke_structured(
        QueryPlan,
        build_plan_repair_prompt(
            question=question,
            router_output=router_output,
            allowed_tools_by_intent=allowed_tools_by_intent(router_output, cfg),
            tool_specs=tool_specs(),
            previous_plan=previous_plan,
            validation_errors=validation_errors,
        ),
        config=cfg,
    )
    return with_artifact_bindings(with_structured_refs(plan), router_output, config=cfg)


def allowed_tools_by_intent(router_output: RouterOutput, config: ResumeQAConfig) -> dict[str, list[str]]:
    """根据结构化校验问题执行允许项工具by意图修复，并保持原有安全边界和产物依赖。"""
    intents = router_output.sub_intent_candidates if router_output.intent == "compound" else [router_output.intent]
    return {
        intent: [
            tool
            for tool in config.allowed_tools_for_intent(intent, scenario)
            if tool not in set(config.forbidden_tools_for_scenario(intent, scenario))
        ]
        for intent in intents
        for scenario in [scenario_for_intent(router_output, intent)]
    }


def tool_specs() -> dict[str, Any]:
    """根据结构化校验问题执行工具specs修复，并保持原有安全边界和产物依赖。"""
    return {
        name: {
            "parameters": [
                parameter.name
                for parameter in inspect.signature(tool).parameters.values()
                if parameter.name != "config"
            ]
        }
        for name, tool in get_tool_registry().items()
    }
