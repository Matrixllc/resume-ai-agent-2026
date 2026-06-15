"""Answer privacy checks.

这个文件负责什么：
  直接扫描最终 answer 文本，拦截默认不应展示的联系方式和敏感属性。

应该从哪个函数读起：
  validate_answer_contact()。

不会负责什么：
  不判断候选人是否适合展示隐私信息；是否允许展示 contact 只看工具结果和 YAML。
"""

from __future__ import annotations

import re
from typing import List

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.schemas import AggregatedAnswer, ToolResult, ValidationIssue
from .issues import issue


def validate_answer_contact(
    answer: AggregatedAnswer,
    tool_results: List[ToolResult],
    config: ResumeQAConfig,
) -> List[ValidationIssue]:
    """按 validation.yaml.privacy 扫描 email、phone、wechat 和敏感属性。"""
    privacy = dict(config.validation.get("privacy", {}) or {})
    if not privacy.get("hide_contact_by_default", True):
        return []
    if _contact_explicitly_allowed(tool_results):
        return []
    text = answer.answer
    phone_scan_text = _strip_date_ranges(text)
    if re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text):
        return [issue("privacy", "email_exposed", "answer exposes email while contact is hidden by default", repairable=False)]
    if re.search(r"(?<!\d)(?:\+?\d[\d -]{7,}\d)(?!\d)", phone_scan_text):
        return [issue("privacy", "phone_exposed", "answer exposes phone-like contact while contact is hidden by default", repairable=False)]
    contact_aliases = dict(privacy.get("contact_aliases", {}) or {})
    if any(str(token).lower() in text.lower() for token in list(contact_aliases.get("wechat", []) or [])):
        return [issue("privacy", "wechat_exposed", "answer may expose wechat contact while contact is hidden by default", repairable=False)]
    sensitive = _sensitive_attribute_hits(text, privacy)
    if sensitive:
        return [issue("privacy", "sensitive_attribute_exposed", f"answer may expose sensitive attributes: {sensitive}", repairable=False)]
    return []


def _contact_explicitly_allowed(tool_results: List[ToolResult]) -> bool:
    """如果 profile 工具明确返回 contact_hidden=false，则允许展示联系方式。"""
    for result in tool_results:
        if result.tool_name == "get_candidate_profile_intro" and result.ok and isinstance(result.data, dict):
            if not result.data.get("contact_hidden", True) and result.data.get("contact"):
                return True
    return False


def _strip_date_ranges(text: str) -> str:
    """移除日期范围，避免把工作年月误判成 phone-like 文本。"""
    patterns = [
        r"(?:19|20)\d{2}[-./年](?:0?[1-9]|1[0-2])?\s*(?:-|—|至|到|~|～)\s*(?:(?:19|20)\d{2}[-./年](?:0?[1-9]|1[0-2])?|至今|present|now|current)",
        r"(?:19|20)\d{2}\s*(?:-|—|至|到|~|～)\s*(?:(?:19|20)\d{2}|至今|present|now|current)",
    ]
    output = text
    for pattern in patterns:
        output = re.sub(pattern, "", output, flags=re.IGNORECASE)
    return output


def _sensitive_attribute_hits(text: str, privacy: dict) -> List[str]:
    """返回最终答案文本中命中的敏感属性 key。"""
    configured = [str(item).strip() for item in list(privacy.get("sensitive_attributes", []) or []) if str(item).strip()]
    aliases = dict(privacy.get("sensitive_attribute_aliases", {}) or {})
    hits: List[str] = []
    for key in configured:
        terms = aliases.get(key, [key])
        if any(term and term in text for term in terms):
            hits.append(key)
    return hits


__all__ = ["validate_answer_contact"]
