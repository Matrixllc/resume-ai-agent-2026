"""Clarification node helpers."""

from __future__ import annotations

from resume_query_ai_qa.core.config import load_config
from resume_query_ai_qa.core.schemas import ResumeQAState, RouterOutput, ValidationIssue
from resume_query_ai_qa.nodes.session_context import candidate_options


def build_clarification(
    qa: ResumeQAState,
    *,
    issues: list[ValidationIssue] | None = None,
    router_output: RouterOutput | None = None,
) -> tuple[str, list[str]]:
    """根据校验问题生成澄清问题和选项并返回。"""
    active_issues = list(issues or [])
    policy = dict(load_config().validation.get("clarification", {}) or {})
    configured = dict(policy.get("codes", {}) or {})
    default = dict(policy.get("default", {}) or {})
    issue = active_issues[0] if active_issues else None
    selected = dict(configured.get(issue.code, {}) or {}) if issue else default
    message = str(selected.get("message") or default.get("message") or "请补充完成当前查询所需的信息。")
    if issue and issue.code == "context_missing":
        ref_type = str(router_output.context_policy.context_ref_type or "") if router_output else ""
        message = str(dict(selected.get("context_messages", {}) or {}).get(ref_type) or message)
    options = candidate_options() if bool(selected.get("include_candidate_options", False)) else []
    return message, options
