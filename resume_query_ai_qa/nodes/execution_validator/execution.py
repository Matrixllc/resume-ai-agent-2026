"""Execution Validator entrypoint."""

from __future__ import annotations

from typing import List

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.schemas import QueryPlan, RouterOutput, ToolResult, ValidationResult
from resume_query_ai_qa.core.rules.evidence_policy import validate_evidence_coverage
from resume_query_ai_qa.core.rules.behavior_contract import validation_issues

from .execution_lineage import validate_candidate_lineage
from .execution_requirements import is_allowed_business_limit_result, validate_required_tool_results
from .execution_results import validate_compare_results, validate_count_results, validate_empty_retrieval_results


def validate_execution(
    *,
    plan: QueryPlan,
    tool_results: List[ToolResult],
    config: ResumeQAConfig | None = None,
    router_output: RouterOutput | None = None,
    session_context: dict | None = None,
) -> ValidationResult:
    """校验计划执行结果并返回校验结果。"""
    cfg = config or load_config()
    errors: List[str] = []
    warnings: List[str] = []
    failed = [item for item in tool_results if not item.ok and not is_allowed_business_limit_result(item, cfg)]
    if failed:
        errors.extend(f"{item.tool_name} failed: {item.error}" for item in failed)

    errors.extend(validate_required_tool_results(plan, tool_results, cfg))
    if not any(is_allowed_business_limit_result(item, cfg) for item in tool_results):
        evidence_errors, evidence_warnings = validate_evidence_coverage(plan=plan, tool_results=tool_results, config=cfg)
        errors.extend(evidence_errors)
        warnings.extend(evidence_warnings)
    errors.extend(validate_count_results(plan, tool_results))
    errors.extend(validate_compare_results(plan, tool_results, cfg))
    errors.extend(validate_empty_retrieval_results(plan, tool_results, router_output=router_output, config=cfg))
    errors.extend(validate_candidate_lineage(plan, tool_results, router_output=router_output, session_context=session_context, config=cfg))

    if errors:
        return ValidationResult(
            ok=False,
            errors=errors,
            warnings=warnings,
            error_details=validation_issues(errors, "execution"),
            repair_hint="Add missing tool calls or repair failed tool arguments.",
            next_node="execution_repair",
        )
    return ValidationResult(ok=True, warnings=warnings, next_node="aggregator")


__all__ = ["validate_execution"]
