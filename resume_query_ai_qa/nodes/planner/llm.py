"""LLM-backed SemanticPlan draft generation.

这个文件负责什么：
- 调用 LLM 生成 SemanticPlan draft。
- 将 draft 交给 normalize_semantic_plan 收口。
- 失败时回退到 YAML 驱动的 rule planner。

应该从哪个函数读起：
- semantic_plan_llm

不会负责什么：
- 不允许 LLM 越权改 router/finalizer 已确定的 intent、conditions、context。
- 不生成 QueryPlan / ToolCallSpec。
"""

from __future__ import annotations

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.llm import invoke_structured
from resume_query_ai_qa.core.llm.prompts import build_semantic_planner_prompt
from resume_query_ai_qa.core.rules.semantic_plan import normalize_semantic_plan, semantic_plan_from_router
from resume_query_ai_qa.core.schemas import ExecutionDecision, RouterOutput, SemanticPlan


def semantic_plan_llm(
    question: str,
    router_output: RouterOutput,
    decision: ExecutionDecision,
    config: ResumeQAConfig,
) -> tuple[SemanticPlan, str]:
    """返回大模型语义计划，失败时回退到 YAML 驱动的规则计划。

    LLM 产物只是 draft；成功后也必须经过 normalize_semantic_plan，
    重新对齐 RouterOutput、ExecutionDecision 和 YAML policy。
    """
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
    """在渲染提示词前收集由 YAML 定义的规划器边界。

    prompt 只暴露当前 intent/scenario 允许的工具能力和 semantic needs，
    避免 LLM 自己发明规划合同。
    """
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
    """压缩 LLM fallback reason，避免 trace 里塞入过长异常。"""
    return f"{type(error).__name__}: {error}"[:300]
