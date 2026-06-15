"""Plan validator entrypoints.

这个文件负责什么：
- 汇总所有 QueryPlan 合同检查。
- 返回 graph 使用的 ValidationResult。

应该从哪个函数读起：
- validate_plan

不会负责什么：
- 不生成或修改 QueryPlan。
- 不调用工具。
- 不修复计划，修复由 plan_repair 负责。
"""

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
    """校验 QueryPlan 并返回 ValidationResult。

    检查顺序是 structure -> boundaries -> artifacts -> semantics。
    只要有错误，就返回 ok=False，并把错误交给 behavior_contract 分类。
    """
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
