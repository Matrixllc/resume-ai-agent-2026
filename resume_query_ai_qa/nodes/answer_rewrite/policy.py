"""Rule-driven policy for answer repair.

这个文件负责什么：
  只根据 answer_validator 返回的 ValidationIssue 分类 rewrite 策略。

应该从哪个函数读起：
  classify_answer_repair_policy()。

不会负责什么：
  不检查自然语言事实、不生成答案、不调用 LLM；这里只决定 rule fallback 还是
  LLM rewrite candidate。
"""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.schemas import ValidationIssue


def classify_answer_repair_policy(issues: list[ValidationIssue], config: ResumeQAConfig | None = None) -> dict[str, Any]:
    """按 ValidationIssue.category 判断当前答案问题应走 rule fallback 还是 LLM rewrite。"""
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
