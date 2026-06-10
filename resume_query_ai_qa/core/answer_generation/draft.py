"""Build layout rule drafts for constrained answer generation."""

from __future__ import annotations

from typing import Any


def build_rule_draft(query_frame: dict[str, Any], layout_name: str, layout_config: dict[str, Any]) -> dict[str, Any]:
    """构建规则draft并返回。"""
    return {
        "task_type": query_frame.get("task_type"),
        "freedom_level": query_frame.get("freedom_level"),
        "layout": layout_name,
        "slots": query_frame.get("slots") or {},
        "sections": list(layout_config.get("sections", []) or []),
        "required_sections": list(layout_config.get("required_sections", []) or layout_config.get("sections", []) or []),
        "titles": dict(layout_config.get("titles", {}) or {}),
        "required_title_sections": list(layout_config.get("required_title_sections", []) or []),
        "first_section": str(layout_config.get("first_section") or ""),
        "section_contract": build_section_contract(layout_config),
        "writing_rules": list(layout_config.get("generation_instructions", []) or []),
        "hard_constraints": build_hard_constraints(layout_config),
        "claim_contract": build_claim_contract(layout_config),
        "fallback_requirements": list(layout_config.get("fallback_sections", []) or []),
    }


def build_section_contract(layout_config: dict[str, Any]) -> dict[str, Any]:
    """构建章节合同并返回。"""
    return dict(layout_config.get("section_contract", {}) or {})


def build_hard_constraints(layout_config: dict[str, Any]) -> list[str]:
    """构建严格约束集合并返回。"""
    return [str(item) for item in list(layout_config.get("hard_constraints", []) or []) if str(item).strip()]


def build_claim_contract(layout_config: dict[str, Any]) -> dict[str, Any]:
    """构建声明合同并返回。"""
    return dict(layout_config.get("claim_contract", {}) or {})
