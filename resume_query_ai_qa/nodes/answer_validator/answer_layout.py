"""Answer layout contract checks.

这个文件负责什么：
  根据 answer.warnings 中的 answer_layout:<layout>，读取 answer_layouts.yaml
  并校验最终 answer 文本的标题和章节合同。

应该从哪个函数读起：
  validate_answer_layout()。

不会负责什么：
  不选择 layout，不生成答案结构，不判断事实是否充分。
"""

from __future__ import annotations

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.answer_generation.layout import layout_contract, validate_layout_contract
from resume_query_ai_qa.core.schemas import AggregatedAnswer, ValidationIssue
from .issues import issue


def validate_answer_layout(answer: AggregatedAnswer, config: ResumeQAConfig) -> list[ValidationIssue]:
    """从 answer.warnings 读取 layout 名，并按 YAML layout contract 校验文本。"""
    layout = ""
    for warning in answer.warnings or []:
        value = str(warning)
        if value.startswith("answer_layout:"):
            layout = value.split(":", 1)[1].strip()
            break
    if not layout:
        return []
    configured = dict((config.answer_layouts or {}).get("layouts", {}) or {})
    if layout not in configured:
        return [issue("layout", "unknown_answer_layout", f"unknown answer layout: {layout}")]
    if "aggregator_fallback:hard_standard" in (answer.warnings or []):
        return []
    text = answer.answer or ""
    layout_config = dict(configured.get(layout, {}) or {})
    contract_reason = validate_layout_contract(text, layout_contract(layout, layout_config))
    if contract_reason:
        return [issue("layout", contract_reason.replace(":", "_"), contract_reason)]
    if layout == "candidate_blocks":
        titles = dict(layout_config.get("titles", {}) or {})
        basis_title = str(titles.get("main_basis") or "")
        personal_title = str(titles.get("personal_info") or "")
        check_title = str(titles.get("experience_check") or "")
        basis_index = text.find(basis_title)
        if basis_index < 0:
            return [issue("layout", "candidate_blocks_missing_main_basis", "candidate_blocks layout requires final main basis section")]
        if text.find(personal_title) < 0:
            return [issue("layout", "candidate_blocks_missing_personal_info", "candidate_blocks layout requires personal info inside candidate block")]
        check_index = text.rfind(check_title, 0, basis_index)
        if check_index < 0:
            return [issue("layout", "candidate_blocks_missing_experience_check", "candidate_blocks layout requires experience check before main basis")]
        first_basis = text.find(basis_title)
        first_personal = text.find(personal_title)
        if first_basis >= 0 and first_personal >= 0 and first_basis < first_personal:
            return [issue("layout", "candidate_blocks_main_basis_before_blocks", "candidate_blocks layout placed main basis before candidate blocks")]
    return []


__all__ = ["validate_answer_layout"]
