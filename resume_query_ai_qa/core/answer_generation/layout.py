"""YAML-driven answer layout selection."""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig


def infer_answer_layout(
    question: str,
    query_frame: dict[str, Any],
    ok_tools: set[str],
    config: ResumeQAConfig,
) -> tuple[str, dict[str, Any], str]:
    """推断答案布局并返回。"""
    layouts = config.answer_layout_rules()
    ordered = sorted(
        ((name, dict(payload or {})) for name, payload in layouts.items() if isinstance(payload, dict)),
        key=lambda item: int(item[1].get("priority", 0) or 0),
        reverse=True,
    )
    for name, payload in ordered:
        if name == "default":
            continue
        reason = match_layout_rule(question, query_frame, ok_tools, payload)
        if reason:
            return name, payload, reason
    default_name = str(query_frame.get("default_layout") or "default")
    return default_name, dict(layouts.get(default_name) or layouts.get("default") or {}), "fallback_default_layout"


def match_layout_rule(question: str, query_frame: dict[str, Any], ok_tools: set[str], layout: dict[str, Any]) -> str:
    """匹配结果布局规则并返回匹配结果。"""
    task_types = {str(item) for item in list(layout.get("task_types", []) or []) if str(item).strip()}
    if task_types and str(query_frame.get("task_type") or "") not in task_types:
        return ""
    freedom_levels = {str(item) for item in list(layout.get("freedom_levels", []) or []) if str(item).strip()}
    if freedom_levels and str(query_frame.get("freedom_level") or "") not in freedom_levels:
        return ""
    required = dict(layout.get("required_tools", {}) or {})
    all_tools = {str(item) for item in list(required.get("all", []) or []) if str(item).strip()}
    any_tools = {str(item) for item in list(required.get("any", []) or []) if str(item).strip()}
    if all_tools and not all_tools <= ok_tools:
        return ""
    if any_tools and not (any_tools & ok_tools):
        return ""
    groups = dict(layout.get("trigger_terms", {}) or {})
    for terms in groups.values():
        values = [str(item) for item in list(terms or []) if str(item).strip()]
        if values and not any(term in question for term in values):
            return ""
    return "matched_task_freedom_tools_terms"


def layout_contract(layout_name: str, layout_config: dict[str, Any]) -> dict[str, Any]:
    """获取布局合同并返回。"""
    return {
        "layout": layout_name,
        "sections": list(layout_config.get("sections", []) or []),
        "required_sections": list(layout_config.get("required_sections", []) or layout_config.get("sections", []) or []),
        "titles": dict(layout_config.get("titles", {}) or {}),
        "required_title_sections": list(layout_config.get("required_title_sections", []) or []),
        "first_section": str(layout_config.get("first_section") or ""),
        "section_contract": dict(layout_config.get("section_contract", {}) or {}),
        "writing_rules": list(layout_config.get("generation_instructions", []) or []),
        "hard_constraints": list(layout_config.get("hard_constraints", []) or []),
        "claim_contract": dict(layout_config.get("claim_contract", {}) or {}),
        "fallback_sections": list(layout_config.get("fallback_sections", []) or []),
    }


def validate_layout_contract(text: str, contract: dict[str, Any]) -> str:
    """仅校验配置中明确声明的可见标题与顺序规则。"""
    titles = {str(key): str(value).strip() for key, value in dict(contract.get("titles", {}) or {}).items()}
    for section in contract.get("required_title_sections", []) or []:
        section_id = str(section)
        title = titles.get(section_id, "")
        if title and title not in text:
            return f"layout_missing_title:{section_id}"
    first_section = str(contract.get("first_section") or "").strip()
    if first_section:
        title = titles.get(first_section, "")
        if title and not text.lstrip().startswith(title):
            return f"layout_first_section_mismatch:{first_section}"
    return ""
