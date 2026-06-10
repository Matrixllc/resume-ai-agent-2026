"""Rule-driven policy for answer repair."""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.schemas import ValidationIssue


def classify_answer_repair_policy(issues: list[ValidationIssue], config: ResumeQAConfig | None = None) -> dict[str, Any]:
    """实现节点内的classify答案修复策略处理；输入来自当前节点契约，输出不越过节点职责边界。"""
    cfg = config or load_config()
    supported = {str(item) for item in list(dict(cfg.validation.get("answer_repair", {}) or {}).get("rule_repair_categories", []) or [])}
    hard_issues = [issue for issue in issues if issue.severity == "error"]
    categories = sorted({issue.category for issue in hard_issues})
    codes = sorted({issue.code for issue in hard_issues})
    # repairable=False means unsafe for local rewrite of the current answer.
    # A deterministic rule rebuild may still repair the issue by discarding it.
    non_local_repairable = [issue for issue in hard_issues if not issue.repairable]
    if not hard_issues:
        return {"action": "none", "categories": [], "codes": [], "reason": "no_answer_errors"}
    if all(issue.category in supported for issue in hard_issues):
        return {
            "action": "rule_repair",
            "categories": categories,
            "codes": codes,
            "reason": "deterministic_repair_supported",
            "non_local_repairable_codes": [issue.code for issue in non_local_repairable],
        }
    return {
        "action": "llm_rewrite",
        "categories": categories,
        "codes": codes,
        "reason": "requires_expression_rewrite",
        "non_local_repairable_codes": [issue.code for issue in non_local_repairable],
    }
