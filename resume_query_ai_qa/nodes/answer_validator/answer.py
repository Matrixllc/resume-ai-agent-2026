"""Answer Validator entrypoint."""

from __future__ import annotations

from typing import List

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.schemas import AggregatedAnswer, QueryPlan, ToolResult, ValidationIssue, ValidationResult
from resume_query_ai_qa.core.rules.evidence_policy import validate_evidence_coverage

from .answer_claims import (
    validate_answer_count,
    validate_answer_evidence_refs,
    validate_answer_names,
    validate_answer_ranking,
    validate_claim_support,
    validate_required_structured_claims,
)
from .answer_layout import validate_answer_layout
from .answer_privacy import validate_answer_contact
from .issues import issue


def validate_answer(
    *,
    answer: AggregatedAnswer,
    tool_results: List[ToolResult],
    plan: QueryPlan | None = None,
    config: ResumeQAConfig | None = None,
) -> ValidationResult:
    """校验最终答案并返回校验结果。"""
    cfg = config or load_config()
    issues: List[ValidationIssue] = []
    warning_issues: List[ValidationIssue] = []

    issues.extend(validate_claim_support(answer, tool_results))
    issues.extend(validate_answer_count(answer, tool_results, cfg))
    issues.extend(validate_answer_names(answer, tool_results))
    issues.extend(validate_answer_ranking(answer, tool_results, cfg, plan))
    issues.extend(validate_answer_evidence_refs(answer, tool_results))
    issues.extend(validate_answer_contact(answer, tool_results, cfg))
    issues.extend(validate_answer_layout(answer, cfg))
    issues.extend(validate_required_structured_claims(answer, tool_results, plan))
    if plan is not None:
        evidence_errors, evidence_warnings = validate_evidence_coverage(plan=plan, tool_results=tool_results, config=cfg)
        warning_issues.extend(issue("evidence_coverage", "evidence_coverage_warning", message, severity="warning") for message in evidence_warnings)
        if answer.used_evidence_refs:
            issues.extend(issue("evidence_coverage", "evidence_coverage", message) for message in evidence_errors)

    errors = [issue.message for issue in issues]
    warnings = [issue.message for issue in warning_issues]
    if errors:
        return ValidationResult(
            ok=False,
            errors=errors,
            warnings=warnings,
            error_details=issues,
            repair_hint="Rewrite the answer using only claims supported by tool_results.",
            next_node="answer_rewrite",
        )
    return ValidationResult(ok=True, warnings=warnings, error_details=warning_issues, next_node="final")


__all__ = ["validate_answer"]
