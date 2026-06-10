"""YAML-driven SemanticPlan construction and normalization."""

from __future__ import annotations

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.rules.execution_policy_rules import scenario_for_intent
from resume_query_ai_qa.core.schemas import ExecutionDecision, RouterOutput, SemanticPlan, SemanticStep, ToolHint


def semantic_plan_from_router(
    router_output: RouterOutput,
    decision: ExecutionDecision | None = None,
    config: ResumeQAConfig | None = None,
) -> SemanticPlan:
    """根据路由输出与 YAML 策略构建确定性的语义计划。"""
    cfg = config or load_config()
    intents = router_output.sub_intent_candidates if router_output.intent == "compound" else [router_output.intent]
    return SemanticPlan(
        intent=router_output.intent,
        is_compound=router_output.intent == "compound",
        steps=[
            semantic_step_from_config(intent, router_output, decision=decision, config=cfg)
            for intent in intents
        ],
        context_policy=router_output.context_policy,
        normalized_conditions=router_output.normalized_conditions,
        compile_strategy="domain_template",
        notes=["semantic_plan_from_router", "yaml_driven_rule_planner"],
    )


def normalize_semantic_plan(
    router_output: RouterOutput,
    semantic_plan: SemanticPlan,
    decision: ExecutionDecision,
    config: ResumeQAConfig | None = None,
) -> SemanticPlan:
    """将大模型草稿与路由输出对齐，并合并 YAML 策略提示。"""
    cfg = config or load_config()
    intents = router_output.sub_intent_candidates if router_output.intent == "compound" else [router_output.intent]
    existing = {step.intent: step for step in semantic_plan.steps}
    steps: list[SemanticStep] = []
    for intent in intents:
        configured = semantic_step_from_config(intent, router_output, decision=decision, config=cfg)
        draft = existing.get(intent)
        if draft is None:
            steps.append(configured.model_copy(update={"reason": "rule_added_missing_semantic_step"}))
            continue
        optional_needs = set(cfg.optional_semantic_needs_for_intent(intent, configured.scenario))
        steps.append(
            configured.model_copy(
                update={
                    "needs": _dedupe([*configured.needs, *(need for need in draft.needs if need in optional_needs)]),
                    "tool_hints": _dedupe([*configured.tool_hints, *draft.tool_hints]),
                    "tool_hint_scores": _dedupe_tool_hints(
                        [*configured.tool_hint_scores, *(_normalize_llm_tool_hint(hint, configured.scenario) for hint in draft.tool_hint_scores)]
                    ),
                    "conditions": router_output.normalized_conditions,
                    "requires_jd": bool(configured.requires_jd or draft.requires_jd),
                    "requires_evidence": bool(configured.requires_evidence or draft.requires_evidence),
                    "evidence": configured.evidence,
                    "reason": draft.reason or "normalized_llm_semantic_step",
                }
            )
        )
    return semantic_plan.model_copy(
        update={
            "intent": router_output.intent,
            "is_compound": router_output.intent == "compound",
            "steps": steps,
            "context_policy": router_output.context_policy,
            "normalized_conditions": router_output.normalized_conditions,
            "compile_strategy": "domain_template",
            "notes": [*semantic_plan.notes, "normalized_semantic_plan: aligned with router output and yaml policy"],
        }
    )


def semantic_step_from_config(
    intent: str,
    router_output: RouterOutput,
    *,
    decision: ExecutionDecision | None,
    config: ResumeQAConfig,
) -> SemanticStep:
    """构建单个语义步骤，避免编写意图专属的 Python 分支。"""
    scenario = scenario_for_intent(router_output, intent)
    defaults = config.semantic_defaults_for_intent(intent, scenario)
    hints = config.preferred_tool_hints_for_scenario(intent, scenario)
    tool_hint_scores = [
        ToolHint(
            name=str(item["name"]),
            confidence=float(item.get("confidence", 0.75) or 0.75),
            reason=f"tool policy preferred for scenario={scenario or 'default'}",
            source="policy",
            scenario=scenario,
        )
        for item in hints
        if str(item.get("name", "") or "").strip()
    ]
    return SemanticStep(
        intent=intent,  # type: ignore[arg-type]
        scenario=scenario,
        needs=config.semantic_needs_for_intent(intent),
        tool_hints=[hint.name for hint in tool_hint_scores],
        tool_hint_scores=tool_hint_scores,
        conditions=router_output.normalized_conditions,
        requires_jd=bool(router_output.requires_jd or defaults["requires_jd"]),
        requires_evidence=bool(router_output.requires_evidence or defaults["requires_evidence"]),
        evidence=[
            evidence
            for item in router_output.sub_intent_evidence
            if item.intent == intent
            for evidence in item.evidence
        ],
        reason="derived_from_router_and_yaml",
    )


def _dedupe(values: list[str]) -> list[str]:
    """去重结果并返回。"""
    return list(dict.fromkeys(str(value) for value in values if str(value).strip()))


def _dedupe_tool_hints(hints: list[ToolHint]) -> list[ToolHint]:
    """去重工具工具建议集合并返回。"""
    output: list[ToolHint] = []
    seen: set[str] = set()
    for hint in hints:
        if hint.name in seen:
            continue
        seen.add(hint.name)
        output.append(hint)
    return output


def _normalize_llm_tool_hint(hint: ToolHint, scenario: str) -> ToolHint:
    """标准化大模型工具工具建议并返回。"""
    return hint.model_copy(
        update={
            "confidence": min(1.0, max(0.0, float(hint.confidence))),
            "source": "llm",
            "scenario": scenario,
        }
    )
