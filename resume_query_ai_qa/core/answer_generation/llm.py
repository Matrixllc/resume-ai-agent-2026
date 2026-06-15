"""LLM prompt, rewrite, drift checks, and grounding merge for Aggregator.

这个文件负责什么：
  调用 LLM 生成 AggregatedAnswer 文本，检查事实漂移，并把事实字段合并回 grounded。

应该从哪个函数读起：
  build_fill_prompt() -> reject_if_fact_drifted() -> merge_grounding()。

不会负责什么：
  不构建 grounded_context，不选择 layout，不调用工具。
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.llm import invoke_structured
from resume_query_ai_qa.core.schemas import AggregatedAnswer

from .grounding import allowed_candidate_names, ranking_sequence_from_context


class LLMAnswerDraft(BaseModel):
    """LLM-owned answer fields; grounding fields are merged from tool-derived context."""

    answer: str = ""
    warnings: list[str] = Field(default_factory=list)


def fill_answer_with_llm(payload: dict[str, Any], config: ResumeQAConfig) -> AggregatedAnswer:
    """调用 LLM，让它基于 question/rule_draft/grounded_context 生成答案文本。"""
    prompt = build_fill_prompt(payload)
    draft = invoke_structured(LLMAnswerDraft, prompt, config=config)
    return AggregatedAnswer(answer=draft.answer, warnings=draft.warnings)


def rewrite_answer_with_llm(payload: dict[str, Any], previous_answer: AggregatedAnswer, answer_errors: list[str], config: ResumeQAConfig) -> AggregatedAnswer:
    """调用大模型重写答案并返回。"""
    prompt = build_rewrite_prompt(payload, previous_answer, answer_errors)
    draft = invoke_structured(LLMAnswerDraft, prompt, config=config)
    return AggregatedAnswer(answer=draft.answer, warnings=draft.warnings)


def build_fill_prompt(payload: dict[str, Any]) -> str:
    """构建 aggregator fill prompt，明确 LLM 只能使用 grounded_context 中的事实。"""
    layout_requirements = build_layout_prompt_requirements(payload.get("rule_draft"))
    return f"""你是简历问答系统的 Aggregator。根据 layout rule draft 和 grounded context 生成中文答案。

硬规则:
- 只能使用 grounded_context 中的事实。
- 不要新增候选人、项目、公司、学校、技能、数量、排名、分数或 evidence_id。
- strict 场景不得改变数量、名单、排序、分数、比较对象。
- guided 场景可以选择重点，但 evidence 为空时必须说明不能确认。
- creative_grounded 场景可以生成问题，但只能基于 context 内项目/技能/证据，禁止敏感属性问题。
- required_sections 是必须回答的语义内容，不代表必须显示章节标题。
- required_title_sections 中的章节必须原样显示 titles 中配置的标题；first_section 必须位于答案开头。
- 可见章节标题必须使用纯文本标题，不要使用 Markdown 标题前缀，例如 #、##、###。
- 输出 JSON，只需要填写 answer 和 warnings；claims 和 used_evidence_refs 不要填写，系统会基于 context 回填。

layout 输出合同:
{layout_requirements}

payload:
{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}
"""


def build_layout_prompt_requirements(rule_draft: Any) -> str:
    """从layout合同生成通用提示词要求。"""
    if not isinstance(rule_draft, dict):
        return "- 未提供 layout rule_draft；仍需保持答案结构清晰。"
    titles = {str(key): str(value).strip() for key, value in dict(rule_draft.get("titles", {}) or {}).items() if str(value).strip()}
    required = [str(item) for item in list(rule_draft.get("required_title_sections", []) or []) if str(item).strip()]
    first_section = str(rule_draft.get("first_section") or "").strip()
    lines: list[str] = []
    if required:
        required_titles = [titles.get(section, section) for section in required]
        lines.append(f"- 必须原样显示这些可见章节标题：{', '.join(required_titles)}。")
    if first_section:
        first_title = titles.get(first_section, first_section)
        lines.append(f"- answer 字段的第一个可见字符必须是「{first_title}」的第一个字符，开头直接写「{first_title}」，不要在前面加编号、项目符号、空标题或 Markdown 标记。")
    if titles:
        ordered_titles = [f"{key}={value}" for key, value in titles.items()]
        lines.append(f"- 标题映射来自 YAML：{'; '.join(ordered_titles)}；需要展示标题时只能使用这些 title 文本。")
    lines.append("- 章节标题可以使用「标题：正文」格式；不要写成「## 标题」或「### 标题」。")
    return "\n".join(lines)


def build_rewrite_prompt(payload: dict[str, Any], previous_answer: AggregatedAnswer, answer_errors: list[str]) -> str:
    """构建rewrite提示词并返回。"""
    return f"""{build_fill_prompt(payload)}

上一版答案:
{previous_answer.model_dump_json(indent=2)}

answer_validator_errors:
{json.dumps(answer_errors, ensure_ascii=False, indent=2)}

