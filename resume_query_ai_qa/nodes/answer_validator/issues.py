"""Structured issue helpers for answer validation.

这个文件负责什么：
  统一创建 answer_validator 返回的 ValidationIssue，保证 category/code/message
  形状稳定，方便 route、rewrite 和 diagnosis 使用。

应该从哪个函数读起：
  issue()。
"""

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
    """创建一条稳定结构的答案校验 issue。"""
    return ValidationIssue(category=category, code=code, message=message, severity=severity, repairable=repairable)
