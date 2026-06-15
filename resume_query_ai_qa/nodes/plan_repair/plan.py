"""Plan repair classification and deterministic reconstruction.

这个文件负责什么：
- 根据 plan_validator 错误决定 repair / clarify / fail。
- 对可修复错误执行确定性 QueryPlan 重建。
- 修复后刷新 structured refs 和 artifact bindings。

应该从哪个函数读起：
- repair_plan
- classify_plan_repair_action
- build_rule_plan

不会负责什么：
- 不调用工具。
- 不直接进入 executor。
- 不绕过 plan_validator。
"""

from __future__ import annotations

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.inspection.plan_artifacts import with_artifact_bindings
from resume_query_ai_qa.core.llm import is_llm_enabled
from resume_query_ai_qa.core.rules.plan_building import ranking_output_limit, reuse_candidate_source_for_count_list, sub_task_for_intent, with_structured_refs
from resume_query_ai_qa.core.rules.behavior_contract import validation_action, validation_issues as build_validation_issues
from resume_query_ai_qa.core.schemas import QueryPlan, RouterOutput, ValidationIssue

from .llm import repair_llm_plan


def build_rule_plan(question: str, router_output: RouterOutput, session_context: dict | None = None, config: ResumeQAConfig | None = None) -> QueryPlan:
    """基于 RouterOutput 重新构建确定性 QueryPlan。

    这是默认 repair 路径。它不在坏 plan 上随意 patch，而是重新按 intent、
    sub_intents、conditions 和 context 生成安全计划。
    """
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
    """把当前问题里的 TopK 排序展示限制写入 QueryPlan constraints。"""
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
    """判断当前 intent 是否必须使用确定性规则修复。"""
    return router_output.intent in {"out_of_scope", "candidate_count", "candidate_list", "candidate_profile_intro", "candidate_compare_pair"} or router_output.intent == "compound"


def classify_plan_repair_action(
    errors: list[str],
    plan: QueryPlan | None,
    router_output: RouterOutput,
    *,
    config: ResumeQAConfig | None = None,
    validation_issues: list[ValidationIssue] | None = None,
) -> dict[str, str]:
    """根据 ValidationIssue 和 validation.yaml 决定 repair / clarify / fail。"""
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
    """修复非法 QueryPlan 并返回修复结果。

    返回值依次是：repaired plan、decision、engine、fallback_reason。
    修复后的 plan 必须回到 plan_validator 复检，不能直接执行。
    """
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
