"""Structured issue helpers for answer validation."""

from __future__ import annotations

from typing import Literal

from resume_query_ai_qa.core.schemas import ValidationIssue


def issue(
    category: str,
    code: str,
    message: str,
    *,
    severity: Literal["error", "warning"] = "error",
    repairable: bool = True,
) -> ValidationIssue:
    """获取issue并返回。"""
    return ValidationIssue(category=category, code=code, message=message, severity=severity, repairable=repairable)
