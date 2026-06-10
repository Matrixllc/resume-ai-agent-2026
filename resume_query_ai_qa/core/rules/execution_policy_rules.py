from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.schemas import ExecutionDecision, RouterOutput, ScenarioDecision


def scenario_for_intent(router_output: RouterOutput | None, intent: str) -> str:
    """读取路由器确定的场景，不重复解释查询文本。"""
    if router_output is None:
        return ""
    decision = router_output.scenario_decisions.get(intent)
    return str(decision.scenario if decision else "")


def resolve_scenario(question: str, router_output: RouterOutput | None, intent: str, config: ResumeQAConfig | None = None) -> str:
    """在路由大模型不可用时，按配置规则生成 scenario。

    intent 只回答“用户想要什么”，例如画像、筛选、排序；scenario 回答
    “这件事应该多严格地执行”。下游 compiler/validator 会用 scenario 决定
    可用工具、是否必须走结构化筛选、是否必须查证据。

    典型例子：
    - candidate_profile_intro -> soft_summary，通常命中画像 template。
    - candidate_filter + 明确 domain/skill -> hard_filter，优先结构化筛选。
    - candidate_filter + “可能/相关/找找” -> open_recall，允许语义召回。
    - evidence_question + 明确候选人 -> fact_check，在候选人内查证据。
    """
    if config is None:
        return ""
    rule = config.scenario_resolution_rule(intent)
    if not rule:
        return ""
    if _looks_like_open_recall(question, router_output, config) and rule.get("open_recall"):
        return rule["open_recall"]
    if router_output and _has_candidate_reference(router_output) and rule.get("with_candidate_reference"):
        return rule["with_candidate_reference"]
    if router_output and _has_filter_scope(router_output) and rule.get("with_filter_scope"):
        return rule["with_filter_scope"]
    if router_output and router_output.requires_evidence and not _has_filter_scope(router_output) and rule.get("requires_evidence_without_scope"):
        return rule["requires_evidence_without_scope"]
    return rule.get("default", "")


def rule_scenario_decisions(
    question: str,
    router_output: RouterOutput,
    config: ResumeQAConfig | None = None,
) -> dict[str, ScenarioDecision]:
    """为路由中的每个意图生成配置驱动的场景决策，供规则回退路径使用。"""
    intents = _router_intents(router_output)
    return {
        intent: ScenarioDecision(
            scenario=resolve_scenario(question, router_output, intent, config),
            confidence=1.0,
            evidence=[question] if question else [],
            reason="rule fallback 根据 intent、条件和问题执行语义生成 scenario",
            source="rule_fallback",
        )
        for intent in intents
    }


def resolve_execution_decision(
    question: str,
    router_output: RouterOutput,
    config: ResumeQAConfig,
) -> ExecutionDecision:
    """决定本轮走 template 还是 generic，但不生成工具参数。

    这是 graph 的调度策略层。它只产出 `ExecutionDecision`：
    - workflow_template：稳定高频路径，runner 会跳过 planner，直接进 compiler。
    - generic_tool_binding：开放或未模板化路径，runner 会先进入 planner。

    注意这里不选择具体工具，也不拼 tool arguments。工具选择和参数绑定属于
    `plan_compiler`，否则 router/policy/compiler 的边界会混在一起。
    """
    intents = _router_intents(router_output)
    scenarios = {intent: scenario_for_intent(router_output, intent) for intent in intents}
    mode = str(config.compiler_flags()["mode"])
    if mode == "generic_tool_binding":
        return ExecutionDecision(
            compiler="generic_tool_binding",
            planner=config.planner_for_scenarios(scenarios),
            scenarios=scenarios,
            reason="generic-only diagnostic mode",
        )
    workflow_name = match_workflow(router_output, scenarios, config)
    if workflow_name or mode == "workflow_template":
        return ExecutionDecision(
            compiler="workflow_template",
            planner="rule",
            workflow_name=workflow_name,
            scenarios=scenarios,
            reason=f"matched stable workflow: {workflow_name}" if workflow_name else "workflow-only diagnostic mode",
        )
    return ExecutionDecision(
        compiler="generic_tool_binding",
        planner=config.planner_for_scenarios(scenarios),
        scenarios=scenarios,
        reason="no stable workflow matched",
    )


def match_workflow(
    router_output: RouterOutput,
    scenarios: dict[str, str],
    config: ResumeQAConfig,
) -> str:
    """按 YAML 优先级匹配稳定工作流；无匹配时返回空字符串走通用规划。"""
    workflows = dict(config.compiler_templates.get("workflows", {}) or {})
    ranked = sorted(
        workflows.items(),
        key=lambda item: -int(dict(item[1] or {}).get("priority", 0) or 0),
    )
    for name, raw_workflow in ranked:
        workflow = dict(raw_workflow or {})
        match = dict(workflow.get("match", {}) or {})
        if not match:
            continue
        if _workflow_matches(router_output, scenarios, match):
            return str(name)
    if router_output.intent == "compound" and _all_sub_intents_have_composable_workflows(router_output, scenarios, workflows):
        return "composed_sub_intent_workflows"
    return ""


