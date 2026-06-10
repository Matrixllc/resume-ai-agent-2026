"""Plan repair classification and deterministic reconstruction."""

from __future__ import annotations

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.inspection.plan_artifacts import with_artifact_bindings
from resume_query_ai_qa.core.llm import is_llm_enabled
from resume_query_ai_qa.core.rules.plan_building import ranking_output_limit, reuse_candidate_source_for_count_list, sub_task_for_intent, with_structured_refs
from resume_query_ai_qa.core.rules.behavior_contract import validation_action, validation_issues as build_validation_issues
from resume_query_ai_qa.core.schemas import QueryPlan, RouterOutput, ValidationIssue

from .llm import repair_llm_plan


def build_rule_plan(question: str, router_output: RouterOutput, session_context: dict | None = None, config: ResumeQAConfig | None = None) -> QueryPlan:
    """按结构化校验问题重建规则计划并返回。"""
    cfg = config or load_config()
    intents = router_output.sub_intent_candidates if router_output.intent == "compound" else [router_output.intent]
    if router_output.intent == "compound":
        tasks = reuse_candidate_source_for_count_list([
            sub_task_for_intent(intent, question, router_output=router_output, session_context=session_context, config=cfg)
            for intent in intents
        ])
        return _with_ranking_output_limit(QueryPlan(intent="compound", is_compound=True, sub_tasks=tasks), question)
    if router_output.intent == "out_of_scope":
        return QueryPlan(intent="out_of_scope", notes=["out_of_scope_no_tools"])
    task = sub_task_for_intent(router_output.intent, question, router_output=router_output, session_context=session_context, config=cfg)
    return _with_ranking_output_limit(QueryPlan(intent=router_output.intent, tool_calls=task.tool_calls), question)


def _with_ranking_output_limit(plan: QueryPlan, question: str) -> QueryPlan:
    """Attach current-turn TopK display limits to plan constraints."""
    limit = ranking_output_limit(question)
    if not limit:
        return plan
    return plan.model_copy(update={"constraints": plan.constraints.model_copy(update={"ranking_output_limit": limit})})


def refresh_artifact_bindings(
    plan: QueryPlan,
    router_output: RouterOutput | None,
    config: ResumeQAConfig | None = None,
) -> QueryPlan:
    """在修复后重新生成产物绑定；不改变计划中的工具调用和参数。"""
    return with_artifact_bindings(with_structured_refs(plan), router_output, config=config)


def requires_deterministic_plan(router_output: RouterOutput) -> bool:
    """根据结构化校验问题执行requiresdeterministic计划修复，并保持原有安全边界和产物依赖。"""
    return router_output.intent in {"out_of_scope", "candidate_count", "candidate_list", "candidate_profile_intro", "candidate_compare_pair"} or router_output.intent == "compound"


def classify_plan_repair_action(
    errors: list[str],
    plan: QueryPlan | None,
    router_output: RouterOutput,
    *,
    config: ResumeQAConfig | None = None,
    validation_issues: list[ValidationIssue] | None = None,
) -> dict[str, str]:
    """根据结构化校验问题执行classify计划修复action修复，并保持原有安全边界和产物依赖。"""
    cfg = config or load_config()
    decision = validation_action(cfg, validation_issues or build_validation_issues(errors, "plan"), "plan")
    if decision["action"] == "repair":
        decision["action"] = "rule_repair"
    return decision


def repair_plan(
    question: str,
    router_output: RouterOutput,
    previous_plan: QueryPlan | None,
    validation_errors: list[str],
    *,
    session_context: dict | None = None,
    config: ResumeQAConfig | None = None,
    use_llm: bool = True,
    validation_issues: list[ValidationIssue] | None = None,
) -> tuple[QueryPlan, dict[str, str], str, str]:
    """根据结构化校验问题执行修复计划修复，并保持原有安全边界和产物依赖。"""
    cfg = config or load_config()
    decision = classify_plan_repair_action(
        validation_errors,
        previous_plan,
        router_output,
        config=cfg,
        validation_issues=validation_issues,
    )
    if decision["action"] in {"clarify", "fail"}:
        if previous_plan is None:
            raise ValueError(f"cannot preserve missing plan for terminal repair action: {decision['action']}")
        return previous_plan, decision, "rule", decision["reason"]
    llm_repair_enabled = bool(dict(cfg.validation.get("plan_repair", {}) or {}).get("llm_enabled", False))
    if (
        decision["category"] == "semantic"
        and llm_repair_enabled
        and use_llm
        and is_llm_enabled(cfg)
        and previous_plan is not None
        and not requires_deterministic_plan(router_output)
    ):
        try:
            plan = repair_llm_plan(
                question,
                router_output,
                previous_plan,
                validation_errors,
                cfg,
                session_context=session_context,
            )
            return refresh_artifact_bindings(plan, router_output), decision, "llm", ""
        except Exception as error:
            reason = f"llm_repair_failed:{type(error).__name__}: {str(error)[:160]}"
            decision = {"action": "rule_repair", "category": decision["category"], "reason": reason}
            plan = build_rule_plan(question, router_output, session_context=session_context, config=cfg)
            return refresh_artifact_bindings(plan, router_output), decision, "rule_fallback", reason
    reason = "deterministic_policy" if requires_deterministic_plan(router_output) else decision["reason"]
    plan = build_rule_plan(question, router_output, session_context=session_context, config=cfg)
    return refresh_artifact_bindings(plan, router_output), decision, "rule", reason
