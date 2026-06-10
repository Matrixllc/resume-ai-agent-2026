"""Plan Validator entrypoints."""

from __future__ import annotations

from typing import List

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.schemas import QueryPlan, RouterOutput, ValidationResult
from resume_query_ai_qa.core.rules.behavior_contract import validation_issues

from .plan_artifacts import validate_artifact_source_contract
from .plan_boundaries import validate_compare_boundaries, validate_count_boundaries, validate_ranking_boundaries
from .plan_semantics import validate_plan_semantics
from .plan_structure import validate_plan_structure


def validate_plan(
    plan: QueryPlan,
    config: ResumeQAConfig | None = None,
    *,
    router_output: RouterOutput | None = None,
    session_context: dict | None = None,
) -> ValidationResult:
    """校验查询计划并返回校验结果。"""
    cfg = config or load_config()
    errors: List[str] = []
    warnings: List[str] = []

    errors.extend(validate_plan_structure(plan, cfg, router_output=router_output))
    errors.extend(validate_compare_boundaries(plan, cfg))
    errors.extend(validate_ranking_boundaries(plan, cfg))
    errors.extend(validate_count_boundaries(plan, cfg))
    errors.extend(validate_artifact_source_contract(plan, router_output, cfg))
    if router_output is not None:
        errors.extend(validate_plan_semantics(plan, router_output, session_context=session_context, config=cfg))

    if errors:
        return ValidationResult(
            ok=False,
            errors=errors,
            warnings=warnings,
            error_details=validation_issues(errors, "plan"),
            repair_hint="Rewrite the plan using only allowed tools and required boundary steps.",
            next_node="plan_repair",
        )
    return ValidationResult(ok=True, warnings=warnings, next_node="executor")


__all__ = ["validate_plan", "validate_plan_semantics"]