def _workflow_matches(router_output: RouterOutput, scenarios: dict[str, str], match: dict[str, Any]) -> bool:
    """判断路由结果是否满足工作流条件并返回布尔值。"""
    expected_intent = str(match.get("intent", "") or "").strip()
    if expected_intent and router_output.intent != expected_intent:
        return False
    allowed_intents = {str(item) for item in list(match.get("intents", []) or []) if str(item).strip()}
    if allowed_intents and router_output.intent not in allowed_intents:
        return False
    required = {str(item) for item in list(match.get("required_sub_intents", []) or []) if str(item).strip()}
    if required and not required <= set(router_output.sub_intent_candidates):
        return False
    allowed_scenarios = {str(item) for item in list(match.get("scenarios", []) or []) if str(item).strip()}
    if allowed_scenarios and not any(scenario in allowed_scenarios for scenario in scenarios.values()):
        return False
    if bool(match.get("requires_scope", False)) and not _has_required_scope(router_output):
        return False
    return True


def _all_sub_intents_have_composable_workflows(
    router_output: RouterOutput,
    scenarios: dict[str, str],
    workflows: dict[str, Any],
) -> bool:
    """判断所有子意图是否都有可组合工作流并返回布尔值。"""
    for intent in router_output.sub_intent_candidates:
        scenario = scenarios.get(str(intent), "")
        if not any(
            _single_intent_workflow_matches(str(intent), scenario, dict(raw_workflow or {}))
            for raw_workflow in workflows.values()
        ):
            return False
    return bool(router_output.sub_intent_candidates)


def _single_intent_workflow_matches(intent: str, scenario: str, workflow: dict[str, Any]) -> bool:
    """判断单个意图与场景是否匹配工作流并返回布尔值。"""
    match = dict(workflow.get("match", {}) or {})
    allowed_intents = {str(item) for item in list(match.get("intents", []) or []) if str(item).strip()}
    allowed_scenarios = {str(item) for item in list(match.get("scenarios", []) or []) if str(item).strip()}
    if intent not in allowed_intents:
        return False
    return not allowed_scenarios or scenario in allowed_scenarios


def _router_intents(router_output: RouterOutput) -> list[str]:
    """获取路由意图集合并返回。"""
    if router_output.intent == "compound":
        return [str(intent) for intent in router_output.sub_intent_candidates]
    return [str(router_output.intent)]


def _has_required_scope(router_output: RouterOutput) -> bool:
    """判断必需范围是否成立并返回布尔值。"""
    if router_output.context_policy.uses_context and router_output.context_policy.context_ref_type == "candidate_pool":
        return True
    return any(
        condition.type in {"domain", "skill", "concept", "keyword", "major", "job_intent"}
        and not condition.matched_by.startswith("preference_target:")
        and str(condition.normalized_value or "").strip()
        for condition in router_output.normalized_conditions
    )


def _has_filter_scope(router_output: RouterOutput) -> bool:
    """判断筛选范围是否成立并返回布尔值。"""
    normalized = any(
        condition.type in {"domain", "skill", "concept", "keyword", "major", "job_intent", "candidate_name"}
        and str(condition.normalized_value or condition.raw_value or "").strip()
        for condition in router_output.normalized_conditions
    )
    raw = any(
        condition.type in {"domain", "skill", "concept", "keyword", "major", "job_intent", "candidate_name"}
        and str(condition.raw_value or "").strip()
        for condition in router_output.conditions
    )
    return normalized or raw


def _has_candidate_reference(router_output: RouterOutput) -> bool:
    """判断候选人引用是否成立并返回布尔值。"""
    return any(condition.type == "candidate_name" for condition in [*router_output.conditions, *router_output.normalized_conditions]) or bool(
        router_output.context_policy.uses_context
    )


def open_recall_terms(config: ResumeQAConfig | None = None) -> list[str]:
    """获取开放召回词项集合并返回。"""
    if config is None:
        return ["可能", "相关", "类似", "接近", "找找", "看看", "这类", "语义", "semantic", "similar", "related", "might", "maybe"]
    raw = (((config.router_rules.get("signals") or {}).get("open_recall_terms")) or [])
    terms = [str(item).strip() for item in list(raw) if str(item).strip()]
    return terms or open_recall_terms(None)


def _looks_like_open_recall(question: str, router_output: RouterOutput | None, config: ResumeQAConfig | None = None) -> bool:
    """判断开放召回是否成立并返回布尔值。"""
    text = str(question or "").lower()
    recall_terms = open_recall_terms(config)
    if any(str(token).lower() in text for token in recall_terms):
        return True
    if router_output is None:
        return False
    evidence = " ".join(
        str(value)
        for item in router_output.sub_intent_evidence
        for value in item.evidence
    ).lower()
    return any(str(token).lower() in evidence for token in recall_terms)
