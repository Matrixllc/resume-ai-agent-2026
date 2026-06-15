"""Experimental LLM-backed QueryPlan repair.

这个文件负责什么：
- 在显式启用时，用 LLM 尝试修复 semantic 类 QueryPlan 错误。
- 给 LLM prompt 暴露受限工具集合和工具参数签名。

默认状态：
- validation.yaml 中 plan_repair.llm_enabled=false。

不会负责什么：
- 不保证 LLM 产物直接可执行。
- 修复后仍必须经过 structured refs、artifact bindings 和 plan_validator。
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
    """调用 LLM 生成修复后的 QueryPlan draft，并刷新 refs/artifacts。"""
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
    """按 intent/scenario 收集 LLM repair 可使用的工具白名单。"""
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
    """从 tool registry 提取工具参数名，作为 LLM repair prompt 约束。"""
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
