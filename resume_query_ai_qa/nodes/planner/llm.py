"""LLM-backed SemanticPlan generation with deterministic fallback."""

from __future__ import annotations

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.llm import invoke_structured
from resume_query_ai_qa.core.llm.prompts import build_semantic_planner_prompt
from resume_query_ai_qa.core.schemas import ExecutionDecision, RouterOutput, SemanticPlan

from .rules import normalize_semantic_plan, semantic_plan_from_router


def semantic_plan_llm(
    question: str,
    router_output: RouterOutput,
    decision: ExecutionDecision,
    config: ResumeQAConfig,
) -> tuple[SemanticPlan, str]:
    """返回大模型语义计划，失败时回退到 YAML 驱动的规则计划。"""
    try:
        semantic_plan = invoke_structured(
            SemanticPlan,
            build_semantic_planner_prompt(
                question=question,
                router_output=router_output,
                **_planner_prompt_context(router_output, decision, config),
            ),
            config=config,
        )
        return normalize_semantic_plan(router_output, semantic_plan, decision, config), ""
    except Exception as error:
        return semantic_plan_from_router(router_output, decision, config), _short_error(error)


def _planner_prompt_context(
    router_output: RouterOutput,
    decision: ExecutionDecision,
    config: ResumeQAConfig,
) -> dict:
    """在渲染提示词前收集由 YAML 定义的规划器边界。"""
    intents = router_output.sub_intent_candidates if router_output.intent == "compound" else [router_output.intent]
    return {
        "scenarios_by_intent": {intent: decision.scenarios.get(intent, "") for intent in intents},
        "tool_capabilities_by_intent": {
            intent: config.tool_capabilities_for_intent(intent, decision.scenarios.get(intent, ""))
            for intent in intents
        },
        "semantic_needs_by_intent": {
            intent: {
                "required": config.semantic_needs_for_intent(intent),
                "optional": config.optional_semantic_needs_for_intent(intent, decision.scenarios.get(intent, "")),
            }
            for intent in intents
        },
    }


def _short_error(error: Exception) -> str:
    """实现节点内的shorterror处理；输入来自当前节点契约，输出不越过节点职责边界。"""
    return f"{type(error).__name__}: {error}"[:300]