只修复 validator 指出的事实或结构问题，不新增 context 外事实。
"""


def reject_if_fact_drifted(answer: AggregatedAnswer, context: dict[str, Any], rule_draft: dict[str, Any]) -> str:
    """识别非法IF事实drifted并返回。"""
    text = answer.answer or ""
    count = context.get("count") or {}
    if "value" in count and str(count.get("value")) not in text:
        return "count_missing_or_changed"
    allowed_names = allowed_candidate_names(context)
    for claim in answer.claims:
        if allowed_names and claim.claim_type in {"name", "profile", "ranking", "comparison", "evidence"}:
            drift = _unknown_candidate_claim(claim, allowed_names)
            if drift:
                return drift
    ranking = ranking_sequence_from_context(context)
    if ranking:
        positions = [text.find(name) for _rank, name in ranking if name in text]
        if positions and positions != sorted(positions):
            return "ranking_sequence_changed"
    if context.get("empty_flags", {}).get("evidence.empty") and not has_empty_evidence_disclaimer(text):
        return "missing_empty_evidence_disclaimer"
    return ""


def has_empty_evidence_disclaimer(text: str) -> bool:
    """Return whether text explains empty evidence and avoids a firm conclusion.

    The empty-evidence contract has two independent parts:
    1. the answer must tell the user the evidence/source is absent;
    2. the answer must avoid confirming the requested fact.

    Keeping these as semantic signal groups makes the guard tolerant to natural
    wording without accepting answers that only mention one side of the contract.
    """
    normalized = _normalize_disclaimer_text(text)
    if not normalized:
        return False
    return _has_evidence_absence_signal(normalized) and _has_uncertainty_signal(normalized)


def _normalize_disclaimer_text(text: str) -> str:
    """Normalize answer text before matching disclaimer signals."""
    return re.sub(r"\s+", "", str(text or "").lower())


def _has_evidence_absence_signal(text: str) -> bool:
    """Return whether text states that supporting evidence is absent."""
    evidence_terms = r"(证据|依据|材料|来源|记录|项目|经历|经验|结果|evidence|context)"
    absence_terms = r"(未|没|没有|无|缺少|缺乏|不足|为空|0|零|未能|不能|无法)"
    retrieval_terms = r"(查到|找到|返回|获得|检索到|提供|命中|支持|用于确认|可核查|明确)"
    return bool(
        re.search(absence_terms + r".{0,12}" + evidence_terms, text)
        or re.search(evidence_terms + r".{0,12}" + absence_terms, text)
        or re.search(absence_terms + r".{0,12}" + retrieval_terms, text)
        or re.search(r"(empty|no|zero).{0,12}(evidence|result|ref|context)", text)
    )


def _has_uncertainty_signal(text: str) -> bool:
    """Return whether text avoids confirming a fact without enough evidence."""
    confirm_terms = r"(确认|判断|核实|认定|证明|推断|下结论|支持该结论|得出结论|confirm|verify|conclude|infer)"
    uncertainty_terms = r"(不能|无法|难以|不足以|不应|不宜|不可|不能据此|无法据此|暂不能|目前不能|不确定)"
    return bool(
        re.search(uncertainty_terms + r".{0,12}" + confirm_terms, text)
        or re.search(confirm_terms + r".{0,12}" + uncertainty_terms, text)
        or re.search(r"(cannot|can't|unable|insufficient|not enough).{0,16}(confirm|verify|conclude|infer)", text)
    )


def _unknown_candidate_claim(claim: Any, allowed_names: set[str]) -> str:
    """获取未知候选人声明并返回。"""
    names_from_value = _claim_value_names(claim.value)
    if names_from_value:
        for name in names_from_value:
            if name not in allowed_names:
                return f"unknown_candidate:{name}"
        return ""
    subject = (claim.subject or claim.text or "").strip()
    if subject and _looks_like_single_candidate_name(subject) and subject not in allowed_names:
        return f"unknown_candidate:{subject}"
    return ""


def _claim_value_names(value: Any) -> list[str]:
    """获取声明值名称集合并返回。"""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _looks_like_single_candidate_name(value: str) -> bool:
    """判断单个候选人名称是否成立并返回布尔值。"""
    if not value:
        return False
    if any(marker in value for marker in ["，", "、", "。", "：", ":", "包括", "名单", "候选人", "领域"]):
        return False
    return len(value) <= 24


def merge_grounding(answer: AggregatedAnswer, grounded: AggregatedAnswer) -> AggregatedAnswer:
    """保留 LLM answer 文本，但用 grounded claims/evidence/warnings 做事实收口。"""
    return answer.model_copy(
        update={
            "claims": grounded.claims,
            "used_evidence_refs": grounded.used_evidence_refs,
            "warnings": _dedupe([*grounded.warnings, *answer.warnings]),
        }
    )


def _dedupe(values: list[str]) -> list[str]:
    """去重结果并返回。"""
    output: list[str] = []
    for value in values:
        if value not in output:
            output.append(value)
    return output
